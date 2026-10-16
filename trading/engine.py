import json
import hashlib
import logging
from datetime import datetime, timedelta
from decimal import Decimal as D

from config.settings import Settings
from data.database import Database
from data.models import Decision, Snapshot, Wallet, utcnow
from trading.execution import Execution, attempt, book_value, failure_draw, ledger_entry, valuation_settings
from trading.paper_wallet import equity, mark
from trading.risk import trade_liquidity_usd
from trading.strategy import decide

log = logging.getLogger(__name__)


class Engine:
    def __init__(self, db: Database, settings: Settings):
        self.db, self.settings = db, settings
        self.execution = Execution.from_settings(settings)
        safe_settings = settings.model_dump(mode="json", exclude={"solana_rpc_url", "solana_rpc_fallback_urls", "dex_base_url", "db_path"})
        with db.conn:
            self.run_id = db.conn.execute("INSERT INTO runs(started_at,settings) VALUES(?,?)",
                (utcnow().timestamp(), json.dumps(safe_settings, sort_keys=True))).lastrowid
            db.save_wallet(db.load_wallet())
            db.conn.execute("INSERT OR IGNORE INTO metadata VALUES('paper_accounting_origin',?)",
                            (db.load_wallet().model_dump_json(),))
            if not self.stored_summary(db, settings)["accounting"]["balanced"]:
                raise ValueError("Paper accounting mismatch; inspect ledger before resuming")

    def _finish(self, order, before, after, now, sid=None, fee=D(0)):
        order["resolved_at"] = now.isoformat()
        self.db.save_order(order)
        entry = ledger_entry(before, after, order, now, fee)
        self.db.conn.execute("INSERT INTO paper_ledger(order_id,snapshot_id,payload) VALUES(?,?,?)",
                            (order["id"], sid, json.dumps(entry, sort_keys=True)))

    def _expire(self, wallet, now):
        for order in self.db.pending_orders():
            if now > datetime.fromisoformat(order["expires_at"]) or (wallet.dead and order["action"] == "BUY"):
                order.update(status="expired" if not wallet.dead else "cancelled",
                             result_reason="no_quote_before_expiry" if not wallet.dead else "wallet_dead")
                self._finish(order, wallet, wallet, now)

    def tick(self, now: datetime | None = None):
        """Release expired reservations even during a quote/discovery outage."""
        with self.db.conn:
            self.db.conn.execute("BEGIN IMMEDIATE")
            self._expire(self.db.load_wallet(), now or utcnow())

    def _queue(self, snapshot, sid, now, wallet, decision):
        pending = self.db.pending_orders()
        reserved = sum((D(o["reserved_cash_usd"]) for o in pending), D(0))
        free = max(D(0), wallet.cash - reserved)
        cost = self.settings.fixed_fee_usd + self.execution.priority_fee_usd
        budget = D(0)
        if decision.action == "BUY":
            if len(wallet.positions) + sum(o["action"] == "BUY" for o in pending) >= self.settings.max_positions:
                return Decision(action="SKIP", reasons=["position_limit_including_pending"])
            budget = min(free, equity(wallet, valuation_settings(self.settings, self.execution)) * self.settings.position_fraction)
            if budget <= cost:
                return Decision(action="SKIP", reasons=["insufficient_unreserved_cash"])
        elif free < cost:
            return Decision(action="HOLD", reasons=["insufficient_unreserved_exit_fee"])
        safe = self.settings.model_dump(mode="json", exclude={"solana_rpc_url", "solana_rpc_fallback_urls", "dex_base_url", "db_path"})
        order = {"token": snapshot.token, "pair": snapshot.pair, "action": decision.action,
                 "signal_snapshot_id": sid, "signal_at": now.isoformat(),
                 "signal_price_usd": str(snapshot.price_usd), "signal_reasons": decision.reasons,
                 "eligible_at": (now + timedelta(seconds=self.execution.latency_seconds)).isoformat(),
                 "expires_at": (now + timedelta(seconds=self.execution.order_ttl_seconds)).isoformat(),
                 "budget_usd": str(budget), "reserved_cash_usd": str(budget if decision.action == "BUY" else cost),
                 "status": "pending", "settings": safe, "execution": self.execution.model_dump(mode="json"),
                 "result_reason": None, "resolved_at": None}
        order["id"] = self.db.conn.execute(
            "INSERT INTO paper_orders(token,pair,status,signal_snapshot_id,payload) VALUES(?,?,'pending',?,'{}')",
            (snapshot.token, snapshot.pair, sid)).lastrowid
        self.db.save_order(order)
        return Decision(action=decision.action, reasons=[*decision.reasons, "paper_order_queued"])

    def process(self, snapshot: Snapshot, now: datetime | None = None) -> Decision | None:
        now = now or utcnow()
        with self.db.conn:
            self.db.conn.execute("BEGIN IMMEDIATE")
            previous = self.db.latest(snapshot.token, snapshot.pair)
            if previous and snapshot.received_at <= previous.received_at:
                return None  # Idempotency and out-of-order guard; no duplicate fills.
            wallet = self.db.load_wallet()
            self._expire(wallet, now)
            holder = snapshot.mint_risk.holder_risk if snapshot.mint_risk else None
            if holder is not None and holder.evidence_payload is not None:
                evidence = json.dumps(holder.evidence_payload, sort_keys=True, separators=(",", ":"))
                if hashlib.sha256(evidence.encode()).hexdigest() != holder.evidence_sha256:
                    raise ValueError("Risk evidence fingerprint mismatch")
                self.db.conn.execute("INSERT OR IGNORE INTO risk_evidence VALUES(?,?)", (holder.evidence_sha256, evidence))
            sid = self.db.add_snapshot(snapshot)
            if 0 <= (now - snapshot.received_at).total_seconds() <= self.settings.max_quote_age_seconds:
                mark(wallet, snapshot, valuation_settings(self.settings, self.execution))
            self._expire(wallet, now)
            pending = next((o for o in self.db.pending_orders() if o["token"] == snapshot.token), None)
            decision = None
            if pending:
                if (pending["pair"] == snapshot.pair and snapshot.received_at > datetime.fromisoformat(pending["signal_at"])
                        and snapshot.received_at >= datetime.fromisoformat(pending["eligible_at"])
                        and now >= snapshot.received_at):
                    frozen_settings = Settings.model_validate(pending["settings"])
                    execution = Execution.model_validate(pending["execution"])
                    outcome = attempt(wallet, pending, snapshot, sid, now, frozen_settings, execution,
                                      failure_draw(pending, execution))
                    pending.update(status=outcome.status, result_reason=outcome.reason,
                                   failed_fee_usd=str(outcome.failed_fee), fill_snapshot_id=sid)
                    self._finish(pending, wallet, outcome.wallet, now, sid,
                                 outcome.fill.fee if outcome.fill else outcome.failed_fee)
                    wallet = outcome.wallet
                    if outcome.fill:
                        fill = outcome.fill
                        self.db.conn.execute("INSERT INTO fills(snapshot_id,payload) VALUES(?,?)",
                                             (sid, fill.model_dump_json()))
                    decision = Decision(action="HOLD" if snapshot.token in wallet.positions else "SKIP",
                                        reasons=["paper_order_" + outcome.status, outcome.reason])
                else:
                    decision = Decision(action="HOLD" if snapshot.token in wallet.positions else "SKIP",
                                        reasons=["pending_order"])
            if decision is None:
                decision = decide(snapshot, previous, wallet, now, self.settings)
                if decision.action in ("BUY", "SELL"):
                    decision = self._queue(snapshot, sid, now, wallet, decision)
            self.db.conn.execute("INSERT INTO decisions(snapshot_id,run_id,signal_at,action,payload) VALUES(?,?,?,?,?)",
                    (sid, self.run_id, now.timestamp(), decision.action, decision.model_dump_json()))
            self.db.save_wallet(wallet)
        log.info("%s token=%s reasons=%s", decision.action, snapshot.token, ",".join(decision.reasons))
        return decision

    def summary(self) -> dict:
        return self.stored_summary(self.db, self.settings)

    @staticmethod
    def stored_summary(db: Database, settings: Settings) -> dict:
        wallet = db.load_wallet()
        counts = db.counts()
        execution = Execution.from_settings(settings)
        pending = db.pending_orders()
        reserved = sum((D(o["reserved_cash_usd"]) for o in pending), D(0))
        origin = db.conn.execute("SELECT value FROM metadata WHERE key='paper_accounting_origin'").fetchone()
        anchor = Wallet.model_validate_json(origin[0]) if origin else wallet
        entries = [json.loads(r[0]) for r in db.conn.execute("SELECT payload FROM paper_ledger ORDER BY id")]
        fields = {"cash": "cash_delta", "news_reserve": "reserve_delta", "owner_profit": "owner_delta", "realized_pnl": "realized_pnl_delta"}
        balanced = all(abs(getattr(wallet, field) - getattr(anchor, field)
                          - sum((D(e[delta]) for e in entries), D(0))) <= D("1e-24") for field, delta in fields.items())
        balance_error = book_value(wallet) - book_value(anchor) - (wallet.realized_pnl - anchor.realized_pnl)
        balanced &= abs(balance_error) <= D("1e-24")
        balanced &= reserved <= wallet.cash
        valuation_warnings = []
        now = utcnow()
        for position in wallet.positions.values():
            latest = db.latest(position.token, position.pair)
            reasons = []
            if latest is None or latest.price_usd is None:
                reasons.append("missing_latest_price")
            if latest is None or not 0 <= (now - latest.received_at).total_seconds() <= settings.max_quote_age_seconds:
                reasons.append("stale_or_future_quote")
            liquidity = trade_liquidity_usd(latest) if latest is not None else None
            if not liquidity or (latest.price_usd is not None
                    and position.quantity * latest.price_usd > liquidity * settings.max_pool_fraction):
                reasons.append("insufficient_exit_liquidity")
            if reasons:
                valuation_warnings.append({"token": position.token, "pair": position.pair, "reasons": reasons})
        return {"mode": "PAPER", "status": "DEAD" if wallet.dead else "ALIVE",
                "cash_usd": f"{wallet.cash:.2f}",
                "estimated_trading_equity_usd": f"{equity(wallet, valuation_settings(settings, execution)):.2f}",
                "news_reserve_usd": f"{wallet.news_reserve:.2f}",
                "owner_profit_usd": f"{wallet.owner_profit:.2f}",
                "realized_pnl_usd": f"{wallet.realized_pnl:.4f}",
                "open_positions": len(wallet.positions), **counts,
                "pending_orders": len(pending), "reserved_cash_usd": str(reserved),
                "available_cash_usd": str(max(D(0), wallet.cash - reserved)),
                "order_status_counts": dict(db.conn.execute("SELECT status,count(*) FROM paper_orders GROUP BY status")),
                "valuation_warnings": valuation_warnings,
                "accounting": {"balanced": balanced, "ledger_entries": len(entries), "balance_error": str(balance_error)}}
