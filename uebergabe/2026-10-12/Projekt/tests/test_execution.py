import json
from datetime import datetime, timedelta
from decimal import Decimal as D

import pytest

from backtesting.replay import Observation, Replay
from config.settings import Settings
from data.database import Database
from data.models import Wallet
from trading.engine import Engine
from trading.execution import Execution, book_value
from trading.paper_wallet import buy, sell


def process(engine, *quotes):
    return [engine.process(q, q.received_at) for q in quotes]


def orders(engine):
    return [json.loads(r[0]) for r in engine.db.conn.execute('SELECT payload FROM paper_orders ORDER BY id')]


def test_entry_reserves_budget_until_strictly_later_quote(engine, quote):
    process(engine, quote(), quote(20, price_usd=D('1.03')))
    assert engine.db.counts()['fills'] == 0
    assert not engine.db.load_wallet().positions
    summary = engine.summary()
    assert D(summary['cash_usd']) == 50 and D(summary['reserved_cash_usd']) == D('2.5')
    assert D(summary['available_cash_usd']) == D('47.5')
    process(engine, quote(21, pair='OTHER', price_usd=D('1.04')))
    assert engine.db.counts()['fills'] == 0
    process(engine, quote(40, price_usd=D('1.04')))
    fill = json.loads(engine.db.conn.execute('SELECT payload FROM fills').fetchone()[0])
    assert fill['signal_snapshot_id'] == 2 and fill['snapshot_id'] == 4
    assert datetime.fromisoformat(fill['signal_at']) < datetime.fromisoformat(fill['simulated_at'])
    assert D(fill['price']) > D('1.04') and D(fill['cash_flow']) == D('-2.5')
    assert engine.summary()['pending_orders'] == 0


def test_pending_order_survives_restart_with_original_costs(engine, quote, tmp_path):
    process(engine, quote(), quote(20, price_usd=D('1.03')))
    pending = engine.db.pending_orders()[0]
    db = Database(tmp_path / 'test.sqlite3', 'demo')
    try:
        restarted = Engine(db, Settings(fixed_fee_usd=D('1'), paper_failure_probability=1))
        assert restarted.db.pending_orders()[0] == pending
        process(restarted, quote(40, price_usd=D('1.04')))
        fill = json.loads(db.conn.execute('SELECT payload FROM fills').fetchone()[0])
        assert D(fill['fee']) < D('.1')
        assert orders(restarted)[0]['status'] == 'filled'
        assert restarted.summary()['accounting']['balanced']
        assert 'solana_rpc_url' not in json.dumps(orders(restarted))
    finally:
        db.close()


def test_expiry_without_quotes_releases_cash_once(engine, quote):
    process(engine, quote(), quote(20, price_usd=D('1.03')))
    deadline = quote(141).received_at
    engine.tick(deadline)
    engine.tick(deadline)
    summary = engine.summary()
    assert summary['order_status_counts'] == {'expired': 1}
    assert D(summary['reserved_cash_usd']) == 0 and D(summary['cash_usd']) == 50
    assert summary['accounting']['ledger_entries'] == 1 and summary['accounting']['balanced']


def test_failure_charges_only_fixed_priority_fees_and_is_idempotent(engine, quote):
    engine.execution = Execution(failure_probability=1)
    process(engine, quote(), quote(20, price_usd=D('1.03')))
    later = quote(40, price_usd=D('1.04'))
    process(engine, later)
    wallet = engine.db.load_wallet()
    assert wallet.cash == D('49.975') and wallet.realized_pnl == D('-.025')
    assert wallet.news_reserve == wallet.owner_profit == 0 and not wallet.positions
    assert engine.process(later, later.received_at) is None
    assert engine.db.counts()['fills'] == 0
    assert orders(engine)[0]['status'] == 'failed'
    assert engine.summary()['accounting']['balanced']


