import sqlite3
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest

from config.settings import Settings
from data.database import Database
from data.models import Decision
from trading.engine import Engine
from trading.risk import risk_reasons


@pytest.mark.parametrize("field,value,reason", [
    ("price_usd", None, "missing_price"),
    ("liquidity_usd", None, "insufficient_or_unknown_liquidity"),
    ("liquidity_usd", D("100"), "insufficient_or_unknown_liquidity"),
    ("volume_5m_usd", None, "insufficient_or_unknown_volume"),
    ("buys_5m", None, "missing_trade_counts"),
    ("mint_risk", None, "missing_onchain_checks"),
    ("pair_created_at", None, "unknown_pair_age"),
])
def test_missing_and_unsafe_data_blocks_entry(quote, field, value, reason):
    snapshot = quote(**{field: value})
    assert reason in risk_reasons(snapshot, snapshot.received_at, Settings())


@pytest.mark.parametrize("field,value,reason", [
    ("mint_authority", True, "mint_authority_active_or_unknown"),
    ("freeze_authority", None, "freeze_authority_active_or_unknown"),
    ("supported_program", False, "unsupported_token_program"),
    ("top10_account_fraction", D(".8"), "high_top10_account_concentration"),
])
def test_onchain_risk(quote, field, value, reason):
    snapshot = quote()
    snapshot.mint_risk = snapshot.mint_risk.model_copy(update={field: value})
    assert reason in risk_reasons(snapshot, snapshot.received_at, Settings())


def test_buy_hold_exit_restart_and_idempotency(engine, quote):
    initial = quote()
    assert engine.process(initial, initial.received_at).action == "SKIP"
    entry = quote(20, price_usd=D("1.03"))
    assert engine.process(entry, entry.received_at).action == "BUY"
    hold = quote(40, price_usd=D("1.04"))
    assert engine.process(hold, hold.received_at).action == "HOLD"
    path = engine.db.conn.execute("PRAGMA database_list").fetchone()[2]
    restored_db = Database(Path(path), "demo")
    try:
        restored = Engine(restored_db, Settings())
        assert len(restored.db.load_wallet().positions) == 1
        assert restored.process(entry, entry.received_at) is None
        exit_quote = quote(60, price_usd=D("1.4"))
        result = restored.process(exit_quote, exit_quote.received_at)
        assert result.action == "SELL" and "take_profit" in result.reasons
        assert restored.process(exit_quote, exit_quote.received_at) is None
        assert restored.db.counts()["fills"] == 1
        assert len(restored.db.pending_orders()) == 1
        later = quote(80, price_usd=D("1.39"))
        restored.process(later, later.received_at)
        assert restored.process(later, later.received_at) is None
        assert restored.db.counts() == dict(tokens=1, snapshots=5, decisions=5, fills=2)
        assert not restored.db.load_wallet().positions
        assert restored.summary()["accounting"]["balanced"]
    finally:
        restored_db.close()


@pytest.mark.parametrize("changes,reason", [
    ({"price_usd": D(".8")}, "stop_loss"),
    ({"buys_5m": 10, "sells_5m": 50}, "sell_pressure"),
    ({"liquidity_usd": D("12000")}, "liquidity_drop"),
])
def test_exit_signals(engine, quote, changes, reason):
    for snapshot in [quote(), quote(20, price_usd=D("1.03")), quote(40, price_usd=D("1.04"))]:
        engine.process(snapshot, snapshot.received_at)
    exit_quote = quote(60, **changes)
    result = engine.process(exit_quote, exit_quote.received_at)
    assert result.action == "SELL" and reason in result.reasons


def test_unfillable_exit_keeps_position(engine, quote):
    for snapshot in [quote(), quote(20, price_usd=D("1.03")), quote(40, price_usd=D("1.04"))]:
        engine.process(snapshot, snapshot.received_at)
    signal = quote(60, liquidity_usd=D("0"), price_usd=D(".1"))
    assert engine.process(signal, signal.received_at).action == "SELL"
    bad = quote(80, liquidity_usd=D("0"), price_usd=D(".1"))
    result = engine.process(bad, bad.received_at)
    assert result.action == "HOLD"
    assert "unpriced_or_illiquid" in result.reasons
    assert len(engine.db.load_wallet().positions) == 1
    assert engine.db.counts()["fills"] == 1


