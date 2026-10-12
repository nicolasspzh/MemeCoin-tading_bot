from decimal import Decimal as D

import pytest

from config.settings import Settings
from data.models import Wallet
from trading.paper_wallet import CannotFill, allocate_profit, buy, equity, mark, sell


@pytest.mark.parametrize("before,profit,cash,reserve,owner", [
    ("50", "10", "58", "2", "0"),
    ("100", "10", "106", "2", "2"),
    ("99", "10", "105.25", "2", "1.75"),
    ("99", "1.25", "100", ".25", "0"),
    ("50", "-10", "40", "0", "0"),
])
def test_profit_distribution(before, profit, cash, reserve, owner):
    wallet = Wallet(cash=D(before) + D(profit))
    allocate_profit(wallet, D(profit), D(before))
    assert wallet.cash == D(cash)
    assert wallet.news_reserve == D(reserve)
    assert wallet.owner_profit == D(owner)
    assert wallet.cash + wallet.news_reserve + wallet.owner_profit == D(before) + D(profit)


def test_round_trip_accounts_for_both_fees_and_slippage(quote):
    wallet, settings = Wallet(), Settings()
    start = quote()
    entry = buy(wallet, start, 1, start.received_at, settings)
    assert entry.cash_flow == D("-2.50")
    assert entry.price == D("1.01")
    assert entry.quantity * entry.price + entry.fee == -entry.cash_flow
    end = quote(20)
    exit_fill = sell(wallet, end, 2, end.received_at, settings)
    assert exit_fill.price == D(".99")
    assert exit_fill.realized_pnl < 0
    assert wallet.cash == D(50) + exit_fill.realized_pnl
    assert wallet.news_reserve == wallet.owner_profit == 0
    assert not wallet.positions


def test_profit_conservation_with_default_execution_costs(quote):
    wallet, settings = Wallet(), Settings()
    start, end = quote(), quote(30, price_usd=D("1.5"))
    buy(wallet, start, 1, start.received_at, settings)
    result = sell(wallet, end, 2, end.received_at, settings)
    assert result.realized_pnl > 0
    assert wallet.cash + wallet.news_reserve + wallet.owner_profit == 50 + result.realized_pnl


def test_low_cash_with_open_positions_is_not_dead(quote):
    wallet, settings = Wallet(), Settings()
    start = quote()
    buy(wallet, start, 1, start.received_at, settings)
    wallet.cash = D("4")
    mark(wallet, start, settings)
    assert equity(wallet, settings) > 5
    assert not wallet.dead


def test_dead_is_latched_and_rejects_entries(quote):
    wallet, settings, snapshot = Wallet(cash=D("4.99")), Settings(), quote()
    mark(wallet, snapshot, settings)
    assert wallet.dead
    with pytest.raises(CannotFill, match="wallet_dead"):
        buy(wallet, snapshot, 1, snapshot.received_at, settings)


def test_position_cap_and_illiquid_exit(quote):
    settings = Settings(max_positions=1)
    wallet, start = Wallet(), quote()
    buy(wallet, start, 1, start.received_at, settings)
    other = quote(token="OTHER")
    with pytest.raises(CannotFill, match="position_limit"):
        buy(wallet, other, 2, other.received_at, settings)
    no_pool = quote(20, liquidity_usd=D("0"))
    cash_before = wallet.cash
    with pytest.raises(CannotFill, match="unpriced_or_illiquid"):
        sell(wallet, no_pool, 3, no_pool.received_at, settings)
    assert wallet.cash == cash_before and "TOKEN" in wallet.positions
