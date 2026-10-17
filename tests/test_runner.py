import pytest

import main
from collectors.http import DataUnavailable
from config.settings import Settings
from data.database import Database
from trading.engine import Engine


@pytest.mark.parametrize("onchain_ok,partial,expected_exit", [(True, False, 0), (False, False, 2), (True, True, 2)])
async def test_collection_cycle_stores_real_source_and_reports_degraded_checks(tmp_path, monkeypatch, quote, onchain_ok, partial, expected_exit):
    snapshot = quote().model_copy(update={"source": "dexscreener"})
    class FakeDex:
        def __init__(self, *args):
            pass
        async def discover_feeds(self, feeds):
            return dict.fromkeys(await self.discover(), "dexscreener-profile"), []
        async def discover(self):
            return [snapshot.token]
        async def snapshots(self, tokens, preferred):
            return {token: snapshot.model_copy(update={"received_at": main.utcnow(), "mint_risk": None}) for token in tokens}
    class FakeSolana:
        def __init__(self, *args, **kwargs):
            self.stats = {}
        async def mint_risk(self, token, pair=None):
            if not onchain_ok:
                raise DataUnavailable("RPC unavailable")
            return snapshot.mint_risk.model_copy(update={"checked_at": main.utcnow(),
                "data_errors": ["Holder endpoint unavailable"] if partial else []})
    monkeypatch.setattr(main, "DexScreener", FakeDex)
    monkeypatch.setattr(main, "Solana", FakeSolana)
    db = Database(tmp_path / "market.sqlite3", "dexscreener")
    try:
        result = await main.collect(Engine(db, Settings(pool_discovery_enabled=False)), once=True)
        assert result == expected_exit
        assert db.counts()["snapshots"] == 1
        assert db.counts()["fills"] == 0
        assert (db.latest(snapshot.token, snapshot.pair).mint_risk is not None) == onchain_ok
    finally:
        db.close()


async def test_bounded_collection_stops_after_requested_cycles(tmp_path, monkeypatch, quote):
    calls = []
    class FakeDex:
        def __init__(self, *args):
            pass
        async def discover_feeds(self, feeds):
            return dict.fromkeys(await self.discover(), "dexscreener-profile"), []
        async def discover(self):
            return ["TOKEN"]
        async def snapshots(self, tokens, preferred):
            calls.append(1)
            return {token: quote().model_copy(update={"source": "dexscreener", "received_at": main.utcnow()}) for token in tokens}
    class FakeSolana:
        def __init__(self, *args, **kwargs):
            self.stats = {}
        async def mint_risk(self, token, pair=None):
            return quote().mint_risk.model_copy(update={"checked_at": main.utcnow()})
    async def no_wait(*args):
        pass
    monkeypatch.setattr(main, "DexScreener", FakeDex)
    monkeypatch.setattr(main, "Solana", FakeSolana)
    monkeypatch.setattr(main.asyncio, "sleep", no_wait)
    db = Database(tmp_path / "bounded.sqlite3", "dexscreener")
    try:
        assert await main.collect(Engine(db, Settings(pool_discovery_enabled=False)), once=False, cycles=3) == 0
        assert len(calls) == 3 and db.counts()["snapshots"] == 3
    finally:
        db.close()


async def test_collection_cycle_failure_has_nonzero_exit(engine, monkeypatch):
    engine.settings.pool_discovery_enabled = False
    class FailedDex:
        def __init__(self, *args):
            pass
        async def discover_feeds(self, feeds):
            return dict.fromkeys(await self.discover(), "dexscreener-profile"), []
        async def discover(self):
            raise DataUnavailable("HTTP 403")
    monkeypatch.setattr(main, "DexScreener", FailedDex)
    assert await main.collect(engine, once=True) == 2
    assert engine.db.counts()["snapshots"] == 0


def test_watchlist_rotates_and_pair_persists(engine, quote):
    first = quote(token="A")
    engine.process(first, first.received_at)
    with engine.db.conn:
        engine.db.discover("B", first.received_at.timestamp(), "demo")
    assert engine.db.watchlist(first.received_at.timestamp(), 1) == ["B"]
    assert engine.db.preferred_pair("A") == "POOL"


def test_database_rejects_incorrect_observation_source(engine, quote):
    wrong = quote().model_copy(update={"source": "dexscreener"})
    with pytest.raises(ValueError, match="source"):
        engine.process(wrong, wrong.received_at)
    assert engine.db.counts()["snapshots"] == 0


