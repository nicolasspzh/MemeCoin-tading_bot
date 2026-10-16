"""Shared paper/replay execution assumptions; never submits transactions."""
import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal as D

from pydantic import BaseModel, ConfigDict, Field

from config.settings import Settings
from data.models import Fill, Snapshot, Wallet
from trading.paper_wallet import CannotFill, buy, equity, sell
from trading.risk import pool_fee_bps, risk_reasons, trade_liquidity_usd


class Execution(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    latency_seconds: float = Field(default=1, ge=0)
    order_ttl_seconds: float = Field(default=120, gt=0)
    priority_fee_usd: D = Field(default=D("0.005"), ge=0)
    failure_probability: float = Field(default=0.02, ge=0, le=1)
    max_adverse_move_bps: D = Field(default=D("300"), ge=0, le=10000)
    seed: int = 7

    @classmethod
    def from_settings(cls, settings: Settings):
        return cls(**{name: getattr(settings, "paper_" + name) for name in cls.model_fields})


def valuation_settings(settings: Settings, execution: Execution) -> Settings:
    return settings.model_copy(update={"fixed_fee_usd": settings.fixed_fee_usd + execution.priority_fee_usd})


def failure_draw(order: dict, execution: Execution) -> D:
    # Stable across restarts, rollback and changes in unrelated processing order.
    key = f'{execution.seed}:{order["id"]}:{order["token"]}:{order["signal_at"]}'
    return D(int.from_bytes(hashlib.sha256(key.encode()).digest(), "big")) / D(2**256)


def execution_blockers(snapshot: Snapshot, now: datetime, settings: Settings, side: str) -> list[str]:
    reasons = risk_reasons(snapshot, now, settings, entry=side == "BUY")
    if side == "BUY":
        return reasons
    # Concentration, LP/creator balances and falling liquidity can cause an exit.
    # They do not prove that a swap is mechanically impossible. Unknown or unsafe
    # token/pool mechanics do, so such an exit remains unfilled.
    mechanics = {"stale_or_future_quote", "missing_price", "missing_onchain_checks",
        "stale_or_future_onchain_checks", "unsupported_token_program", "incomplete_onchain_checks",
        "freeze_authority_active_or_unknown", "token2022_extensions_unverified_or_unsafe",
        "missing_verified_holder_risk", "holder_risk_token_or_pool_mismatch", "unverified_pool_and_holders",
        "pool_fee_above_limit", "unknown_pool_fees"}
    risk = snapshot.mint_risk
    extra = set(risk.extension_reasons) if risk else set()
    if risk and risk.holder_risk:
        extra.update(risk.holder_risk.reasons)
    return [r for r in reasons if r in mechanics or r in extra]


@dataclass
class Attempt:
    wallet: Wallet
    status: str
    reason: str
    fill: Fill | None = None
    failed_fee: D = D(0)
    impact_bps: D = D(0)


def attempt(wallet: Wallet, order: dict, snapshot: Snapshot, sid: int, now: datetime,
            settings: Settings, execution: Execution, draw: D) -> Attempt:
    candidate = wallet.model_copy(deep=True)
    side = order["action"]
    notional = (D(order["budget_usd"]) if side == "BUY" else
                candidate.positions[snapshot.token].quantity * (snapshot.price_usd or 0)
                if snapshot.token in candidate.positions else D(0))
    liquidity = trade_liquidity_usd(snapshot)
    impact = 2 * notional / liquidity * 10000 if liquidity else D(0)
    impact = min(impact, (D(10000) - settings.slippage_bps) / 2)
    # The measured pool fee replaces the fixed assumption. An unknown fee is priced
    # at the limit; such a fill is rejected below by its risk blockers anyway.
    fee = pool_fee_bps(snapshot, settings)
    fill_settings = valuation_settings(settings, execution).model_copy(
        update={"slippage_bps": settings.slippage_bps + impact,
                "fee_bps": settings.max_pool_fee_bps if fee is None else fee})
    try:
        if side == "SELL" and snapshot.token not in candidate.positions:
            raise CannotFill("position_missing")
        # Local preflight does not charge transaction fees. The copied wallet
        # ensures a rejected or failed attempt cannot partially book a fill.
        fill = (buy(candidate, snapshot, sid, now, fill_settings, budget_usd=D(order["budget_usd"]))
                if side == "BUY" else sell(candidate, snapshot, sid, now, fill_settings))
        blockers = execution_blockers(snapshot, now, settings, side)
        if blockers:
            raise CannotFill("execution_risk:" + ",".join(blockers))
    except CannotFill as exc:
        return Attempt(wallet, "rejected", str(exc))
    signal_price = D(order["signal_price_usd"])
    adverse = ((snapshot.price_usd / signal_price - 1) if side == "BUY"
               else (1 - snapshot.price_usd / signal_price)) * 10000
    failure = ("price_moved_beyond_limit" if adverse > execution.max_adverse_move_bps else
               "simulated_transaction_failure" if draw < D(str(execution.failure_probability)) else None)
    if failure:
        failed = wallet.model_copy(deep=True)
        cost = min(failed.cash, fill_settings.fixed_fee_usd)
        failed.cash -= cost
        failed.realized_pnl -= cost
        if side == "SELL":
            failed.positions[snapshot.token].failed_exit_fees += cost
        if equity(failed, valuation_settings(settings, execution)) < 5:
            failed.dead = True
        return Attempt(failed, "failed", failure, failed_fee=cost, impact_bps=impact)
    fill.signal_at = datetime.fromisoformat(order["signal_at"])
    fill.order_id = order["id"]
    fill.signal_snapshot_id = order["signal_snapshot_id"]
    fill.impact_bps = impact
    fill.priority_fee_usd = execution.priority_fee_usd
    if equity(candidate, valuation_settings(settings, execution)) < 5:
        candidate.dead = True
    return Attempt(candidate, "filled", "executed_at_later_quote", fill=fill, impact_bps=impact)


def book_value(wallet: Wallet) -> D:
    return (wallet.cash + wallet.news_reserve + wallet.owner_profit
            + sum((p.entry_cost for p in wallet.positions.values()), D(0)))


def ledger_entry(before: Wallet, after: Wallet, order: dict, at: datetime, fee=D(0)) -> dict:
    difference = book_value(after) - book_value(before) - (after.realized_pnl - before.realized_pnl)
    if abs(difference) > D("1e-24"):
        raise ValueError("Paper ledger does not balance")
    return {"order_id": order["id"], "status": order["status"], "at": at.isoformat(),
            "cash_delta": str(after.cash - before.cash),
            "reserve_delta": str(after.news_reserve - before.news_reserve),
            "owner_delta": str(after.owner_profit - before.owner_profit),
            "position_cost_delta": str(sum((p.entry_cost for p in after.positions.values()), D(0))
                                      - sum((p.entry_cost for p in before.positions.values()), D(0))),
            "realized_pnl_delta": str(after.realized_pnl - before.realized_pnl),
            "fee_usd": str(fee), "balance_error": str(difference)}
