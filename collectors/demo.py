"""Deterministic synthetic observations, deliberately separate from market data."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from data.models import MintRisk, Snapshot


def demo_snapshots():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    # Entry, take-profit exit, sell pressure and later label observations.
    for seconds, price in [(0, "1"), (20, "1.03"), (40, "1.04"), (60, "1.4"),
                           (80, "1.39"), (300, "1.15"), (900, "1.10"),
                           (3600, "1.05"), (3660, "1.04")]:
        now = start + timedelta(seconds=seconds)
        risk = MintRisk(checked_at=now, supported_program=True, mint_authority=False,
                        freeze_authority=False, top10_account_fraction=Decimal("0.25"))
        common = dict(source="demo", received_at=now, pair_created_at=start - timedelta(minutes=5),
                      price_usd=Decimal(price), market_cap_usd=Decimal("100000"),
                      volume_5m_usd=Decimal("5000"), buys_5m=60 if seconds < 60 else 15,
                      sells_5m=20, mint_risk=risk, raw={"synthetic": True})
        yield Snapshot(token="DEMO_MOMENTUM", pair="DEMO_POOL_A", symbol="DEMO",
                       liquidity_usd=Decimal("20000"), **common)
        yield Snapshot(token="DEMO_ILLIQUID", pair="DEMO_POOL_B", symbol="RISK",
                       liquidity_usd=Decimal("50"), **common)