@pytest.mark.parametrize('failure', ['missing_risk', 'freeze', 'missing_quote', 'low_liquidity'])
def test_changed_data_rejects_pending_buy_without_fee(engine, quote, failure):
    process(engine, quote(), quote(20, price_usd=D('1.03')))
    q = quote(40, price_usd=D('1.04'))
    if failure == 'missing_risk': q.mint_risk = None
    if failure == 'freeze': q.mint_risk.freeze_authority = True
    if failure == 'missing_quote': q.price_usd = None
    if failure == 'low_liquidity': q.liquidity_usd = D('1')
    process(engine, q)
    assert orders(engine)[0]['status'] == 'rejected'
    assert engine.db.load_wallet().cash == 50 and engine.db.counts()['fills'] == 0
    assert engine.summary()['accounting']['balanced']


def test_unsafe_exit_does_not_invent_recovered_money(engine, quote):
    process(engine, quote(), quote(20, price_usd=D('1.03')), quote(40, price_usd=D('1.04')),
            quote(60, price_usd=D('1.4')))
    unsafe = quote(80, price_usd=D('1.39'))
    unsafe.mint_risk.freeze_authority = True
    process(engine, unsafe)
    assert orders(engine)[1]['status'] == 'rejected'
    wallet = engine.db.load_wallet()
    assert wallet.cash == D('47.5') and len(wallet.positions) == 1
    assert wallet.realized_pnl == wallet.news_reserve == 0


def test_pending_buys_count_toward_position_limit(engine, quote):
    engine.settings.max_positions = 1
    process(engine, quote(token='A'), quote(token='B'), quote(20, token='A', price_usd=D('1.03')))
    decision = process(engine, quote(20, token='B', price_usd=D('1.03')))[0]
    assert decision.reasons == ['position_limit_including_pending']
    assert len(engine.db.pending_orders()) == 1


def test_sell_failure_costs_reduce_distributable_profit(engine, quote):
    process(engine, quote(), quote(20, price_usd=D('1.03')), quote(40, price_usd=D('1.04')))
    engine.execution = Execution(failure_probability=1)
    process(engine, quote(60, price_usd=D('1.4')), quote(80, price_usd=D('1.39')))
    wallet = engine.db.load_wallet()
    assert wallet.positions['TOKEN'].failed_exit_fees == D('.025')
    engine.execution = Execution(failure_probability=0)
    process(engine, quote(100, price_usd=D('1.4')), quote(120, price_usd=D('1.39')))
    wallet = engine.db.load_wallet()
    assert not wallet.positions
    assert abs(book_value(wallet) - 50 - wallet.realized_pnl) < D('1e-24')
    assert abs(wallet.news_reserve - wallet.realized_pnl * D('.2')) < D('1e-24')
    assert engine.summary()['accounting']['balanced']
    fill = json.loads(engine.db.conn.execute('SELECT payload FROM fills ORDER BY id DESC LIMIT 1').fetchone()[0])
    assert D(fill['net_trade_pnl']) == D(fill['realized_pnl']) - D('.025')


def test_exit_fee_larger_than_proceeds_is_fully_charged(quote):
    wallet = Wallet()
    q = quote()
    buy(wallet, q, 1, q.received_at, Settings())
    end = quote(20, price_usd=D('.000001'))
    fill = sell(wallet, end, 2, end.received_at, Settings())
    assert fill.cash_flow < 0 and fill.fee > D('.02')
    assert abs(wallet.cash - 50 - wallet.realized_pnl) < D('1e-24')


def test_wallet_ledger_detects_unrecorded_change(engine, quote):
    process(engine, quote(), quote(20, price_usd=D('1.03')), quote(40, price_usd=D('1.04')))
    assert engine.summary()['accounting']['balanced']
    with engine.db.conn:
        wallet = engine.db.load_wallet()
        wallet.cash += D('1')
        engine.db.save_wallet(wallet)
    assert not engine.summary()['accounting']['balanced']
    with pytest.raises(ValueError, match='accounting mismatch'):
        Engine(engine.db, engine.settings)


