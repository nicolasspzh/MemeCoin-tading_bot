import hashlib
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from decimal import Decimal as D

import pytest

from backtesting.__main__ import freeze_input
from backtesting.replay import Execution, Observation, Replay, quality_profile, read_observations
from config.settings import Settings


def run_quotes(quotes, **execution):
    simulator = Replay(Settings(), Execution(failure_probability=0, **execution))
    metrics = simulator.run([Observation(i + 1, q) for i, q in enumerate(quotes)])
    return simulator, metrics


def test_signal_fills_at_later_observed_price_and_budget_is_fixed(quote):
    quotes = [quote(), quote(20, price_usd=D("1.03")), quote(40, price_usd=D("1.04"))]
    replay, metrics = run_quotes(quotes)
    fill = replay.fills[0]
    assert datetime.fromisoformat(fill["signal_at"]) == quotes[1].received_at
    assert datetime.fromisoformat(fill["simulated_at"]) == quotes[2].received_at
    assert fill["effective_delay_seconds"] == 20
    assert fill["signal_snapshot_id"] == 2 and fill["snapshot_id"] == 3
    assert D(fill["price"]) > D("1.04")  # adverse slippage plus size/liquidity impact
    assert D(fill["cash_flow"]) == D("-2.50")
    assert metrics["completed_trades"] == 0 and len(metrics["open_positions"]) == 1


def test_round_trip_conservation_and_costs(quote):
    quotes = [quote(), quote(20, price_usd=D("1.03")), quote(40, price_usd=D("1.04")),
              quote(60, price_usd=D("1.4")), quote(80, price_usd=D("1.39"), buys_5m=10)]
    replay, metrics = run_quotes(quotes)
    assert [f["side"] for f in replay.fills] == ["BUY", "SELL"]
    assert metrics["completed_trades"] == 1
    assert D(metrics["total_equity_mark_usd"]) == 50 + D(metrics["net_realized_pnl_usd"])
    assert D(metrics["priority_fees_included_usd"]) == D(".01")
    assert D(metrics["slippage_and_impact_usd"]) > 0
    assert D(metrics["successful_fees_usd"]) > D(".05")
    assert D(metrics["news_reserve_usd"]) > 0
    assert not metrics["open_positions"]


def test_later_prices_do_not_rewrite_earlier_signals_or_fills(quote):
    prefix = [quote(), quote(20, price_usd=D("1.03")), quote(40, price_usd=D("1.04"))]
    left, _ = run_quotes([*prefix, quote(60, price_usd=D("10"))])
    right, _ = run_quotes([*prefix, quote(60, price_usd=D(".01"))])
    assert left.decisions[:3] == right.decisions[:3]
    assert left.fills[0] == right.fills[0]


def test_future_onchain_features_are_unavailable_at_quote_time(quote):
    initial, signal, intermediate, fill = quote(), quote(20, price_usd=D("1.03")), quote(29, price_usd=D("1.035")), quote(35, price_usd=D("1.04"))
    signal.mint_risk.checked_at = signal.received_at + timedelta(seconds=10)
    intermediate.mint_risk.checked_at = intermediate.received_at + timedelta(seconds=2)
    replay, _ = run_quotes([initial, signal, intermediate, fill])
    assert replay.orders[0]["signal_at"] == signal.mint_risk.checked_at.isoformat()
    assert replay.fills[0]["snapshot_id"] == 4
    assert replay.fills[0]["effective_delay_seconds"] == 5


def test_minimum_latency_and_expiry(quote):
    quotes = [quote(), quote(20, price_usd=D("1.03")), quote(30, price_usd=D("1.035")), quote(40, price_usd=D("1.04"))]
    replay, _ = run_quotes(quotes, latency_seconds=20)
    assert replay.fills[0]["snapshot_id"] == 4
    expired, _ = run_quotes(quotes, order_ttl_seconds=5)
    assert expired.orders[0]["status"] == "expired"
    assert not expired.fills


def test_no_fill_or_forced_sale_at_end_of_data(quote):
    pending, result = run_quotes([quote(), quote(20, price_usd=D("1.03"))], latency_seconds=0)
    assert result["completed_trades"] == 0 and result["win_rate_pct"] is None
    assert result["profit_factor_closed_trades"] is None
    assert result["ending_cash_usd"] == "50"
    assert pending.orders[0]["status"] == "unfilled_end_of_data"
    assert not pending.fills


