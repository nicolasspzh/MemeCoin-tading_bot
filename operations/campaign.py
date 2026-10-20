"""Finite, resumable collection on an already-running host.

This supervisor survives a disconnected shell, not machine shutdown/suspension.
It does not schedule cloud wakeups or promise uninterrupted hosting.
"""
import argparse
import asyncio
import fcntl
import hashlib
import json
import logging
import resource
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import selectors
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta

from backtesting.evaluation import EXCLUDED_SETTINGS, code_digest, digest, utc
from config.settings import Settings, load_settings
from data.database import Database
from data.models import Decision, utcnow
from main import collect, single_writer
from collectors.schedule import FOLLOWUP_SECONDS
from trading.engine import Engine

ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("collection-campaign")


def atomic_json(path, value):
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w") as out:
        json.dump(value, out, indent=2)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())
    temporary.replace(path)


def read_json(path, fallback=None):
    return json.loads(path.read_text()) if path.exists() else fallback


def operations_digest():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class Recorder(Engine):
    """Reuse collection/schema/labels without generating paper orders or PnL."""
    observation_only = True

    def __init__(self, db, settings, feature_until=None):
        self.feature_until = feature_until
        if db.source != "dexscreener":
            raise ValueError("Observation campaign requires market source")
        if (db.counts()["fills"] or db.conn.execute("SELECT count(*) FROM paper_orders").fetchone()[0]
                or db.load_wallet().positions):
            raise ValueError("Campaign cannot reuse a trading database")
        super().__init__(db, settings)
        with db.conn:
            db.conn.execute("INSERT OR IGNORE INTO metadata VALUES('collection_mode','observation_only')")

    def process(self, snapshot, now=None):
        now = now or utcnow()
        with self.db.conn:
            self.db.conn.execute("BEGIN IMMEDIATE")
            previous = self.db.latest(snapshot.token, snapshot.pair)
            if previous and snapshot.received_at <= previous.received_at:
                return None
            holder = snapshot.mint_risk.holder_risk if snapshot.mint_risk else None
            if holder and holder.evidence_payload is not None:
                evidence = json.dumps(holder.evidence_payload, sort_keys=True, separators=(",", ":"))
                if hashlib.sha256(evidence.encode()).hexdigest() != holder.evidence_sha256:
                    raise ValueError("Risk evidence fingerprint mismatch")
                self.db.conn.execute("INSERT OR IGNORE INTO risk_evidence VALUES(?,?)", (holder.evidence_sha256, evidence))
            sid = self.db.add_snapshot(snapshot)
            decision = Decision(action="SKIP", reasons=["observation_only"])
            self.db.conn.execute("INSERT INTO decisions(snapshot_id,run_id,signal_at,action,payload) VALUES(?,?,?,?,?)",
                                 (sid, self.run_id, now.timestamp(), decision.action, decision.model_dump_json()))
        return decision


def initialize(directory, until, settings, *, now=None):
    now = now or utcnow()
    until = utc(until)
    if not now < until <= now + timedelta(days=14):
        raise ValueError("Campaign end must be in the next fourteen days")
    if not settings.require_verified_holder_risk:
        raise ValueError("Campaign requires current risk checks")
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "backups").mkdir()
    (directory / "logs").mkdir()
    manifest = {"version": 1, "created_at": now.isoformat(), "until": until.isoformat(),
                "source": "dexscreener", "mode": "observation_only", "code_sha256": code_digest(),
                "operations_sha256": operations_digest(),
                "settings": settings.model_dump(mode="json", exclude=EXCLUDED_SETTINGS),
                "cycles_per_worker": 90, "stall_seconds": 300, "backup_interval_seconds": 3600,
                "minimum_free_bytes": 2 * 1024**3, "backup_slots": 2,
                "hosting": "current host only; no cloud wakeup or boot service configured"}
    if settings.observation_cohorts:
        manifest['feature_until'] = (until - timedelta(seconds=FOLLOWUP_SECONDS)).isoformat()
        manifest['followup_grace_seconds'] = FOLLOWUP_SECONDS
    atomic_json(directory / "manifest.json", {"manifest": manifest, "sha256": digest(manifest)})
    return manifest


def load_manifest(directory):
    envelope = read_json(directory / "manifest.json")
    manifest = envelope["manifest"]
    if digest(manifest) != envelope["sha256"]:
        raise ValueError("Campaign manifest changed")
    if manifest["code_sha256"] != code_digest() or manifest["operations_sha256"] != operations_digest():
        raise ValueError("Campaign software changed; review and create a new campaign")
    return manifest