def test_paper_and_replay_have_same_fills_and_balances(engine, quote):
    snapshots = [quote(), quote(20, price_usd=D('1.03')), quote(40, price_usd=D('1.04')),
                 quote(60, price_usd=D('1.4')), quote(80, price_usd=D('1.39'))]
    process(engine, *snapshots)
    replay = Replay(engine.settings, Execution(failure_probability=0))
    replay.run([Observation(i+1, q) for i, q in enumerate(snapshots)])
    assert engine.db.load_wallet() == replay.wallet
    persisted = [json.loads(r[0]) for r in engine.db.conn.execute('SELECT payload FROM fills ORDER BY id')]
    assert len(persisted) == len(replay.fills) == 2
    for actual, expected in zip(persisted, replay.fills):
        assert all(expected[key] == value for key, value in actual.items())


def test_delayed_risk_cannot_fill_using_pre_signal_quote(engine, quote):
    process(engine, quote())
    signal = quote(20, price_usd=D('1.03'))
    signal.mint_risk.checked_at += timedelta(seconds=10)
    engine.process(signal, signal.mint_risk.checked_at)
    earlier = quote(29, price_usd=D('1.035'))
    earlier.mint_risk.checked_at += timedelta(seconds=2)
    engine.process(earlier, earlier.mint_risk.checked_at)
    assert engine.db.counts()['fills'] == 0
    process(engine, quote(40, price_usd=D('1.04')))
    assert engine.db.counts()['fills'] == 1


def test_dead_cancels_pending_entry_but_keeps_exit_ability(engine, quote):
    process(engine, quote(), quote(20, price_usd=D('1.03')))
    with engine.db.conn:
        wallet = engine.db.load_wallet()
        wallet.dead = True
        engine.db.save_wallet(wallet)
    engine.tick(quote(25).received_at)
    assert orders(engine)[0]['status'] == 'cancelled'
    assert D(engine.summary()['reserved_cash_usd']) == 0


def test_legacy_wallet_is_preserved_when_accounting_is_first_enabled(tmp_path, quote):
    from trading.paper_wallet import buy
    db = Database(tmp_path / 'old.sqlite3', 'demo')
    wallet = Wallet(cash=D('99'), news_reserve=D('3'), owner_profit=D('1'))
    q = quote()
    buy(wallet, q, 1, q.received_at, Settings())
    with db.conn:
        db.save_wallet(wallet)
    try:
        engine = Engine(db, Settings())
        assert db.load_wallet() == wallet
        assert engine.summary()['accounting']['balanced']
        assert engine.summary()['accounting']['ledger_entries'] == 0
        assert engine.summary()['valuation_warnings'][0]['reasons']
    finally:
        db.close()


def test_stale_attempt_before_expiry_is_rejected_without_fee(engine, quote):
    engine.execution = Execution(order_ttl_seconds=1000, failure_probability=0)
    process(engine, quote(), quote(20, price_usd=D('1.03')))
    later = quote(40, price_usd=D('1.04'))
    engine.process(later, quote(200).received_at)
    assert orders(engine)[0]['result_reason'] == 'stale_or_future_quote'
    assert orders(engine)[0]['status'] == 'rejected'
    assert engine.db.load_wallet().cash == 50


def test_zero_latency_still_needs_quote_received_after_signal(engine, quote):
    engine.execution = Execution(latency_seconds=0, failure_probability=0)
    process(engine, quote(), quote(20, price_usd=D('1.03')))
    assert engine.db.counts()['fills'] == 0
    same = quote(20, price_usd=D('1.04'))
    assert engine.process(same, same.received_at) is None
    process(engine, quote(21, price_usd=D('1.04')))
    assert engine.db.counts()['fills'] == 1


def test_risk_arriving_after_expiry_cannot_backdate_fill(engine, quote):
    process(engine, quote(), quote(20, price_usd=D('1.03')))
    later = quote(139, price_usd=D('1.04'))
    later.mint_risk.checked_at = quote(141).received_at
    engine.process(later, later.mint_risk.checked_at)
    assert orders(engine)[0]['status'] == 'expired'
    assert engine.db.counts()['fills'] == 0
