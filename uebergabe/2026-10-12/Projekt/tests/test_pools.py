import asyncio
import copy
import json
from pathlib import Path

import pytest

from collectors.http import DataUnavailable
from collectors.pools import FEE_ACCOUNT, PROGRAM, SOURCE, PoolDiscovery, parse_pools
from config.settings import Settings
from data.database import Database


@pytest.fixture
def transaction():
    return json.loads((Path(__file__).parent / "fixtures/raydium_cpmm_initialize.json").read_text())


def test_real_finalized_transaction_decodes_expected_pool(transaction):
    events = parse_pools(transaction, transaction["transaction"]["signatures"][0])
    assert len(events) == 1
    assert events[0]["pool"] == "5GQaopKrfi3WyMap2G4rvqpG9HzeKMQmfDjtMs78htQM"
    assert events[0]["token_0"] == "So11111111111111111111111111111111111111112"
    assert events[0]["token_1"] == "CD8Z8xzZYQtpGhwfG2GmKjsHaFLzNW6qua6fdC8q88or"
    assert events[0]["slot"] == 454159580


def test_failed_or_other_program_transaction_cannot_discover_pool(transaction):
    signature = transaction["transaction"]["signatures"][0]
    transaction["meta"]["err"] = {"InstructionError": [1, "failed"]}
    assert parse_pools(transaction, signature) == []
    transaction["meta"]["err"] = None
    keys = transaction["transaction"]["message"]["accountKeys"]
    keys[keys.index(PROGRAM)] = "11111111111111111111111111111111"
    assert parse_pools(transaction, signature) == []


def test_v0_loaded_accounts_and_inner_initialization(transaction):
    signature = transaction["transaction"]["signatures"][0]
    message = transaction["transaction"]["message"]
    keys = message["accountKeys"]
    instructions = [ix for ix in message["instructions"] if keys[ix["programIdIndex"]] == PROGRAM]
    assert len(instructions) == 1
    message["instructions"] = []
    message["accountKeys"] = keys[:2]
    transaction["meta"]["loadedAddresses"] = {"writable": keys[2:-2], "readonly": keys[-2:]}
    transaction["meta"]["innerInstructions"] = [{"index": 0, "instructions": instructions}]
    assert len(parse_pools(transaction, signature)) == 1


@pytest.mark.parametrize("fault", ["signature", "slot", "fee_account", "negative_index", "truncated"])
def test_bad_initialization_data_rejected(transaction, fault):
    signature = transaction["transaction"]["signatures"][0]
    message = transaction["transaction"]["message"]
    if fault == "signature":
        signature = "wrong"
    elif fault == "slot":
        transaction["slot"] = True
    elif fault == "fee_account":
        message["accountKeys"][message["accountKeys"].index(FEE_ACCOUNT)] = "11111111111111111111111111111111"
    else:
        ix = next(i for i in message["instructions"] if message["accountKeys"][i["programIdIndex"]] == PROGRAM)
        if fault == "negative_index":
            ix["accounts"][0] = -1
        else:
            ix["accounts"] = ix["accounts"][:5]
    with pytest.raises(DataUnavailable):
        parse_pools(transaction, signature)


class FakeRPC:
    def __init__(self, transaction):
        self.transaction = transaction
        self.signature = transaction["transaction"]["signatures"][0]
        self.row = {"signature": self.signature, "slot": transaction["slot"], "blockTime": transaction["blockTime"], "err": None}
        self.pages = [[self.row]]
        self.calls = []
        self.unavailable = False

    async def rpc(self, method, params):
        self.calls.append((method, params))
        if method == "getSignaturesForAddress":
            return self.pages.pop(0) if self.pages else []
        assert method == "getTransaction"
        return None if self.unavailable else self.transaction


