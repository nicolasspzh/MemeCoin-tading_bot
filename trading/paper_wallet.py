"""Decimal ledger with persisted positions. All fills are simulated."""
from datetime import datetime
from decimal import Decimal

from config.settings import Settings
from data.models import Fill, Position, Snapshot, Wallet
from trading.risk import pool_fee_bps, trade_liquidity_usd

D = Decimal


class CannotFill(ValueError):
    pass


def estimated_proceeds(position: Position, price: Decimal, settings: Settings) -> Decimal:
    gross = position.quantity * price * (1 - settings.slippage_bps / 10000)
    fee_bps = settings.fee_bps if position.exit_fee_bps is None else position.exit_fee_bps
    return max(D(0), gross * (1 - fee_bps / 10000) - settings.fixed_fee_usd)


def equity(wallet: Wallet, settings: Settings) -> Decimal:
    """Cash plus estimated liquidation value, excluding reserve/owner accounts."""
    return wallet.cash + sum((estimated_proceeds(p, p.last_price, settings)
                              for p in wallet.positions.values()), D(0))


def mark(wallet: Wallet, snapshot: Snapshot, settings: Settings):
    p = wallet.positions.get(snapshot.token)
    if p and p.pair == snapshot.pair and snapshot.price_usd is not None:
        p.last_price = snapshot.price_usd
        p.peak_price = max(p.peak_price, snapshot.price_usd)
        fee = pool_fee_bps(snapshot, settings)
        if fee is not None:
            p.exit_fee_bps = fee  # PumpSwap fees change with market cap
    # DEAD is latched. Open positions may still exit, but no further entries.
    if equity(wallet, settings) < 5:
        wallet.dead = True


def allocate_profit(wallet: Wallet, profit: Decimal, pre_profit_capital: Decimal):
    """Marginal split: fill capital to $100 at 80/20, then use 60/20/20.

    Profit must already be in cash. Losses never draw on reserve or owner profit.
    """
    if profit <= 0:
        return
    below = min(profit, max(D(0), (D(100) - pre_profit_capital) / D("0.8")))
    above = profit - below
    news = profit * D("0.2")
    owner = above * D("0.2")
    # Other positions can tie up capital. Only distribute cash actually available.
    # Newly realized positive profit is always liquid, so this is an invariant.
    if news + owner > wallet.cash:
        raise ValueError("Profit allocation exceeds cash")
    wallet.cash -= news + owner
    wallet.news_reserve += news
    wallet.owner_profit += owner


def _validate_quote(snapshot: Snapshot, now: datetime, settings: Settings):
    if not 0 <= (now - snapshot.received_at).total_seconds() <= settings.max_quote_age_seconds:
        raise CannotFill("stale_or_future_quote")
    if snapshot.price_usd is None or not trade_liquidity_usd(snapshot):
        raise CannotFill("unpriced_or_illiquid")


def buy(wallet: Wallet, snapshot: Snapshot, sid: int, now: datetime, settings: Settings,
        *, budget_usd: Decimal | None = None) -> Fill:
    _validate_quote(snapshot, now, settings)
    if wallet.dead or equity(wallet, settings) < 5:
        raise CannotFill("wallet_dead")
    if snapshot.token in wallet.positions or len(wallet.positions) >= settings.max_positions:
        raise CannotFill("position_limit")
    budget = (min(wallet.cash, equity(wallet, settings) * settings.position_fraction)
              if budget_usd is None else budget_usd)
    if not budget.is_finite() or budget > wallet.cash:
        raise CannotFill("insufficient_cash")
    if budget <= settings.fixed_fee_usd:
        raise CannotFill("insufficient_cash")
    if budget > trade_liquidity_usd(snapshot) * settings.max_pool_fraction:
        raise CannotFill("excessive_pool_participation")
    notional = (budget - settings.fixed_fee_usd) / (1 + settings.fee_bps / 10000)
    price = snapshot.price_usd * (1 + settings.slippage_bps / 10000)
    quantity = notional / price
    fee = budget - notional
    wallet.cash -= budget
    wallet.positions[snapshot.token] = Position(
        token=snapshot.token, pair=snapshot.pair, quantity=quantity, entry_cost=budget,
        entry_price=price, opened_at=now, entry_snapshot_id=sid,
        peak_price=snapshot.price_usd, last_price=snapshot.price_usd, exit_fee_bps=settings.fee_bps)
    return Fill(side="BUY", token=snapshot.token, pair=snapshot.pair, snapshot_id=sid,
                quantity=quantity, price=price, fee=fee, cash_flow=-budget,
                signal_at=now, simulated_at=now, entry_snapshot_id=sid)


def sell(wallet: Wallet, snapshot: Snapshot, sid: int, now: datetime, settings: Settings) -> Fill:
    _validate_quote(snapshot, now, settings)
    p = wallet.positions[snapshot.token]
    if p.pair != snapshot.pair:
        raise CannotFill("pair_mismatch")
    if p.quantity * snapshot.price_usd > trade_liquidity_usd(snapshot) * settings.max_pool_fraction:
        raise CannotFill("exit_liquidity_too_low")
    price = snapshot.price_usd * (1 - settings.slippage_bps / 10000)
    gross = p.quantity * price
    fee = gross * settings.fee_bps / 10000 + settings.fixed_fee_usd
    proceeds = gross - fee
    if wallet.cash + proceeds < 0:
        raise CannotFill("insufficient_cash_for_exit_costs")
    pnl = proceeds - p.entry_cost
    # Exclude this trade's newly realized PnL when selecting allocation tranches.
    other_value = sum((estimated_proceeds(v, v.last_price, settings)
                       for key, v in wallet.positions.items() if key != snapshot.token), D(0))
    before = wallet.cash + p.entry_cost + other_value + p.failed_exit_fees
    wallet.cash += proceeds
    del wallet.positions[snapshot.token]
    wallet.realized_pnl += pnl
    net_trade_pnl = pnl - p.failed_exit_fees
    allocate_profit(wallet, net_trade_pnl, before)
    if equity(wallet, settings) < 5:
        wallet.dead = True
    return Fill(side="SELL", token=snapshot.token, pair=snapshot.pair, snapshot_id=sid,
                quantity=p.quantity, price=price, fee=fee, cash_flow=proceeds,
                realized_pnl=pnl, signal_at=now, simulated_at=now,
                entry_snapshot_id=p.entry_snapshot_id,
                net_trade_pnl=net_trade_pnl if p.failed_exit_fees else None)