def test_stale_quote_cannot_fill_or_revalue_wallet(engine, quote):
    for snapshot in [quote(), quote(20, price_usd=D("1.03")), quote(40, price_usd=D("1.04"))]:
        engine.process(snapshot, snapshot.received_at)
    old = quote(60, price_usd=D(".01"))
    result = engine.process(old, old.received_at + timedelta(minutes=10))
    assert result.action == "HOLD"
    assert engine.db.load_wallet().positions["TOKEN"].last_price == D("1.04")


def test_later_labels_do_not_change_past_decisions(engine, quote):
    first = quote(liquidity_usd=D("1"))
    engine.process(first, first.received_at)
    saved = engine.db.conn.execute("SELECT payload FROM decisions WHERE snapshot_id=1").fetchone()[0]
    later = quote(40, price_usd=D("2"))
    engine.process(later, later.received_at)
    row = engine.db.conn.execute("SELECT * FROM outcomes WHERE snapshot_id=1 AND horizon_seconds=30").fetchone()
    assert row["future_snapshot_id"] == 2 and row["delay_seconds"] == 10
    assert engine.db.conn.execute("SELECT payload FROM decisions WHERE snapshot_id=1").fetchone()[0] == saved
    assert Decision.model_validate_json(saved).action == "SKIP"
    still_missing = engine.db.conn.execute("SELECT future_snapshot_id FROM outcomes WHERE snapshot_id=1 AND horizon_seconds=60").fetchone()[0]
    assert still_missing is None


def test_missed_horizon_is_not_fabricated(engine, quote):
    for snapshot in [quote(), quote(100, price_usd=D("2"))]:
        engine.process(snapshot, snapshot.received_at)
    assert engine.db.conn.execute("SELECT future_snapshot_id FROM outcomes WHERE snapshot_id=1 AND horizon_seconds=30").fetchone()[0] is None


def test_sql_failure_rolls_back_quote_decision_and_wallet(engine, quote):
    first = quote()
    engine.process(first, first.received_at)
    before = engine.db.load_wallet().model_dump_json()
    engine.db.conn.execute("CREATE TRIGGER fail_fill BEFORE INSERT ON fills BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    entry = quote(20, price_usd=D("1.03"))
    engine.process(entry, entry.received_at)
    pending = engine.db.pending_orders()
    later = quote(40, price_usd=D("1.04"))
    with pytest.raises(sqlite3.IntegrityError, match="test failure"):
        engine.process(later, later.received_at)
    assert engine.db.load_wallet().model_dump_json() == before
    assert engine.db.counts() == dict(tokens=1, snapshots=2, decisions=2, fills=0)
    assert engine.db.pending_orders() == pending
    assert engine.db.conn.execute("SELECT count(*) FROM paper_ledger").fetchone()[0] == 0
    engine.db.conn.execute("DROP TRIGGER fail_fill")
    engine.process(later, later.received_at)
    assert engine.db.counts()["fills"] == 1
    assert engine.summary()["accounting"]["balanced"]


def test_demo_and_market_data_cannot_share_database(tmp_path):
    path = tmp_path / "mixed.sqlite3"
    Database(path, "demo").close()
    with pytest.raises(ValueError, match="separate databases"):
        Database(path, "dexscreener")


@pytest.mark.parametrize("exit_seconds,peak,exit_price,reason", [
    (80, "1.2", "1.07", "trailing_stop"),
    (1000, "1.04", "1.04", "time_stop"),
])
def test_trailing_and_time_exits(engine, quote, exit_seconds, peak, exit_price, reason):
    for snapshot in [quote(), quote(20, price_usd=D("1.03")), quote(40, price_usd=D("1.04")), quote(60, price_usd=D(peak))]:
        engine.process(snapshot, snapshot.received_at)
    snapshot = quote(exit_seconds, price_usd=D(exit_price))
    result = engine.process(snapshot, snapshot.received_at)
    assert result.action == "SELL" and reason in result.reasons
