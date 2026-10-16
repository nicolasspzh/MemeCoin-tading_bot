import fcntl
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from config.settings import Settings
from data.database import Database
from data.models import HolderRisk, utcnow
from operations import campaign
from trading.engine import Engine


@pytest.fixture
def directory(tmp_path):
    path = tmp_path / "campaign"
    campaign.initialize(path, (utcnow() + timedelta(days=7)).isoformat(), Settings())
    return path


@pytest.fixture
def market_quote(quote):
    wsol = "So11111111111111111111111111111111111111112"

    def make(*args, **kwargs):
        # 100 SOL quote reserve at USD 100 per SOL: USD 20'000 verified two-sided liquidity.
        kwargs.setdefault("raw", {"quoteToken": {"address": wsol}, "priceUsd": "1", "priceNative": "0.01"})
        snapshot = quote(*args, source="dexscreener", **kwargs)
        snapshot.mint_risk.risk_version = 3
        snapshot.mint_risk.holder_risk = HolderRisk(
            token=snapshot.token, pair=snapshot.pair, checked_at=snapshot.received_at,
            slot=1, pool_program="test-program", status="complete",
            top10_owner_fraction_lower=Decimal(".25"), top10_owner_fraction_upper=Decimal(".25"),
            creator_observed_fraction=Decimal(0), lp_nonredeemable_fraction=Decimal(1),
            pool_details={"mints": [snapshot.token, wsol],
                          "raw_vault_reserves_after_fees": ["1000000", "100000000000"]})
        return snapshot
    return make


def test_observations_remain_order_free_and_labels_survive_restart(directory, market_quote):
    path = directory / "observations.sqlite3"
    db = Database(path, "dexscreener")
    recorder = campaign.Recorder(db, Settings())
    for second, price in [(0, "1"), (20, "1.03"), (40, "1.04")]:
        snapshot = market_quote(second, price_usd=Decimal(price))
        assert recorder.process(snapshot).reasons == ["observation_only"]
    db.close()
    db = Database(path, "dexscreener")
    try:
        recorder = campaign.Recorder(db, Settings())
        assert recorder.process(snapshot) is None
        assert db.counts() == {"tokens": 1, "snapshots": 3, "decisions": 3, "fills": 0}
        assert db.conn.execute("SELECT count(*) FROM paper_orders").fetchone()[0] == 0
        assert db.conn.execute("SELECT future_snapshot_id FROM outcomes WHERE snapshot_id=1 AND horizon_seconds=30").fetchone()[0] == 3
        assert db.load_wallet().cash == Decimal(50)
    finally:
        db.close()


def test_recorder_rejects_demo_and_existing_trading_database(tmp_path, market_quote):
    db = Database(tmp_path / "demo.sqlite3", "demo")
    with pytest.raises(ValueError, match="market source"):
        campaign.Recorder(db, Settings())
    db.close()
    db = Database(tmp_path / "trades.sqlite3", "dexscreener")
    try:
        engine = Engine(db, Settings(paper_failure_probability=0))
        for second, price in [(0, "1"), (20, "1.03"), (40, "1.04")]:
            snapshot = market_quote(second, price_usd=Decimal(price))
            engine.process(snapshot, snapshot.received_at)
        assert db.pending_orders() or db.counts()["fills"]
        with pytest.raises(ValueError, match="trading database"):
            campaign.Recorder(db, Settings())
    finally:
        db.close()


