from datetime import datetime
from decimal import Decimal

from config.settings import Settings
from data.models import Decision, Snapshot, Wallet
from trading.risk import risk_reasons


def decide(snapshot: Snapshot, previous: Snapshot | None, wallet: Wallet,
           now: datetime, settings: Settings) -> Decision:
    position = wallet.positions.get(snapshot.token)
    if position:
        if snapshot.pair != position.pair:
            return Decision(action="HOLD", reasons=["pair_mismatch"])
        if snapshot.price_usd is None or not 0 <= (now - snapshot.received_at).total_seconds() <= settings.max_quote_age_seconds:
            return Decision(action="HOLD", reasons=["no_fresh_exit_quote"])
        reasons = risk_reasons(snapshot, now, settings, entry=False)
        price = snapshot.price_usd
        if price <= position.entry_price * (1 - settings.stop_loss_fraction):
            reasons.append("stop_loss")
        if price >= position.entry_price * (1 + settings.take_profit_fraction):
            reasons.append("take_profit")
        if price <= position.peak_price * (1 - settings.trailing_stop_fraction):
            reasons.append("trailing_stop")
        if (now - position.opened_at).total_seconds() >= settings.max_position_seconds:
            reasons.append("time_stop")
        if snapshot.buys_5m is not None and snapshot.sells_5m is not None and snapshot.sells_5m > snapshot.buys_5m:
            reasons.append("sell_pressure")
        if previous and previous.liquidity_usd and snapshot.liquidity_usd is not None and snapshot.liquidity_usd < previous.liquidity_usd * Decimal("0.65"):
            reasons.append("liquidity_drop")
        if wallet.dead:
            reasons.append("wallet_dead")
        return Decision(action="SELL" if reasons else "HOLD", reasons=reasons or ["position_healthy"])
    if wallet.dead:
        return Decision(action="SKIP", reasons=["wallet_dead"])
    reasons = risk_reasons(snapshot, now, settings)
    if reasons:
        return Decision(action="SKIP", reasons=reasons)
    if previous is None or previous.price_usd is None:
        return Decision(action="SKIP", reasons=["need_price_history"])
    elapsed = (snapshot.received_at - previous.received_at).total_seconds()
    if previous.pair != snapshot.pair or not 10 <= elapsed <= settings.max_quote_age_seconds:
        return Decision(action="SKIP", reasons=["insufficient_recent_history"])
    momentum = snapshot.price_usd / previous.price_usd - 1
    if momentum < settings.min_momentum_fraction:
        reasons.append("weak_price_momentum")
    if snapshot.buys_5m < 10 or snapshot.buys_5m < 2 * max(1, snapshot.sells_5m):
        reasons.append("weak_buy_pressure")
    return Decision(action="SKIP" if reasons else "BUY", reasons=reasons or ["price_and_buy_momentum"])
