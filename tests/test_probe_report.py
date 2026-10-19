from datetime import UTC, datetime, timedelta
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
        with db.conn:
            for second in range(0, 7200, 60):
                db.record_health("collector", start.timestamp() + second, "cycle", "{}")
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


def test_probe_report_counts_only_until_an_early_stop(tmp_path):
    start = utcnow()
    directory = tmp_path / "probe"
    campaign.initialize(directory, (start + timedelta(hours=24)).isoformat(), Settings(observation_cohorts=True))
    created = datetime.fromisoformat(campaign.load_manifest(directory)["created_at"])
    campaign.atomic_json(directory / "state.json", {"status": "stopped_by_request",
                                                    "stopped_at": (created + timedelta(hours=7)).isoformat()})
    result = probe_report(directory, now=start + timedelta(hours=30))
    assert result["hours_observed"] == 7 and result["state"]["stopped_at"]
    campaign.atomic_json(directory / "state.json", {"status": "running"})
    assert probe_report(directory, now=created + timedelta(hours=2))["hours_observed"] == 2


def test_outages_are_excluded_from_rates_and_admission_gaps(tmp_path):
    start = utcnow()
    settings = Settings(observation_cohorts=True, admission_prefilter=True, pool_discovery_enabled=False)
    directory = tmp_path / "probe"
    campaign.initialize(directory, (start + timedelta(hours=8)).isoformat(), settings)
    created = datetime.fromisoformat(campaign.load_manifest(directory)["created_at"]).timestamp()
    db = Database(directory / "observations.sqlite3", "dexscreener")
    try:
        with db.conn:
            # Cycles for an hour, a one-hour reboot, then another hour of cycles.
            for second in [*range(0, 3600, 60), *range(7200, 10800, 60)]:
                db.record_health("collector", created + second, "cycle", "{}")
            for token, admitted in (("A", 600), ("B", 1320), ("C", 7300)):
                db.discover(token, created + admitted, "test")
                db.conn.execute("INSERT INTO observation_tracks VALUES(?,?,?,?,?,NULL,NULL)",
                                (token, token + "-POOL", created + admitted, created + admitted + 1800,
                                 created + admitted + 5760))
    finally:
        db.close()
    result = probe_report(directory, now=datetime.fromtimestamp(created + 10800, UTC))
    assert result["hours_observed"] == 3 and result["hours_active"] == 1.98  # 3660 s without cycles
    assert len(result["outages"]) == 1 and result["outages"][0]["seconds"] == 3660
    assert result["admissions"]["gaps"] == 1 and result["admissions"]["gaps_interrupted_by_outage"] == 1
    assert result["admissions"]["gaps_over_900_seconds"] == 0
    assert "Ausfälle: 1 (61 Minuten)" in german(result)
