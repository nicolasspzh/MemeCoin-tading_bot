"""Run: python main.py demo | collect [--once] | status [--source demo]."""
import argparse
import asyncio
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import sys
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path

import aiohttp
from pydantic import ValidationError

from collectors.demo import demo_snapshots
from collectors.dexscreener import DexScreener
from collectors.http import DataUnavailable, JsonClient
from collectors.solana import Solana
from collectors.pools import PoolDiscovery
from collectors.schedule import ObservationSchedule, RpcBudget
from config.settings import load_settings
from data.database import Database
from data.models import Snapshot, utcnow
from trading.engine import Engine

log = logging.getLogger("memecoin")


@contextmanager
def single_writer(path: Path):
    """Avoid accidentally running two collectors against the same wallet."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with Path(str(path) + ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("A process already uses this database") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


async def collect(engine: Engine, once: bool, cycles: int | None = None) -> int:
    settings, db = engine.settings, engine.db
    schedule, budget = None, None
    if settings.observation_cohorts:
        if not getattr(engine, 'observation_only', False):
            raise ValueError('Finite cohort collection requires the observation-only recorder')
        schedule = ObservationSchedule(db, settings, getattr(engine, 'feature_until', None))
        budget = RpcBudget(db, settings.rpc_daily_request_limit, settings.rpc_total_request_limit)
    timeout = aiohttp.ClientTimeout(total=20)
    last_discovery = float("-inf")
    completed_cycles, degraded_seen = 0, False
    async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
        http = JsonClient(session)
        dex = DexScreener(http, settings.dex_base_url)
        options = {'budget': budget, 'cache_partial': True} if schedule else {}
        solana = Solana(http, settings.solana_rpc_url, settings.solana_rpc_fallback_urls,
                        cache_seconds=settings.rpc_cache_seconds, **options)
        discovery = PoolDiscovery(db, solana, settings) if settings.pool_discovery_enabled else None
        async with discovery if discovery is not None else nullcontext():
            while True:
                started = time.monotonic()
                engine.tick()
                successes, failures, risk_failures = 0, 0, 0
                if started - last_discovery >= 60:
                    try:
                        discovered = await dex.discover()
                        with db.conn:
                            for token in discovered:
                                db.discover(token, utcnow().timestamp(), "dexscreener-profile")
                        last_discovery = started
                        log.info("Discovery returned %d candidate profiles", len(discovered))
                    except DataUnavailable as exc:
                        failures += 1
                        log.warning("DEX discovery unavailable: %s", exc)
                with db.conn:
                    for token in settings.watch_tokens:
                        db.discover(token, utcnow().timestamp(), "watchlist")
                wallet = db.load_wallet()
                pending_pairs = {o["token"]: o["pair"] for o in db.pending_orders()}
                candidates = (schedule.select(utcnow().timestamp()) if schedule else
                              db.watchlist(utcnow().timestamp(), settings.max_watch_tokens))
                tokens = list(dict.fromkeys([*wallet.positions, *pending_pairs, *settings.watch_tokens, *candidates]))
                # Positions have priority even when the watch budget is full.
                limit = max(settings.max_watch_tokens, len(set(wallet.positions) | set(pending_pairs)))
                deferred = max(len(tokens), db.recent_token_count(utcnow().timestamp())) - limit
                if deferred > 0:
                    log.warning("Watch capacity reached: at least %d tokens deferred this cycle", deferred)
                selected = tokens[:limit]
                preferred_pairs = {token: wallet.positions[token].pair if token in wallet.positions
                                   else pending_pairs.get(token) or (schedule.preferred_pair(token) if schedule
                                        else db.preferred_pair(token)) for token in selected}
                try:
                    quotes = await dex.snapshots(selected, preferred_pairs) if selected else {}
                except (DataUnavailable, ValidationError, TypeError, KeyError, AttributeError):
                    quotes = {}
                    failures += 1
                    with db.conn:
                        db.record_health("dexscreener", utcnow().timestamp(), "batch_error", "Quote batch unavailable")
                with db.conn:
                    if deferred > 0:
                        db.record_health("scheduler", utcnow().timestamp(), "capacity_deferred", str(deferred))
                for token in selected:
                    try:
                        preferred = preferred_pairs[token]
                        snapshot = quotes.get(token)
                        # The batch endpoint can omit the pinned pool. Recover
                        # from its token-pairs endpoint without switching pools.
                        if schedule and preferred and (snapshot is None or snapshot.price_usd is None):
                            try:
                                recovered = await dex.snapshot(token, preferred)
                                if recovered is not None and recovered.price_usd is not None:
                                    snapshot = recovered
                            except (DataUnavailable, ValidationError, TypeError, KeyError, AttributeError):
                                pass  # Preserve an explicit missing/unpriced observation below.
                        with db.conn:
                            db.record_attempt(token, utcnow().timestamp(),
                                              ("quote_missing" if snapshot is None else
                                               "quote_received" if snapshot.price_usd is not None else "quote_received_unpriced"), preferred)
                        if snapshot is None:
                            log.warning("No DEX pair quote for token=%s", token)
                            failures += 1
                            if preferred:
                                missing = Snapshot(token=token, pair=preferred, source="dexscreener",
                                                   received_at=utcnow(), raw={"missing_pair": True})
                                engine.process(schedule.decorate(missing) if schedule else missing)
                            continue
                        if schedule:
                            snapshot = schedule.decorate(snapshot)
                        if snapshot.price_usd is None:
                            failures += 1
                            engine.process(snapshot)
                            continue  # No useful entry quote: avoid wasted risk RPCs.
                        previous_quote = db.last_quote_at(token, snapshot.pair)
                        if previous_quote is not None:
                            gap = snapshot.received_at.timestamp() - previous_quote
                            if gap > settings.poll_seconds * 1.5:
                                with db.conn:
                                    db.record_health("scheduler", snapshot.received_at.timestamp(), "quote_gap",
                                        json.dumps({"token": token, "pair": snapshot.pair, "seconds": gap}))
                        try:
                            snapshot.mint_risk = await solana.mint_risk(token, snapshot.pair)
                            if snapshot.mint_risk.data_errors:
                                risk_failures += 1
                                log.warning("Partial on-chain checks token=%s errors=%s; entry blocked",
                                            token, ",".join(snapshot.mint_risk.data_errors))
                        except (DataUnavailable, ValidationError, TypeError, KeyError, AttributeError) as exc:
                            risk_failures += 1
                            reason = str(exc) if isinstance(exc, DataUnavailable) else type(exc).__name__
                            log.warning("On-chain checks unavailable for token=%s reason=%s; entry blocked", token, reason)
                        engine.process(snapshot)
                        successes += 1
                    except (DataUnavailable, ValidationError, TypeError, KeyError, AttributeError) as exc:
                        failures += 1
                        # Avoid logging response bodies or URLs containing API keys.
                        log.warning("Observation failed token=%s error_type=%s", token, type(exc).__name__)
                completed_cycles += 1
                engine.tick()
                discovery_status = discovery.status() if discovery else {"enabled": False}
                degraded_seen |= successes == 0 or failures > 0 or risk_failures > 0 or bool(discovery and discovery.errors)
                elapsed = time.monotonic() - started
                with db.conn:
                    db.record_health("collector", utcnow().timestamp(), "cycle",
                        json.dumps({"cycle": completed_cycles, "elapsed_seconds": round(elapsed, 3),
                                    "quotes": successes, "errors": failures, "risk_errors": risk_failures,
                                    "deferred": max(0, deferred)}))
                summary = {**engine.summary(), "cycle": completed_cycles, "cycle_quotes": successes,
                           "cycle_errors": failures, "cycle_onchain_errors": risk_failures,
                           "rpc_totals": dict(solana.stats), "pool_discovery": discovery_status,
                           "cycle_elapsed_seconds": round(elapsed, 3), "cycle_deferred": max(0, deferred)}
                if schedule:
                    summary['observation_schedule'] = schedule.status(utcnow().timestamp())
                    summary['rpc_request_budget'] = budget.status()
                print(json.dumps(summary, indent=2), flush=True)
                if once or (cycles is not None and completed_cycles >= cycles):
                    return 2 if degraded_seen else 0
                if not tokens:
                    log.warning("No candidates yet; add WATCH_TOKENS to seed collection")
                await asyncio.sleep(max(0, settings.poll_seconds - (time.monotonic() - started)))


def main() -> int:
    parser = argparse.ArgumentParser(description="Solana collector and paper trading only")
    parser.add_argument("command", choices=["demo", "collect", "status"])
    parser.add_argument("--db", type=Path, help="SQLite file; demo uses runtime/demo.sqlite3 by default")
    parser.add_argument("--once", action="store_true", help="One collection cycle with a meaningful exit status")
    parser.add_argument("--cycles", type=int, help="Stop after this many collection cycles")
    parser.add_argument("--source", choices=["demo", "dexscreener"], default="dexscreener", help="Source for status")
    parser.add_argument("--log-file", type=Path, help="Optional rotating log file (5 MB, 3 backups)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)sZ %(levelname)s %(message)s")
    logging.Formatter.converter = time.gmtime
    try:
        if args.cycles is not None and (args.cycles < 1 or args.once):
            raise ValueError("--cycles must be positive and cannot be combined with --once")
        if args.log_file:
            args.log_file.parent.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(args.log_file, maxBytes=5_000_000, backupCount=3)
            handler.setFormatter(logging.Formatter("%(asctime)sZ %(levelname)s %(message)s"))
            logging.getLogger().addHandler(handler)
        settings = load_settings()
        source = "demo" if args.command == "demo" else args.source if args.command == "status" else "dexscreener"
        path = args.db or (Path("runtime/demo.sqlite3") if source == "demo" else settings.db_path)
        if args.command == "status" and not path.exists():
            raise ValueError("Database does not exist; run demo or collect first")
        with single_writer(path):
            db = Database(path, source)
            try:
                if args.command == "status":
                    print(json.dumps({**Engine.stored_summary(db, settings), "collection": db.collection_status()}, indent=2))
                    return 0
                engine = Engine(db, settings)
                if args.command == "demo":
                    for snapshot in demo_snapshots():
                        engine.process(snapshot, snapshot.received_at)
                    print(json.dumps({"data": "SYNTHETIC_DEMO", **engine.summary()}, indent=2))
                    return 0
                return asyncio.run(collect(engine, args.once, args.cycles))
            finally:
                db.close()
    except KeyboardInterrupt:
        log.info("Stopped; committed state remains in SQLite")
        return 130
    except (ValueError, OSError) as exc:
        # Pydantic errors can include endpoint input. Only expose field names.
        if isinstance(exc, ValidationError):
            log.error("Invalid settings fields: %s", [e["loc"] for e in exc.errors()])
        else:
            log.error("%s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
