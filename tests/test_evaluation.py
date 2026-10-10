import json
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest

from backtesting.__main__ import freeze_input
from backtesting.evaluation import (POLICY, data_quality, diagnostic, digest, evaluate,
                                    load_protocol, merge_inputs, prepare, readiness, scenario_definitions)
from backtesting.replay import Observation
from config.settings import Settings


def dataset(path, quotes, source='demo'):
    records = [Observation(i + 1, q.model_copy(update={'source': source})) for i, q in enumerate(quotes)]
    freeze_input(path, records, source)
    return path


def test_merge_deduplicates_exact_copies_and_preserves_origins(tmp_path, quote):
    first = dataset(tmp_path / 'a.sqlite3', [quote(), quote(20)])
    second = dataset(tmp_path / 'b.sqlite3', [quote(20), quote(40)])
    before = first.read_bytes()
    records, provenance = merge_inputs([first, second], allow_demo=True)
    assert len(records) == 3 and provenance['duplicates_removed'] == 1
    assert len(provenance['row_mapping'][1]['origins']) == 2
    assert first.read_bytes() == before
    reverse, _ = merge_inputs([second, first], allow_demo=True)
    assert reverse == records


def test_conflicting_observations_are_not_silently_replaced(tmp_path, quote):
    one = dataset(tmp_path / 'a.sqlite3', [quote()])
    two = dataset(tmp_path / 'b.sqlite3', [quote(price_usd=D('2'))])
    with pytest.raises(ValueError, match='Conflicting'):
        merge_inputs([one, two], allow_demo=True)


def test_synthetic_data_requires_opt_in_and_cannot_mix_with_market(tmp_path, quote):
    demo = dataset(tmp_path / 'demo.sqlite3', [quote()])
    market = dataset(tmp_path / 'market.sqlite3', [quote()], 'dexscreener')
    with pytest.raises(ValueError, match='Synthetic'):
        merge_inputs([demo])
    with pytest.raises(ValueError, match='cannot be mixed'):
        merge_inputs([demo, market], allow_demo=True)


def test_days_apart_are_not_continuous_coverage(quote):
    records = [Observation(1, quote()), Observation(2, quote(7 * 86400))]
    quality = data_quality(records, Settings())
    assert quality['active_5min_buckets'] == 2
    assert quality['active_5min_fraction'] < .001
    assert 'sparse_time_coverage' in quality['blockers']
    assert 'missing_or_sparse_same_pool_followups' in quality['blockers']
    assert not quality['readiness']


def test_modern_check_cannot_reclassify_legacy_or_missing_data(quote):
    old = quote()
    missing = quote(20, mint_risk=None, price_usd=None)
    quality = data_quality([Observation(1, old), Observation(2, missing)], Settings())
    assert quality['modern_risk_fraction'] == 0
    assert quality['priced_fraction'] == .5
    assert 'legacy_or_missing_risk_data' in quality['blockers']


def test_stress_never_reduces_base_cost_or_failure_assumptions():
    settings = Settings(slippage_bps=D(500), fixed_fee_usd=D('.1'),
                        paper_priority_fee_usd=D('.05'), paper_failure_probability=.2)
    scenarios = scenario_definitions(settings)
    assert D(scenarios['stress']['settings']['slippage_bps']) > settings.slippage_bps
    assert D(scenarios['stress']['settings']['fixed_fee_usd']) >= settings.fixed_fee_usd
    assert D(scenarios['stress']['execution']['priority_fee_usd']) >= settings.paper_priority_fee_usd
    assert scenarios['stress']['execution']['failure_probability'] >= .2


def test_zero_trade_replay_never_passes_evidence_gate():
    metrics = {'completed_trades': 0, 'distinct_closed_trade_tokens': 0,
               'open_positions': [], 'order_status_counts': {}, 'net_realized_pnl_usd': '0'}
    result = readiness({'blockers': []}, {'baseline': [{'metrics': metrics}]}, 'dexscreener', True)
    assert not result['eligible_for_review'] and not result['live_trading_approved']
    assert 'too_few_closed_trades' in result['blockers']
    assert not result['positive_net_realized_pnl_in_every_scenario']


def test_profitable_known_data_is_still_not_an_unseen_test():
    metrics = {'completed_trades': 1000, 'distinct_closed_trade_tokens': 100,
               'open_positions': [], 'order_status_counts': {}, 'net_realized_pnl_usd': '20'}
    result = readiness({'blockers': []}, {'baseline': [{'metrics': metrics}]}, 'dexscreener', False)
    assert not result['eligible_for_review']
    assert 'previously_available_development_data' in result['blockers']


@pytest.fixture
def planned(tmp_path, quote):
    now = quote(3600).received_at
    source = dataset(tmp_path / 'development.sqlite3', [quote(), quote(20)], 'dexscreener')
    out = tmp_path / 'plan'
    envelope = prepare([source], out, Settings(solana_rpc_url='https://example.com/?key=private-key'), now=now)
    return out / 'protocol.json', envelope['plan'], source