async def test_discovery_failure_still_stores_quotes_and_marks_run_degraded(tmp_path, monkeypatch, quote):
    token = quote().token
    class FakeDex:
        def __init__(self, *args):
            pass
        async def discover_feeds(self, feeds):
            return dict.fromkeys(await self.discover(), "dexscreener-profile"), []
        async def discover(self):
            return [token]
        async def snapshots(self, tokens, preferred):
            return {token: quote().model_copy(update={"source": "dexscreener", "received_at": main.utcnow()})}
    class FailedDiscoveryRPC:
        def __init__(self, *args, **kwargs):
            self.stats = {}
        async def rpc(self, *args):
            raise DataUnavailable("Discovery method unavailable")
        async def mint_risk(self, token, pair=None):
            return quote().mint_risk.model_copy(update={"checked_at": main.utcnow()})
    monkeypatch.setattr(main, "DexScreener", FakeDex)
    monkeypatch.setattr(main, "Solana", FailedDiscoveryRPC)
    db = Database(tmp_path / "partial.sqlite3", "dexscreener")
    try:
        assert await main.collect(Engine(db, Settings()), once=True) == 2
        assert db.counts()["snapshots"] == 1
        assert db.conn.execute("SELECT count(*) FROM collection_attempts").fetchone()[0] == 1
        assert db.conn.execute("SELECT count(*) FROM collector_health WHERE kind='scan_error'").fetchone()[0] == 1
    finally:
        db.close()


async def test_missing_pair_attempt_is_persisted_and_priority_moves_on(tmp_path, monkeypatch, quote):
    class FakeDex:
        def __init__(self, *args):
            pass
        async def discover_feeds(self, feeds):
            return dict.fromkeys(await self.discover(), "dexscreener-profile"), []
        async def discover(self):
            return ["A", "B"]
        async def snapshots(self, tokens, preferred):
            return {token: None for token in tokens}
    monkeypatch.setattr(main, "DexScreener", FakeDex)
    db = Database(tmp_path / "unpriced.sqlite3", "dexscreener")
    settings = Settings(pool_discovery_enabled=False, max_watch_tokens=1)
    try:
        assert await main.collect(Engine(db, settings), once=True) == 2
        assert await main.collect(Engine(db, settings), once=True) == 2
        rows = db.conn.execute("SELECT token,status FROM collection_attempts ORDER BY id").fetchall()
        assert [tuple(r) for r in rows] == [("A", "quote_missing"), ("B", "quote_missing")]
        assert db.counts()["snapshots"] == 0
    finally:
        db.close()


async def test_long_observation_gap_is_recorded(tmp_path, monkeypatch, quote):
    import json
    from datetime import timedelta
    earlier = quote().model_copy(update={"source": "dexscreener", "received_at": main.utcnow() - timedelta(seconds=90)})
    class FakeDex:
        def __init__(self, *args):
            pass
        async def discover_feeds(self, feeds):
            return dict.fromkeys(await self.discover(), "dexscreener-profile"), []
        async def discover(self):
            return [earlier.token]
        async def snapshots(self, tokens, preferred):
            return {earlier.token: earlier.model_copy(update={"received_at": main.utcnow()})}
    class FakeSolana:
        def __init__(self, *args, **kwargs):
            self.stats = {}
        async def mint_risk(self, token, pair=None):
            return quote().mint_risk.model_copy(update={"checked_at": main.utcnow()})
    monkeypatch.setattr(main, "DexScreener", FakeDex)
    monkeypatch.setattr(main, "Solana", FakeSolana)
    db = Database(tmp_path / "gap.sqlite3", "dexscreener")
    try:
        engine = Engine(db, Settings(pool_discovery_enabled=False))
        engine.process(earlier, earlier.received_at)
        assert await main.collect(engine, once=True) == 0
        gap = json.loads(db.conn.execute("SELECT details FROM collector_health WHERE kind='quote_gap'").fetchone()[0])
        assert gap["token"] == earlier.token and gap["seconds"] >= 90
    finally:
        db.close()


async def test_one_failed_candidate_list_keeps_others_and_marks_run_degraded(engine, monkeypatch):
    engine.settings.pool_discovery_enabled = False
    engine.settings.discovery_feeds = ["token-profiles", "token-boosts"]
    class PartialDex:
        def __init__(self, *args):
            pass
        async def discover_feeds(self, feeds):
            assert feeds == ["token-profiles", "token-boosts"]
            return {"BOOSTED": "dexscreener-boost"}, ["token-profiles"]
        async def snapshots(self, tokens, preferred):
            return {token: None for token in tokens}
    monkeypatch.setattr(main, "DexScreener", PartialDex)
    assert await main.collect(engine, once=True) == 2
    assert engine.db.conn.execute("SELECT source FROM tokens WHERE token='BOOSTED'").fetchone()[0] == "dexscreener-boost"