def locked(directory):
    path = directory / "supervisor.lock"
    if not path.exists():
        return False
    with path.open("a") as fd:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False
        except BlockingIOError:
            return True


def status(directory):
    state = read_json(directory / "state.json", {})
    manifest = read_json(directory / "manifest.json", {}).get("manifest", {})
    result = {"directory": str(directory), "supervisor_running": locked(directory),
              "stop_requested": (directory / "stop.request").exists(), "until": manifest.get("until"),
              "state": state, "hosting": manifest.get("hosting")}
    path = directory / "observations.sqlite3"
    if path.exists():
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5) as db:
            db.execute("BEGIN")
            rows, first, last = db.execute("SELECT count(*),min(received_at),max(received_at) FROM snapshots").fetchone()
            priced, last_price = db.execute("SELECT count(*),max(received_at) FROM snapshots WHERE price IS NOT NULL").fetchone()
            cycles = db.execute("SELECT count(*) FROM collector_health WHERE source='collector' AND kind='cycle'").fetchone()[0]
            result["data"] = {"snapshots": rows, "tokens": db.execute("SELECT count(distinct token) FROM snapshots").fetchone()[0],
                              "first_observation_at": datetime.fromtimestamp(first, UTC).isoformat() if first else None,
                              "last_observation_at": datetime.fromtimestamp(last, UTC).isoformat() if last else None,
                              "priced_snapshots": priced,
                              "last_quote_at": datetime.fromtimestamp(last_price, UTC).isoformat() if last_price else None,
                              "last_quote_age_seconds": round(utcnow().timestamp() - last_price, 1) if last_price else None,
                              "cycles": cycles,
                              "attempts": dict(db.execute("SELECT status,count(*) FROM collection_attempts GROUP BY status")),
                              "orders": db.execute("SELECT count(*) FROM paper_orders").fetchone()[0],
                              "fills": db.execute("SELECT count(*) FROM fills").fetchone()[0],
                              "outcomes": [{"horizon_seconds": row[0], "total": row[1], "observed": row[2], "due": row[3]}
                                for row in db.execute("SELECT horizon_seconds,count(*),count(future_snapshot_id),sum(target_at<=?) FROM outcomes GROUP BY horizon_seconds", (utcnow().timestamp(),))]}
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='observation_tracks'").fetchone():
                result['observation_tracks'] = dict(db.execute("""SELECT CASE WHEN completed_at IS NOT NULL THEN 'completed'
                    WHEN primary_until>? THEN 'primary' ELSE 'followup' END,count(*)
                    FROM observation_tracks GROUP BY 1""", (utcnow().timestamp(),)))
                result['rpc_request_budget'] = dict(db.execute('SELECT utc_day,requests FROM rpc_request_budget'))
                result['rpc_budget_limits'] = {k: manifest.get('settings', {}).get(k)
                    for k in ('rpc_daily_request_limit', 'rpc_total_request_limit')}
                result['observation_phases'] = dict(db.execute("SELECT coalesce(json_extract(payload,'$.observation_phase'),'legacy'),count(*) FROM snapshots GROUP BY 1"))
    return result


def backup_database(directory, slot, minimum_free_bytes=0):
    source = directory / "observations.sqlite3"
    if not source.exists():
        return None
    target = directory / "backups" / f"observations-{slot}.sqlite3"
    temporary = target.with_suffix(".pending")
    # Includes committed WAL state. Never copy a live SQLite file with cp.
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=10) as src:
        size = src.execute("PRAGMA page_count").fetchone()[0] * src.execute("PRAGMA page_size").fetchone()[0]
        if shutil.disk_usage(directory).free < size + minimum_free_bytes:
            raise OSError("Insufficient space for a new backup")
        with sqlite3.connect(temporary) as dest:
            src.backup(dest, pages=128, sleep=.01)
            if dest.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Backup integrity check failed")
    temporary.replace(target)
    return {"at": utcnow().isoformat(), "path": str(target), "bytes": target.stat().st_size, "integrity": "ok"}


