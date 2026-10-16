"""Event replay with separate quote, feature-availability and execution clocks.

No queries to outcomes, decisions, fills or the live wallet are made. The initial
wallet is always a fresh $50. Missing history stays missing; no interpolation.
"""
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

from config.settings import Settings
from data.models import Snapshot, Wallet
from trading.execution import Execution, attempt, failure_draw, valuation_settings
from trading.paper_wallet import equity, mark
from trading.risk import trade_liquidity_usd
from trading.strategy import decide


@dataclass(frozen=True)
class Observation:
    id: int
    snapshot: Snapshot

    @property
    def available_at(self) -> datetime:
        risk = self.snapshot.mint_risk
        checks = [self.snapshot.received_at]
        if risk:
            checks.extend(t for t in (risk.checked_at, risk.mint_checked_at, risk.concentration_checked_at,
                                      risk.holder_risk.checked_at if risk.holder_risk else None) if t is not None)
        return max(checks)


def read_observations(path: Path, *, allow_demo: bool = False) -> tuple[list[Observation], dict]:
    """Load a consistent read transaction without changing source data or WAL."""
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("BEGIN")
        source = connection.execute("SELECT value FROM metadata WHERE key='source'").fetchone()
        if not source or source[0] not in ("demo", "dexscreener"):
            raise ValueError("Missing or unsupported dataset source")
        source = source[0]
        if source == "demo" and not allow_demo:
            raise ValueError("Synthetic data requires --allow-demo and is not a market backtest")
        records, fingerprint, keys = [], hashlib.sha256(), set()
        evidence = {}
        has_evidence = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='risk_evidence'").fetchone()
        for row in connection.execute("SELECT id,token,pair,received_at,payload FROM snapshots ORDER BY id"):
            sid, token, pair, received_at, payload = row
            snapshot = Snapshot.model_validate_json(payload)
            holder = snapshot.mint_risk.holder_risk if snapshot.mint_risk else None
            if holder and holder.evidence_sha256:
                digest = holder.evidence_sha256
                if digest not in evidence:
                    proof = (connection.execute("SELECT payload FROM risk_evidence WHERE sha256=?", (digest,)).fetchone()
                             if has_evidence else None)
                    if not proof:
                        raise ValueError(f"Missing risk evidence at row {sid}")
                    decoded = json.loads(proof[0])
                    canonical_proof = json.dumps(decoded, sort_keys=True, separators=(",", ":"))
                    if hashlib.sha256(canonical_proof.encode()).hexdigest() != digest:
                        raise ValueError(f"Invalid risk evidence fingerprint at row {sid}")
                    evidence[digest] = decoded
                holder.evidence_payload = evidence[digest]
            if (snapshot.source != source or snapshot.token != token or snapshot.pair != pair
                    or abs(snapshot.received_at.timestamp() - received_at) > 0.000001):
                raise ValueError(f"Snapshot metadata/payload mismatch at row {sid}")
            key = (token, pair, received_at)
            if key in keys:
                raise ValueError(f"Duplicate observation key at row {sid}")
            keys.add(key)
            canonical = json.dumps(snapshot.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
            fingerprint.update(f"{sid}:{canonical}\n".encode())
            records.append(Observation(sid, snapshot))
        if not records:
            raise ValueError("Dataset contains no observations")
        provenance = {"path": str(path.resolve()), "source": source,
                      "snapshots_sha256": fingerprint.hexdigest(), "rows": len(records)}
        return records, provenance
    finally:
        connection.close()


def quality_profile(records: list[Observation]) -> dict:
    counts, gaps, delays = Counter(), [], []
    groups = defaultdict(list)
    nulls, risk_status = Counter(), Counter()
    for row in records:
        s = row.snapshot
        groups[(s.token, s.pair)].append(s.received_at)
        counts[s.token] += 1
        delays.append((row.available_at - s.received_at).total_seconds())
        for field in ("price_usd", "liquidity_usd", "volume_5m_usd", "buys_5m", "sells_5m", "pair_created_at"):
            if getattr(s, field) is None:
                nulls[field] += 1
        if s.mint_risk is None:
            risk_status["missing"] += 1
        elif not s.mint_risk.supported_program:
            risk_status["unsupported_program"] += 1
        elif s.mint_risk.extension_checks_passed is False:
            risk_status["blocked_extensions"] += 1
        elif s.mint_risk.risk_version == 3 and s.mint_risk.holder_risk is None:
            risk_status["missing_verified_holder_risk"] += 1
        elif s.mint_risk.holder_risk is not None:
            risk_status["holder_analysis_" + s.mint_risk.holder_risk.status] += 1
        elif s.mint_risk.top10_account_fraction is None:
            risk_status["missing_concentration"] += 1
        else:
            risk_status["supported_with_concentration"] += 1
    for times in groups.values():
        ordered = sorted(times)
        gaps.extend((b - a).total_seconds() for a, b in zip(ordered, ordered[1:]))
    begin = min(row.snapshot.received_at for row in records)
    end = max(row.available_at for row in records)
    return {"observations": len(records), "tokens": len(counts), "pairs": len(groups),
            "pairs_with_multiple_quotes": sum(len(times) >= 2 for times in groups.values()),
            "start_utc": begin.isoformat(), "end_utc": end.isoformat(),
            "duration_seconds": (end - begin).total_seconds(),
            "observations_per_token": dict(counts), "missing_fields": dict(nulls),
            "risk_data_status": dict(risk_status),
            "max_gap_seconds": max(gaps, default=None),
            "gaps_over_120_seconds": sum(gap > 120 for gap in gaps),
            "max_feature_availability_delay_seconds": max(delays),
            "duplicate_keys": 0, "invalid_rows": 0}


class Replay:
    def __init__(self, settings: Settings, execution: Execution):
        self.settings, self.execution = settings, execution
        self.wallet = Wallet()
        self.pending = {}
        self.orders, self.fills, self.decisions, self.curve = [], [], [], []
        self.previous, self.quotes = {}, {}
        self.reason_counts = Counter()
        self.successful_fees = D(0)
        self.failed_fees = D(0)
        self.priority_fees = D(0)
        self.slippage_cost = D(0)

    def valuation_settings(self) -> Settings:
        return valuation_settings(self.settings, self.execution)

    def total_equity(self) -> D:
        return equity(self.wallet, self.valuation_settings()) + self.wallet.news_reserve + self.wallet.owner_profit

    def reserved_cash(self) -> D:
        return sum((D(o["reserved_cash_usd"]) for o in self.pending.values()), D(0))

    def _attempt(self, order: dict, row: Observation, now: datetime):
        snapshot = row.snapshot
        outcome = attempt(self.wallet, order, snapshot, row.id, now, self.settings, self.execution,
                          failure_draw(order, self.execution))
        self.wallet = outcome.wallet
        order.update(status=outcome.status, result_reason=outcome.reason, resolved_at=now.isoformat(),
                     failed_fee_usd=str(outcome.failed_fee))
        self.failed_fees += outcome.failed_fee
        self.priority_fees += min(outcome.failed_fee, self.execution.priority_fee_usd)
        fill = outcome.fill
        if fill is None:
            return
        self.successful_fees += fill.fee
        self.priority_fees += min(fill.fee, self.execution.priority_fee_usd)
        adverse_cost = fill.quantity * abs(fill.price - snapshot.price_usd)
        self.slippage_cost += adverse_cost
        self.fills.append({**fill.model_dump(mode="json"), "order_id": order["id"],
                           "signal_snapshot_id": order["signal_snapshot_id"],
                           "quote_received_at": snapshot.received_at.isoformat(),
                           "effective_delay_seconds": (now - fill.signal_at).total_seconds(),
                           "liquidity_usd": str(snapshot.liquidity_usd),
                           "impact_bps": str(outcome.impact_bps), "slippage_cost_usd": str(adverse_cost)})

    def _signal(self, row: Observation, now: datetime, resolved: dict | None = None):
        snapshot = row.snapshot
        key = (snapshot.token, snapshot.pair)
        previous = self.previous.get(key)
        if previous and snapshot.received_at <= previous.received_at:
            return
        self.previous[key] = snapshot
        if resolved:
            action = "HOLD" if snapshot.token in self.wallet.positions else "SKIP"
            reasons = ["paper_order_" + resolved["status"], resolved["result_reason"]]
        elif snapshot.token in self.pending:
            action, reasons = "HOLD", ["pending_order"]
        else:
            decision = decide(snapshot, previous, self.wallet, now, self.settings)
            action, reasons = decision.action, decision.reasons
        budget = D(0)
        if action == "BUY":
            entry_count = len(self.wallet.positions) + sum(o["action"] == "BUY" for o in self.pending.values())
            budget = min(max(D(0), self.wallet.cash - self.reserved_cash()),
                         equity(self.wallet, self.valuation_settings()) * self.settings.position_fraction)
            if entry_count >= self.settings.max_positions:
                action, reasons = "SKIP", ["position_limit_including_pending"]
            elif budget <= self.valuation_settings().fixed_fee_usd:
                action, reasons = "SKIP", ["insufficient_unreserved_cash"]
        elif action == "SELL" and self.wallet.cash - self.reserved_cash() < self.valuation_settings().fixed_fee_usd:
            action, reasons = "HOLD", ["insufficient_unreserved_exit_fee"]
        if action in ("BUY", "SELL"):
            order = {"id": len(self.orders) + 1, "token": snapshot.token, "pair": snapshot.pair,
                     "action": action, "signal_snapshot_id": row.id,
                     "signal_at": now.isoformat(), "signal_price_usd": str(snapshot.price_usd),
                     "eligible_at": (now + timedelta(seconds=self.execution.latency_seconds)).isoformat(),
                     "expires_at": (now + timedelta(seconds=self.execution.order_ttl_seconds)).isoformat(),
                     "budget_usd": str(budget), "status": "pending", "result_reason": None,
                     "reserved_cash_usd": str(budget if action == "BUY" else self.valuation_settings().fixed_fee_usd)}
            self.pending[snapshot.token] = order
            self.orders.append(order)
        self.decisions.append({"snapshot_id": row.id, "signal_at": now.isoformat(),
                               "action": action, "reasons": reasons})
        self.reason_counts.update(reasons)

    def run(self, records: list[Observation]) -> dict:
        if not records:
            raise ValueError("Cannot replay an empty dataset")
        # Quote events precede feature/signal events at the same timestamp. Even
        # zero-latency orders require a strictly later observed quote.
        events = []
        for row in records:
            events.extend([(row.snapshot.received_at, 0, row.id, row), (row.available_at, 1, row.id, row)])
        events.sort(key=lambda event: event[:3])
        for now, kind, _, row in events:
            for token, order in list(self.pending.items()):
                if now > datetime.fromisoformat(order["expires_at"]) or (self.wallet.dead and order["action"] == "BUY"):
                    order.update(status="cancelled" if self.wallet.dead else "expired",
                                 result_reason="wallet_dead" if self.wallet.dead else "no_quote_before_expiry", resolved_at=now.isoformat())
                    del self.pending[token]
            snapshot = row.snapshot
            if kind == 0:
                self.quotes[(snapshot.token, snapshot.pair)] = snapshot
                mark(self.wallet, snapshot, self.valuation_settings())
            else:
                order = self.pending.get(snapshot.token)
                if (order and order["pair"] == snapshot.pair
                        and snapshot.received_at > datetime.fromisoformat(order["signal_at"])
                        and snapshot.received_at >= datetime.fromisoformat(order["eligible_at"])):
                    del self.pending[snapshot.token]
                    self._attempt(order, row, now)
                    self._signal(row, now, resolved=order)
                else:
                    self._signal(row, now)
            point = {"at": now.isoformat(), "total_marked_equity_usd": str(self.total_equity()),
                     "cash_usd": str(self.wallet.cash), "news_reserve_usd": str(self.wallet.news_reserve),
                     "owner_profit_usd": str(self.wallet.owner_profit), "open_positions": len(self.wallet.positions)}
            if self.curve and self.curve[-1]["at"] == point["at"]:
                self.curve[-1] = point
            else:
                self.curve.append(point)
        for order in self.pending.values():
            order.update(status="unfilled_end_of_data", result_reason="no_future_quote", resolved_at=None)
        return self.metrics(records)

    def metrics(self, records: list[Observation]) -> dict:
        closed = [fill for fill in self.fills if fill["side"] == "SELL"]
        pnls = [D(fill.get("net_trade_pnl", fill["realized_pnl"])) for fill in closed]
        gross_profit = sum((p for p in pnls if p > 0), D(0))
        gross_loss = -sum((p for p in pnls if p < 0), D(0))
        peak, drawdown = D(50), D(0)
        for point in self.curve:
            value = D(point["total_marked_equity_usd"])
            peak = max(peak, value)
            drawdown = max(drawdown, (peak - value) / peak)
        end = max(row.available_at for row in records)
        unresolved = []
        for position in self.wallet.positions.values():
            quote = self.quotes.get((position.token, position.pair))
            reasons = []
            if quote is None or quote.price_usd is None:
                reasons.append("missing_terminal_price")
            if quote is None or (end - quote.received_at).total_seconds() > self.settings.max_quote_age_seconds:
                reasons.append("stale_terminal_quote")
            liquidity = trade_liquidity_usd(quote) if quote is not None else None
            if not liquidity or (quote.price_usd is not None
                    and position.quantity * quote.price_usd > liquidity * self.settings.max_pool_fraction):
                reasons.append("insufficient_terminal_liquidity")
            unresolved.append({"token": position.token, "quantity": str(position.quantity),
                               "mark_price_usd": str(position.last_price), "valuation_warnings": reasons})
        return {"starting_capital_usd": "50", "ending_cash_usd": str(self.wallet.cash),
                "trading_equity_mark_usd": str(equity(self.wallet, self.valuation_settings())),
                "total_equity_mark_usd": str(self.total_equity()),
                "marked_return_pct": str((self.total_equity() / 50 - 1) * 100),
                "net_realized_pnl_usd": str(self.wallet.realized_pnl),
                "news_reserve_usd": str(self.wallet.news_reserve), "owner_profit_usd": str(self.wallet.owner_profit),
                "completed_trades": len(closed), "successful_fills": len(self.fills),
                "orders": len(self.orders), "order_status_counts": dict(Counter(o["status"] for o in self.orders)),
                "decision_counts": dict(Counter(d["action"] for d in self.decisions)),
                "decision_reasons": dict(self.reason_counts),
                "win_rate_pct": str(D(sum(p > 0 for p in pnls)) / len(pnls) * 100) if pnls else None,
                "profit_factor_closed_trades": str(gross_profit / gross_loss) if gross_loss else None,
                "successful_fees_usd": str(self.successful_fees), "failed_fees_usd": str(self.failed_fees),
                "priority_fees_included_usd": str(self.priority_fees),
                "slippage_and_impact_usd": str(self.slippage_cost),
                "max_sampled_drawdown_pct": str(drawdown * 100),
                "open_positions": unresolved, "status": "DEAD" if self.wallet.dead else "ALIVE",
                "decision_grade": "DESCRIPTIVE_ONLY" if closed else "NO_COMPLETED_TRADES"}
