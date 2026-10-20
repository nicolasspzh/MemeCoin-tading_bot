from datetime import UTC, datetime
from pathlib import Path

import pytest

from deploy.release_check import validate_release

ROOT = Path(__file__).resolve().parents[1]


def test_r3_release_matches_frozen_protocol_unit_and_profile():
    config = validate_release(ROOT, now=datetime(2026, 10, 20, 20, 0, tzinfo=UTC))
    unit = (ROOT / "deploy" / config["unit"]).read_text()
    assert "MemoryHigh=1G" in unit and "MemoryMax=1536M" in unit and "WantedBy=multi-user.target" in unit
    assert config["profile"] == "r3"


def test_r3_release_refuses_once_the_window_has_started():
    with pytest.raises(ValueError, match="already started"):
        validate_release(ROOT, now=datetime(2026, 10, 21, 0, 0, tzinfo=UTC))