def test_failed_transaction_charges_costs_and_does_not_open_position(quote):
    replay = Replay(Settings(), Execution(failure_probability=1))
    result = replay.run([Observation(1, quote()), Observation(2, quote(20, price_usd=D("1.03"))),
                         Observation(3, quote(40, price_usd=D("1.031")))])
    assert replay.orders[0]["status"] == "failed"
    assert not replay.fills and not result["open_positions"]
    assert D(result["ending_cash_usd"]) == D("49.975")
    assert D(result["net_realized_pnl_usd"]) == -D(result["failed_fees_usd"]) == D("-.025")


def test_adverse_price_limit_causes_failed_transaction(quote):
    replay, result = run_quotes([quote(), quote(20, price_usd=D("1.03")), quote(40, price_usd=D("1.5"))])
    assert replay.orders[0]["result_reason"] == "price_moved_beyond_limit"
    assert result["successful_fills"] == 0
    assert D(result["failed_fees_usd"]) > 0


def test_actual_quote_liquidity_blocks_fill(quote):
    replay, result = run_quotes([quote(), quote(20, price_usd=D("1.03")), quote(40, price_usd=D("1.04"), liquidity_usd=D("1"))])
    assert replay.orders[0]["status"] == "rejected"
    assert replay.orders[0]["result_reason"] == "excessive_pool_participation"
    assert result["successful_fills"] == 0 and result["ending_cash_usd"] == "50"


def test_pending_orders_reserve_position_capacity(quote):
    replay = Replay(Settings(max_positions=1), Execution(failure_probability=0))
    quotes = [quote(token="A", pair="A"), quote(token="B", pair="B"),
              quote(20, token="A", pair="A", price_usd=D("1.03")),
              quote(20, token="B", pair="B", price_usd=D("1.03"))]
    result = replay.run([Observation(i + 1, q) for i, q in enumerate(quotes)])
    assert result["orders"] == 1
    assert result["decision_reasons"]["position_limit_including_pending"] == 1


def test_input_is_readonly_and_future_outcome_tables_are_ignored(tmp_path, quote):
    path = tmp_path / "source.sqlite3"
    records = [Observation(1, quote()), Observation(2, quote(20, price_usd=D("1.03")))]
    freeze_input(path, records, "demo")
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE outcomes(future_price TEXT)")
        connection.execute("INSERT INTO outcomes VALUES('1000000000000')")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    loaded, provenance = read_observations(path, allow_demo=True)
    assert loaded == records and provenance["rows"] == 2
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    with pytest.raises(ValueError, match="Synthetic"):
        read_observations(path)


def test_corrupt_metadata_and_duplicate_keys_rejected(tmp_path, quote):
    path = tmp_path / "source.sqlite3"
    records = [Observation(1, quote()), Observation(2, quote())]
    freeze_input(path, records, "demo")
    with pytest.raises(ValueError, match="Duplicate"):
        read_observations(path, allow_demo=True)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE snapshots SET token='OTHER' WHERE id=1")
    with pytest.raises(ValueError, match="mismatch"):
        read_observations(path, allow_demo=True)


def test_profile_reports_single_point_coins_and_nulls(quote):
    records = [Observation(1, quote(mint_risk=None)), Observation(2, quote(10, token="OTHER", price_usd=None))]
    profile = quality_profile(records)
    assert profile["pairs_with_multiple_quotes"] == 0
    assert profile["missing_fields"]["price_usd"] == 1
    assert profile["risk_data_status"]["missing"] == 1


def test_cli_produces_reproducible_artifacts_and_never_overwrites(tmp_path, quote):
    path = tmp_path / "source.sqlite3"
    snapshots = [quote(), quote(20, price_usd=D("1.03")), quote(40, price_usd=D("1.04"))]
    freeze_input(path, [Observation(i + 1, s) for i, s in enumerate(snapshots)], "demo")
    target = tmp_path / "result"
    args = [sys.executable, "-m", "backtesting", "--db", str(path), "--out", str(target), "--allow-demo"]
    completed = subprocess.run(args, capture_output=True, text=True, check=True)
    assert json.loads(completed.stdout)["input_source"] == "demo"
    assert (target / "baseline" / "orders.csv").exists()
    assert (target / "stress" / "equity.csv").exists()
    first = json.loads((target / "result.json").read_text())
    assert subprocess.run(args, capture_output=True).returncode == 2
    second_target = tmp_path / "repeat"
    subprocess.run([sys.executable, "-m", "backtesting", "--db", str(target / "input.sqlite3"),
                    "--out", str(second_target), "--allow-demo"], capture_output=True, text=True, check=True)
    second = json.loads((second_target / "result.json").read_text())
    assert first["scenarios"] == second["scenarios"]
    assert first["input"]["snapshots_sha256"] == second["input"]["snapshots_sha256"]