def configure_logging(directory, name):
    handler = RotatingFileHandler(directory / "logs" / f"{name}.log", maxBytes=5_000_000, backupCount=3)
    handler.setFormatter(logging.Formatter("%(asctime)sZ %(levelname)s %(message)s"))
    logging.Formatter.converter = time.gmtime
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def worker(directory):
    manifest = load_manifest(directory)
    if utcnow() >= utc(manifest["until"]):
        return 0
    settings = load_settings().model_copy(update=Settings.model_validate(manifest["settings"]).model_dump(
        exclude=EXCLUDED_SETTINGS))
    configure_logging(directory, "collector")
    path = directory / "observations.sqlite3"
    with single_writer(path):
        db = Database(path, "dexscreener")
        try:
            feature_until = utc(manifest['feature_until']).timestamp() if manifest.get('feature_until') else None
            return asyncio.run(collect(Recorder(db, settings, feature_until), once=False, cycles=manifest["cycles_per_worker"]))
        finally:
            db.close()


def stop_child(child):
    if child.poll() is not None:
        return
    try:
        os.killpg(child.pid, signal.SIGINT)
        try:
            child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=5)
    except ProcessLookupError:
        child.wait(timeout=5)


def parse_summaries(buffer):
    decoded = []
    while buffer.strip():
        buffer = buffer.lstrip()
        try:
            value, end = json.JSONDecoder().raw_decode(buffer)
        except json.JSONDecodeError:
            break
        decoded.append(value)
        buffer = buffer[end:]
    if len(buffer) > 1_000_000:
        raise ValueError("Unexpected collector output")
    return decoded, buffer