def test_account_evidence_is_atomic_and_deduplicated(directory, quote):
    db = Database(directory / "observations.sqlite3", "dexscreener")
    try:
        recorder = campaign.Recorder(db, Settings())
        snapshot = quote(source="dexscreener")
        proof = {"public_account": "example"}
        sha = hashlib.sha256(json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        holder = HolderRisk(token=snapshot.token, pair=snapshot.pair, checked_at=snapshot.received_at,
                            slot=1, pool_program="example", status="complete",
                            evidence_payload=proof, evidence_sha256="invalid")
        snapshot.mint_risk.holder_risk = holder
        with pytest.raises(ValueError, match="fingerprint"):
            recorder.process(snapshot)
        assert db.counts()["snapshots"] == 0
        holder.evidence_sha256 = sha
        recorder.process(snapshot)
        recorder.process(snapshot.model_copy(update={"received_at": snapshot.received_at + timedelta(seconds=20)}))
        assert db.conn.execute("SELECT count(*) FROM risk_evidence").fetchone()[0] == 1
        with pytest.raises(ValueError, match="source"):
            recorder.process(quote(60))
        assert db.counts()["snapshots"] == 2
    finally:
        db.close()


def test_manifest_excludes_credentials_and_detects_mutation(tmp_path, monkeypatch):
    directory = tmp_path / "safe"
    settings = Settings(solana_rpc_url="https://example.com/?api-key=secret-value")
    until = (utcnow() + timedelta(days=7)).isoformat()
    campaign.initialize(directory, until, settings)
    serialized = (directory / "manifest.json").read_text()
    assert "secret-value" not in serialized and "solana_rpc_url" not in serialized
    assert campaign.load_manifest(directory)["mode"] == "observation_only"
    monkeypatch.setattr(campaign, "code_digest", lambda: "changed")
    with pytest.raises(ValueError, match="software changed"):
        campaign.load_manifest(directory)
    monkeypatch.undo()
    envelope = json.loads(serialized)
    envelope["manifest"]["settings"]["poll_seconds"] = 100
    campaign.atomic_json(directory / "manifest.json", envelope)
    with pytest.raises(ValueError, match="manifest changed"):
        campaign.load_manifest(directory)


@pytest.mark.parametrize("offset", [-1, 15 * 86400])
def test_campaign_has_bounded_future_deadline(tmp_path, offset):
    with pytest.raises(ValueError, match="fourteen days"):
        campaign.initialize(tmp_path / "invalid", (utcnow() + timedelta(seconds=offset)).isoformat(), Settings())
    assert not (tmp_path / "invalid").exists()


def test_existing_campaign_cannot_be_overwritten(directory):
    with pytest.raises(FileExistsError):
        campaign.initialize(directory, (utcnow() + timedelta(days=1)).isoformat(), Settings())


def test_status_distinguishes_missing_observations_from_valid_prices(directory, quote):
    db = Database(directory / "observations.sqlite3", "dexscreener")
    try:
        recorder = campaign.Recorder(db, Settings())
        recorder.process(quote(source="dexscreener"))
        recorder.process(quote(60, source="dexscreener", price_usd=None))
        result = campaign.status(directory)
        assert result["data"]["snapshots"] == 2
        assert result["data"]["priced_snapshots"] == 1
        assert result["data"]["last_quote_at"] == quote().received_at.isoformat()
        assert result["data"]["last_observation_at"] == quote(60).received_at.isoformat()
    finally:
        db.close()


def test_online_backup_includes_wal_and_rotates_without_modifying_source(directory, quote, monkeypatch):
    db = Database(directory / "observations.sqlite3", "dexscreener")
    try:
        recorder = campaign.Recorder(db, Settings())
        recorder.process(quote(source="dexscreener"))
        for second, slot in [(20, 0), (40, 1), (60, 0)]:
            recorder.process(quote(second, source="dexscreener"))
            result = campaign.backup_database(directory, slot)
            with sqlite3.connect(result["path"]) as copy:
                assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert copy.execute("SELECT count(*) FROM snapshots").fetchone()[0] == second // 20 + 1
        assert len(list((directory / "backups").glob("*.sqlite3"))) == 2
        assert db.counts()["snapshots"] == 4
        before = (directory / "backups/observations-0.sqlite3").read_bytes()
        monkeypatch.setattr(campaign.shutil, "disk_usage", lambda _: SimpleNamespace(free=1))
        with pytest.raises(OSError, match="space"):
            campaign.backup_database(directory, 0, 1)
        assert (directory / "backups/observations-0.sqlite3").read_bytes() == before
    finally:
        db.close()


def test_output_parser_handles_partial_and_consecutive_json():
    first, remainder = campaign.parse_summaries('  {"a": 1}\n {"b":')
    assert first == [{"a": 1}]
    second, remainder = campaign.parse_summaries(remainder + ' 2}\n')
    assert second == [{"b": 2}] and not remainder.strip()
    with pytest.raises(ValueError, match="output"):
        campaign.parse_summaries("?" * 1_000_001)


def test_duplicate_start_never_spawns_another_collector(directory, monkeypatch):
    with (directory / "supervisor.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        monkeypatch.setattr(campaign.subprocess, "Popen", lambda *a, **k: pytest.fail("duplicate worker"))
        assert campaign.start(directory)["status"] == "already_running"
        assert campaign.status(directory)["supervisor_running"]
    assert not campaign.status(directory)["supervisor_running"]


SUMMARY = {"rpc_totals": {"requests": 3, "successes": 2}, "cycle_quotes": 1,
           "cycle_errors": 0, "cycle_onchain_errors": 0, "cycle_elapsed_seconds": .1, "cycle_deferred": 2}


def run_supervisor(directory, monkeypatch, worker_scripts, *, free_bytes=10 * 1024**3, launch_states=None):
    # Exercise real pipes, subprocesses, signals and final output draining;
    # replace the network worker and explicitly control the disk-space input.
    # Debian /tmp can be a tmpfs smaller than the production 2 GiB floor.
    real_popen = subprocess.Popen
    scripts = iter(worker_scripts)
    def popen(*args, **kwargs):
        if launch_states is not None:
            launch_states.append(campaign.read_json(directory / "state.json"))
        return real_popen([sys.executable, "-u", "-c", next(scripts)], **kwargs)
    monkeypatch.setattr(campaign.subprocess, "Popen", popen)
    monkeypatch.setattr(campaign, "configure_logging", lambda *a: None)
    monkeypatch.setattr(campaign.signal, "signal", lambda *a: None)
    monkeypatch.setattr(campaign.time, "sleep", lambda _: None)
    monkeypatch.setattr(campaign.shutil, "disk_usage", lambda _: SimpleNamespace(free=free_bytes))
    with (directory / "supervisor.lock").open("a") as fd:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        campaign.supervise(directory, os.dup(fd.fileno()))
    return campaign.read_json(directory / "state.json")


def output_script(directory, stop=False):
    return ("import json; from pathlib import Path; "
            f"print(json.dumps({SUMMARY!r}), flush=True); "
            + (f"Path({str(directory / 'stop.request')!r}).touch()" if stop else ""))


def test_supervisor_restarts_finished_worker_and_counts_final_output(directory, monkeypatch):
    state = run_supervisor(directory, monkeypatch, [output_script(directory), output_script(directory, stop=True)])
    assert state["status"] == "stopped_by_request"
    assert state["worker_launches"] == 2
    assert state["completed_cycles"] == 2
    assert state["rpc_requests"] == 6 and state["rpc_successes"] == 4
    assert not campaign.locked(directory)


def test_supervisor_stops_after_repeated_start_failures(directory, monkeypatch):
    state = run_supervisor(directory, monkeypatch, ["raise SystemExit(2)"] * 5)
    assert state["status"] == "repeated_start_failure" and state["worker_launches"] == 5
    assert state["completed_cycles"] == 0


def test_supervisor_stops_before_spawning_when_disk_space_is_low(directory, monkeypatch):
    # No fake workers are available: trying to launch one also fails the test.
    state = run_supervisor(directory, monkeypatch, [], free_bytes=1024**3)
    assert state["status"] == "disk_space_low"
    assert state["worker_launches"] == state["completed_cycles"] == 0
    assert state["backup_count"] == 0


def test_stalled_worker_is_replaced(directory, monkeypatch):
    manifest = campaign.load_manifest(directory)
    manifest["stall_seconds"] = .01
    monkeypatch.setattr(campaign, "load_manifest", lambda _: manifest)
    launches = []
    state = run_supervisor(directory, monkeypatch, ["import time; time.sleep(30)", output_script(directory, stop=True)],
                           launch_states=launches)
    assert state["worker_launches"] == 2 and state["completed_cycles"] == 1
    # Check why replacement started, before its normal exit can overwrite the
    # most recent restart reason. Output/exit scheduling may differ by host.
    assert launches[1]["restart_reason"] == "worker_stalled"
    assert state["status"] == "stopped_by_request"


def test_deadline_stops_active_worker(directory, monkeypatch):
    manifest = campaign.load_manifest(directory)
    manifest["until"] = (utcnow() + timedelta(seconds=.1)).isoformat()
    monkeypatch.setattr(campaign, "load_manifest", lambda _: manifest)
    state = run_supervisor(directory, monkeypatch, ["import time; time.sleep(30)"])
    assert state["status"] == "completed_scheduled_window"
    assert state["worker_pid"] is None


def test_worker_uses_frozen_settings_but_current_credentials(directory, monkeypatch):
    called = []
    async def collect(recorder, once, cycles):
        called.append(True)
        assert recorder.settings.solana_rpc_url == "https://example.com/?key=runtime-key"
        assert recorder.settings.max_watch_tokens == 30
        assert cycles == 90
        return 2
    monkeypatch.setattr(campaign, "load_settings", lambda: Settings(max_watch_tokens=1, solana_rpc_url="https://example.com/?key=runtime-key"))
    monkeypatch.setattr(campaign, "collect", collect)
    monkeypatch.setattr(campaign, "configure_logging", lambda *a: None)
    assert campaign.worker(directory) == 2 and called
