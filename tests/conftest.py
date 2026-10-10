from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from config.settings import Settings
from data.database import Database
from data.models import MintRisk, Snapshot
from trading.engine import Engine


@pytest.fixture
def quote():
    def make(seconds=0, **changes):
        now = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds)
        data = dict(token="TOKEN", pair="POOL", source="demo", received_at=now,
                    pair_created_at=now - timedelta(minutes=10), price_usd=Decimal("1"),
                    liquidity_usd=Decimal("20000"), volume_5m_usd=Decimal("3000"),
                    buys_5m=60, sells_5m=20,
                    mint_risk=MintRisk(checked_at=now, supported_program=True,
                                      mint_authority=False, freeze_authority=False,
                                      top10_account_fraction=Decimal("0.25")))
        data.update(changes)
        return Snapshot(**data)
    return make


@pytest.fixture
def engine(tmp_path):
    db = Database(tmp_path / "test.sqlite3", "demo")
    yield Engine(db, Settings(paper_failure_probability=0))
    db.close()