async def test_discovery_persists_events_cursors_and_deduplicates_after_restart(tmp_path, transaction):
    path = tmp_path / "discovery.sqlite3"
    db = Database(path, "dexscreener")
    rpc = FakeRPC(transaction)
    discovery = PoolDiscovery(db, rpc, Settings(max_age_seconds=10**10))
    await discovery.poll()
    assert discovery.errors == 0
    assert db.conn.execute("SELECT count(*) FROM pool_events").fetchone()[0] == 1
    assert db.conn.execute("SELECT count(*) FROM tokens").fetchone()[0] == 1
    assert db.preferred_pair("CD8Z8xzZYQtpGhwfG2GmKjsHaFLzNW6qua6fdC8q88or") == "5GQaopKrfi3WyMap2G4rvqpG9HzeKMQmfDjtMs78htQM"
    event = db.conn.execute("SELECT chain_time, discovered_at FROM pool_events").fetchone()
    assert event[1] > event[0]  # local receipt is not backdated to chain time
    db.close()
    db = Database(path, "dexscreener")
    try:
        rpc.pages = [[rpc.row], []]  # even a repeated provider result cannot duplicate a pool
        restarted = PoolDiscovery(db, rpc, Settings())
        await restarted.poll()
        assert db.conn.execute("SELECT count(*) FROM pool_events").fetchone()[0] == 1
        assert sum(m == "getTransaction" for m, _ in rpc.calls) == 1
        assert rpc.calls[-1][1][1]["until"] == rpc.signature
        assert db.conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        db.close()


async def test_missing_transaction_is_retried_after_restart_not_lost(tmp_path, transaction):
    db = Database(tmp_path / "pending.sqlite3", "dexscreener")
    try:
        rpc = FakeRPC(transaction); rpc.unavailable = True
        scanner = PoolDiscovery(db, rpc, Settings())
        await scanner.poll()
        assert scanner.errors == 1 and scanner.status()["pending_transactions"] == 1
        assert db.conn.execute("SELECT attempts FROM chain_transactions").fetchone()[0] == 1
        rpc.unavailable = False
        with db.conn:
            db.conn.execute("UPDATE chain_transactions SET next_attempt=0")
        restarted = PoolDiscovery(db, rpc, Settings())
        await restarted.poll()
        assert restarted.status()["pending_transactions"] == 0
        assert db.conn.execute("SELECT status FROM chain_transactions").fetchone()[0] == "verified_pool"
    finally:
        db.close()


async def test_new_pool_after_saved_cursor_is_discovered_on_next_poll(tmp_path, transaction):
    db = Database(tmp_path / "newpool.sqlite3", "dexscreener")
    try:
        rpc = FakeRPC(transaction)
        scanner = PoolDiscovery(db, rpc, Settings(max_age_seconds=10**10))
        await scanner.poll()
        first_signature = rpc.signature
        fresh = copy.deepcopy(transaction)
        fresh_signature = "1" * 63 + "7"
        fresh_pool = "3RSAGUGNvL4x27ukwRybPE7WUQMiUCWtgYJezLUgpump"
        fresh["transaction"]["signatures"][0] = fresh_signature
        fresh["slot"] += 10
        keys = fresh["transaction"]["message"]["accountKeys"]
        keys[keys.index("5GQaopKrfi3WyMap2G4rvqpG9HzeKMQmfDjtMs78htQM")] = fresh_pool
        rpc.transaction = fresh
        rpc.pages = [[dict(rpc.row, signature=fresh_signature, slot=fresh["slot"])]]
        await scanner.poll()
        assert scanner.errors == 0
        assert db.conn.execute("SELECT count(*) FROM pool_events").fetchone()[0] == 2
        state = json.loads(db.conn.execute("SELECT payload FROM chain_scan_state").fetchone()[0])
        assert state["cursor"] == fresh_signature
        assert rpc.calls[2][1][1]["until"] == first_signature
    finally:
        db.close()


async def test_bounded_pagination_resumes_from_saved_before_and_keeps_newest_head(tmp_path, transaction):
    db = Database(tmp_path / "catchup.sqlite3", "dexscreener")
    try:
        rpc = FakeRPC(transaction)
        signatures = ["1" * 63 + c for c in "23456"]  # 64-byte base58 signatures
        rows = [dict(rpc.row, signature=s, err={"failed": True}) for s in signatures]
        state = {"cursor": rpc.signature, "head": None, "before": None}
        with db.conn:
            db.conn.execute("INSERT INTO chain_scan_state VALUES(?,?)", (SOURCE, json.dumps(state)))
        rpc.pages = [rows[:2], rows[2:4], rows[4:]]
        settings = Settings(discovery_page_size=2, discovery_pages_per_poll=1)
        await PoolDiscovery(db, rpc, settings).poll()
        mid = json.loads(db.conn.execute("SELECT payload FROM chain_scan_state").fetchone()[0])
        assert mid == {"cursor": rpc.signature, "head": signatures[0], "before": signatures[1]}
        await PoolDiscovery(db, rpc, settings).poll()
        await PoolDiscovery(db, rpc, settings).poll()
        final = json.loads(db.conn.execute("SELECT payload FROM chain_scan_state").fetchone()[0])
        assert final == {"cursor": signatures[0], "head": None, "before": None}
        assert rpc.calls[1][1][1]["before"] == signatures[1]
        assert db.conn.execute("SELECT count(*) FROM chain_transactions").fetchone()[0] == 5
    finally:
        db.close()


