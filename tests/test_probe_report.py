from datetime import timedelta
from decimal import Decimal

from collectors.schedule import ObservationSchedule
from config.settings import Settings
from data.database import Database
from data.models import Snapshot, utcnow
from deploy.probe_report import german, probe_report
from operations import campaign

WSOL = "So11111111111111111111111111111111111111112"


def dex_quote(token, pair, at, dex_id="pumpswap", liquidity="20000"):
    return Snapshot(token=token, pair=pair, source="dexscreener", received_at=at, price_usd=Decimal("1"),
                    pair_created_at=at - timedelta(minutes=10), liquidity_usd=Decimal(liquidity),
                    raw={"dexId": dex_id, "quoteToken": {"address": WSOL}})


def test_probe_report_counts_screens_admissions_and_checks(tmp_path):
    start = utcnow()
    settings = Settings(observation_cohorts=True, admission_prefilter=True, max_watch_tokens=8,
                        observation_admission_seconds=720, pool_discovery_enabled=False)
    directory = tmp_path / "probe"
    campaign.initialize(directory, (start + timedelta(hours=8)).isoformat(), settings)
    db = Database(directory / "observations.sqlite3", "dexscreener")
    try:
        recorder = campaign.Recorder(db, settings)
        schedule = ObservationSchedule(db, settings)
        with db.conn:
            for token in ("A", "B", "C"):
                db.discover(token, start.timestamp() + 5, "test")  # after the manifest was created
        now = start.timestamp() + 10
        schedule.record_screens(now, {"A": dex_quote("A", "A-CURVE", start, dex_id="pumpfun"),
                                      "B": dex_quote("B", "B-SWAP", start), "C": None})
        assert schedule.select(now) == ["B"]
        later = now + 1000
        schedule.record_screens(later, {"A": dex_quote("A", "A-SWAP", start), "C": None})
        assert schedule.select(later) == ["B", "A"]
        for token, pair, seconds in (("B", "B-SWAP", 20), ("A", "A-SWAP", 1010)):
            recorder.process(schedule.decorate(dex_quote(token, pair, start + timedelta(seconds=seconds))))
    finally:
        db.close()
    result = probe_report(directory, now=start + timedelta(hours=2))
    assert result["hours_observed"] == 2 and result["admission_prefilter"] is True
    assert result["screens"]["total"] == 5 and result["screens"]["eligible"] == 2
    assert result["screens"]["tokens_screened"] == 3 and result["screens"]["tokens_eligible"] == 2
    assert result["screens"]["rejection_reasons"] == {"unsupported_dex_pool": 1, "no_dex_pair": 2}
    assert result["admissions"]["total"] == 2 and result["admissions"]["gaps_over_900_seconds"] == 1
    assert result["admissions"]["gaps"] == 1 and sum(result["admissions"]["by_utc_hour"].values()) == 2
    assert sum(result["screens"]["eligible_tokens_by_utc_hour"].values()) == 2
    assert sum(result["discovered"]["by_utc_hour"].values()) == 3
    assert result["orders"] == result["fills"] == 0
    assert result["observations"]["total"] == 2 and result["observations"]["entry_check_pass_rows"] == 0
    assert "missing_onchain_checks" in result["observations"]["top_blockers"]
    text = german(result)
    assert "3 Coins geprüft, 2 geeignet" in text and "über 900 s: 1 von 1" in text and "Orders/Ausführungen: 0/0" in text


def test_probe_report_before_first_database(tmp_path):
    directory = tmp_path / "probe"
    campaign.initialize(directory, (utcnow() + timedelta(hours=8)).isoformat(), Settings(observation_cohorts=True))
    result = probe_report(directory)
    assert result["database"] is None
    assert "noch nicht vorhanden" in german(result)