def test_plan_records_future_window_and_strips_endpoints(planned):
    path, plan, _ = planned
    assert datetime.fromisoformat(plan['test_start_utc']) > datetime.fromisoformat(plan['created_at_utc'])
    assert datetime.fromisoformat(plan['test_end_exclusive_utc']) - datetime.fromisoformat(plan['test_start_utc']) == timedelta(days=7)
    assert plan['seeds'] == [7, 17, 29]
    assert plan['quality_policy'] == POLICY
    assert 'private-key' not in path.read_text() and 'solana_rpc_url' not in path.read_text()


def test_past_or_embargoed_holdout_cannot_be_predeclared(tmp_path, quote):
    source = dataset(tmp_path / 'source.sqlite3', [quote()], 'dexscreener')
    with pytest.raises(ValueError, match='future'):
        prepare([source], tmp_path / 'bad', Settings(), start=quote(20).received_at.isoformat(), now=quote(30).received_at)
    assert not (tmp_path / 'bad').exists()


def test_protocol_detects_mutation_and_code_changes(planned, monkeypatch):
    from backtesting import evaluation
    path, plan, _ = planned
    monkeypatch.setattr(evaluation, 'code_digest', lambda: 'changed-code')
    with pytest.raises(ValueError, match='Code changed'):
        load_protocol(path)
    monkeypatch.undo()
    envelope = json.loads(path.read_text())
    envelope['plan']['seeds'] = [1]
    path.write_text(json.dumps(envelope))
    with pytest.raises(ValueError, match='fingerprint'):
        load_protocol(path)


def test_evaluation_does_not_open_test_source_before_end(planned, tmp_path, monkeypatch):
    from backtesting import evaluation
    path, plan, _ = planned
    monkeypatch.setattr(evaluation, 'merge_inputs', lambda *a, **k: pytest.fail('Holdout was inspected early'))
    result = evaluate(path, [tmp_path / 'not-even-created.sqlite3'], tmp_path / 'early', now=datetime.fromisoformat(plan['test_start_utc']))
    assert result['status'] == 'WAITING_FOR_WINDOW_END' and not result['performance_evaluated']


def test_holdout_boundaries_exclude_early_quotes_and_late_risk(planned, tmp_path, quote):
    path, plan, _ = planned
    start, end = datetime.fromisoformat(plan['test_start_utc']), datetime.fromisoformat(plan['test_end_exclusive_utc'])
    offset = int((start - quote().received_at).total_seconds())
    day_end = int((end - quote().received_at).total_seconds())
    crosses_start = quote(offset - 1)
    crosses_start.mint_risk.checked_at = start + timedelta(seconds=1)
    crosses_end = quote(day_end - 1)
    crosses_end.mint_risk.checked_at = end
    snapshots = [crosses_start, quote(offset), quote(offset + 20), crosses_end, quote(day_end)]
    source = dataset(tmp_path / 'test.sqlite3', snapshots, 'dexscreener')
    result = evaluate(path, [source], tmp_path / 'result', now=end)
    assert result['data_quality']['observations'] == 2
    assert result['excluded_rows'] == {'before_window': 1, 'risk_arrived_after_window': 1, 'after_window': 1}
    assert result['assessment']['status'] == 'INSUFFICIENT_EVIDENCE'
    with sqlite3.connect(tmp_path / 'result/input.sqlite3') as db:
        assert db.execute('SELECT count(*) FROM snapshots').fetchone()[0] == 2


def test_empty_holdout_is_reported_without_fabricated_metrics(planned, tmp_path):
    path, plan, source = planned
    result = evaluate(path, [source], tmp_path / 'empty', now=datetime.fromisoformat(plan['test_end_exclusive_utc']))
    assert result['data_quality']['observations'] == 0 and result['scenarios'] == {}
    assert 'no_observations' in result['assessment']['blockers']


def test_diagnostic_is_reproducible_and_never_overwrites(tmp_path, quote):
    source = dataset(tmp_path / 'source.sqlite3', [quote(), quote(20, price_usd=D('1.03')), quote(40, price_usd=D('1.04'))])
    one = diagnostic([source], tmp_path / 'one', Settings(), allow_demo=True)
    two = diagnostic([source], tmp_path / 'two', Settings(), allow_demo=True)
    assert one['scenarios'] == two['scenarios']
    assert one['frozen_snapshots_sha256'] == two['frozen_snapshots_sha256']
    assert one['assessment']['status'] == 'SYNTHETIC_ONLY'
    assert len(one['scenarios']['baseline']) == len(one['scenarios']['stress']) == 3
    with pytest.raises(FileExistsError):
        diagnostic([source], tmp_path / 'one', Settings(), allow_demo=True)