async def test_discovery_task_shutdown_is_clean_and_recorded(tmp_path, transaction):
    db = Database(tmp_path / "shutdown.sqlite3", "dexscreener")
    try:
        scanner = PoolDiscovery(db, FakeRPC(transaction), Settings())
        async with scanner:
            assert scanner.task and not scanner.task.done()
        assert scanner.task.done()
        kinds = [r[0] for r in db.conn.execute("SELECT kind FROM collector_health ORDER BY id")]
        assert kinds[0] == "started" and kinds[-1] == "stopped" and "bootstrap_boundary" in kinds
    finally:
        db.close()


async def test_existing_queue_can_resolve_during_signature_endpoint_outage(tmp_path, transaction):
    db = Database(tmp_path / "outage.sqlite3", "dexscreener")
    try:
        rpc = FakeRPC(transaction)
        scanner = PoolDiscovery(db, rpc, Settings())
        await scanner.scan()
        original = rpc.rpc
        async def outage(method, params):
            if method == "getSignaturesForAddress":
                raise DataUnavailable("RPC getSignaturesForAddress unavailable")
            return await original(method, params)
        rpc.rpc = outage
        await scanner.poll()
        assert scanner.errors == 1 and scanner.status()["pending_transactions"] == 0
        assert db.conn.execute("SELECT count(*) FROM pool_events").fetchone()[0] == 1
    finally:
        db.close()


async def test_malformed_signature_page_does_not_advance_cursor(tmp_path, transaction):
    db = Database(tmp_path / "badpage.sqlite3", "dexscreener")
    try:
        rpc = FakeRPC(transaction)
        rpc.pages = [[dict(rpc.row, signature="invalid!")]]
        scanner = PoolDiscovery(db, rpc, Settings())
        await scanner.poll()
        assert scanner.errors == 1
        assert db.conn.execute("SELECT count(*) FROM chain_scan_state").fetchone()[0] == 0
        assert db.conn.execute("SELECT count(*) FROM chain_transactions").fetchone()[0] == 0
    finally:
        db.close()


def test_missing_quotes_cannot_starve_other_candidates(engine, quote):
    now = quote().received_at.timestamp()
    with engine.db.conn:
        for token in ("A", "B", "C"):
            engine.db.discover(token, now, "test")
    assert engine.db.watchlist(now, 1) == ["A"]
    with engine.db.conn:
        engine.db.record_attempt("A", now, "quote_missing")
    assert engine.db.watchlist(now, 2) == ["B", "C"]
    assert engine.db.conn.execute("SELECT status FROM collection_attempts").fetchone()[0] == "quote_missing"


def test_missing_observation_does_not_hide_last_valid_quote_time(engine, quote):
    from datetime import timedelta
    first = quote()
    engine.process(first, first.received_at)
    missing = first.model_copy(update={"received_at": first.received_at + timedelta(seconds=20), "price_usd": None})
    engine.process(missing, missing.received_at)
    assert engine.db.last_quote_at(first.token, first.pair) == first.received_at.timestamp()


def test_old_database_receives_additive_tables_without_losing_wallet(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite3"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    old.execute("INSERT INTO metadata VALUES('source','dexscreener')")
    old.commit(); old.close()
    db = Database(path, "dexscreener")
    try:
        assert db.conn.execute("SELECT count(*) FROM pool_events").fetchone()[0] == 0
        assert db.conn.execute("SELECT value FROM metadata WHERE key='source'").fetchone()[0] == "dexscreener"
    finally:
        db.close()