def supervise(directory, lock_fd):
    manifest = load_manifest(directory)
    configure_logging(directory, "supervisor")
    # The lock is inherited from start, so concurrent starts cannot race.
    lock = os.fdopen(lock_fd, "a")
    state = read_json(directory / "state.json", {})
    state.update(status="starting", supervisor_pid=os.getpid(), started_at=utcnow().isoformat())
    for key in ("stopped_at", "error_type", "restart_reason"):
        state.pop(key, None)
    state.setdefault("worker_launches", 0)
    state.setdefault("rpc_requests", 0)
    state.setdefault("rpc_successes", 0)
    state.setdefault("completed_cycles", 0)
    state.setdefault("backup_count", 0)
    atomic_json(directory / "state.json", state)
    stop = [False]
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.__setitem__(0, True))
    child, failures = None, 0
    last_backup = utc(state["last_backup"]["at"]).timestamp() if state.get("last_backup") else 0
    try:
        while utcnow() < utc(manifest["until"]) and not stop[0] and not (directory / "stop.request").exists():
            load_manifest(directory)
            if shutil.disk_usage(directory).free < manifest["minimum_free_bytes"]:
                state.update(status="disk_space_low")
                break
            child = subprocess.Popen([sys.executable, "-u", "-m", "operations.campaign", "worker", "--directory", str(directory)],
                                     cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, start_new_session=True)
            state.update(status="running", worker_pid=child.pid, worker_launches=state["worker_launches"] + 1)
            buffer, previous_requests, previous_successes = "", 0, 0
            last_progress, last_state, worker_cycles = time.monotonic(), 0, 0
            selector = selectors.DefaultSelector()
            selector.register(child.stdout, selectors.EVENT_READ)
            reason = None
            def consume(chunk):
                nonlocal buffer, previous_requests, previous_successes, last_progress, worker_cycles
                buffer += chunk.decode()
                summaries, buffer = parse_summaries(buffer)
                for summary in summaries:
                    requests = summary["rpc_totals"].get("requests", 0)
                    successes = summary["rpc_totals"].get("successes", 0)
                    state["rpc_requests"] += requests - previous_requests
                    state["rpc_successes"] += successes - previous_successes
                    previous_requests, previous_successes = requests, successes
                    state["completed_cycles"] += 1
                    state["last_cycle_at"] = utcnow().isoformat()
                    state["last_cycle"] = {key: summary[key] for key in ("cycle_quotes", "cycle_errors", "cycle_onchain_errors", "cycle_elapsed_seconds", "cycle_deferred")}
                    state["worker_rss_peak_kb"] = max(state.get("worker_rss_peak_kb", 0), summary.get("rss_peak_kb", 0))
                    state["data_degraded"] = bool(not summary["cycle_quotes"] or summary["cycle_errors"] or summary["cycle_onchain_errors"] or summary.get("pool_discovery", {}).get("errors"))
                    last_progress = time.monotonic()
                    worker_cycles += 1

            while True:
                for key, _ in selector.select(timeout=1):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if chunk:
                        consume(chunk)
                    else:
                        selector.unregister(key.fileobj)
                if child.poll() is not None:
                    # Capture the final flushed summary even when the child exits
                    # before the first poll. The pipe is at EOF after child exit.
                    consume(child.stdout.read())
                    break
                if stop[0] or (directory / "stop.request").exists(): reason = "stopped_by_request"
                elif utcnow() >= utc(manifest["until"]): reason = "completed_scheduled_window"
                elif shutil.disk_usage(directory).free < manifest["minimum_free_bytes"]: reason = "disk_space_low"
                elif time.monotonic() - last_progress > manifest["stall_seconds"]: reason = "worker_stalled"
                if time.monotonic() - last_state >= 5 or reason:
                    state["heartbeat_at"] = utcnow().isoformat()
                    state["supervisor_rss_peak_kb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                    atomic_json(directory / "state.json", state)
                    last_state = time.monotonic()
                if reason:
                    stop_child(child)
                    consume(child.stdout.read())
                    break
                if worker_cycles and time.time() - last_backup >= manifest["backup_interval_seconds"]:
                    try:
                        backup = backup_database(directory, state["backup_count"] % manifest["backup_slots"], manifest["minimum_free_bytes"])
                        if backup:
                            state["last_backup"] = backup
                            state["backup_count"] += 1
                            state.pop("backup_error_type", None)
                    except Exception as error:
                        state["backup_error_type"] = type(error).__name__
                        log.warning("Backup failed: %s", type(error).__name__)
                    last_backup = time.time()
            selector.close()
            child.stdout.close()
            state["last_worker_exit"] = child.wait()
            state["worker_pid"] = None
            if reason and reason != "worker_stalled":
                state["status"] = reason
                break
            failures = failures + 1 if worker_cycles == 0 else 0
            if failures >= 5:
                state["status"] = "repeated_start_failure"
                break
            state.update(status="restarting", restart_reason=reason or "bounded_worker_finished")
            atomic_json(directory / "state.json", state)
            for _ in range(min(60, 5 * 2**failures)):
                if stop[0] or (directory / "stop.request").exists() or utcnow() >= utc(manifest["until"]): break
                time.sleep(1)
        if state["status"] in ("running", "starting", "restarting"):
            state["status"] = "completed_scheduled_window" if utcnow() >= utc(manifest["until"]) else "stopped_by_request"
    except Exception as error:
        state.update(status="supervisor_error", error_type=type(error).__name__)
        log.error("Supervisor failed: %s", type(error).__name__)
    finally:
        if child is not None:
            stop_child(child)
        state.update(worker_pid=None, stopped_at=utcnow().isoformat(), heartbeat_at=utcnow().isoformat())
        if shutil.disk_usage(directory).free >= manifest["minimum_free_bytes"]:
            try:
                backup = backup_database(directory, state["backup_count"] % manifest["backup_slots"], manifest["minimum_free_bytes"])
                if backup:
                    state["last_backup"] = backup
                    state["backup_count"] += 1
            except Exception as error:
                state["backup_error_type"] = type(error).__name__
        atomic_json(directory / "state.json", state)
        lock.close()


def start(directory):
    manifest = load_manifest(directory)
    if utcnow() >= utc(manifest["until"]):
        raise ValueError("Campaign end has already passed")
    with (directory / "supervisor.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "already_running"}
        (directory / "stop.request").unlink(missing_ok=True)
        child = subprocess.Popen([sys.executable, "-m", "operations.campaign", "supervise", "--directory", str(directory),
                                  "--lock-fd", str(lock.fileno())], cwd=ROOT, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                                 pass_fds=(lock.fileno(),))
    return {"status": "start_requested", "pid": child.pid, "directory": str(directory)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "start", "stop", "status", "worker", "supervise"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--until")
    parser.add_argument("--lock-fd", type=int)
    parser.add_argument("--max-tokens", type=int, default=10)
    args = parser.parse_args()
    directory = args.directory.resolve()
    try:
        if args.command == "init":
            settings = load_settings().model_copy(update={"max_watch_tokens": args.max_tokens, "discovery_poll_seconds": 60})
            settings = Settings.model_validate(settings.model_dump())
            if not args.until: raise ValueError("--until is required")
            initialize(directory, args.until, settings)
            output = {"status": "initialized", "directory": str(directory)}
        elif args.command == "start": output = start(directory)
        elif args.command == "stop":
            if not (directory / "manifest.json").exists(): raise ValueError("Unknown campaign")
            (directory / "stop.request").touch()
            output = {"status": "stop_requested"}
        elif args.command == "status": output = status(directory)
        elif args.command == "worker": return worker(directory)
        else:
            if args.lock_fd is None: raise ValueError("Use start to launch the supervisor")
            supervise(directory, args.lock_fd)
            return 0
        print(json.dumps(output, indent=2))
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        print(f"Campaign command failed: {type(error).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
