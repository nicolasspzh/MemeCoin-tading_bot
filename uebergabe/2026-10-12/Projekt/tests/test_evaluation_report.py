import hashlib
import json

import pytest

from backtesting.__main__ import freeze_input
from backtesting.evaluation import diagnostic
from backtesting.replay import Observation
from config.settings import Settings
from operations.evaluation_report import build_report, render


@pytest.fixture
def result_file(tmp_path, quote):
    db = tmp_path / 'demo.sqlite3'
    freeze_input(db, [Observation(1, quote()), Observation(2, quote(20))], 'demo')
    diagnostic([db], tmp_path / 'evaluation', Settings(), allow_demo=True)
    return tmp_path / 'evaluation/result.json'


def test_actual_diagnostic_renders_all_runs_without_changing_input(result_file, tmp_path):
    before = result_file.read_bytes()
    out = tmp_path / 'report.html'
    build_report(result_file, out)
    page = out.read_text()
    assert 'KÜNSTLICHE TESTDATEN' in page
    assert 'Zu wenige abgeschlossene Trades' in page
    assert 'Netto realisiert' in page and 'Prioritätsgebühren sind bereits enthalten' in page
    for scenario in ('baseline', 'stress'):
        for seed in (7, 17, 29):
            assert f'<td>{scenario}</td><td>{seed}</td>' in page
    assert hashlib.sha256(before).hexdigest() in page
    assert str(result_file.parent) not in page
    assert result_file.read_bytes() == before
    with pytest.raises(FileExistsError):
        build_report(result_file, out)


def test_waiting_result_never_renders_injected_performance():
    result = {'status': 'WAITING_FOR_WINDOW_END',
              'test_start_utc': '2026-10-09T00:00:00+00:00',
              'test_end_exclusive_utc': '2026-10-16T00:00:00+00:00',
              'scenarios': {'UNEXPECTED_RESULTS': []}}
    page = render(result, 'hash')
    assert '09.10.2026 02:00:00 CEST' in page
    assert 'Auswertung noch gesperrt' in page
    assert 'UNEXPECTED_RESULTS' not in page


def test_escape_untrusted_text_and_omit_private_fields(result_file):
    result = json.loads(result_file.read_text())
    result['assessment']['blockers'].append('<script>alert(1)</script>')
    result['inputs']['private_endpoint'] = 'SECRET_SENTINEL'
    result['scenario_definitions']['baseline']['settings']['solana_rpc_url'] = 'SECRET_SENTINEL'
    page = render(result, 'hash')
    assert '<script>' not in page
    assert '&lt;script&gt;' in page
    assert 'SECRET_SENTINEL' not in page


@pytest.mark.parametrize('value', ['NaN', 'Infinity', 'not-a-number'])
def test_bad_numeric_data_leaves_no_report(result_file, tmp_path, value):
    result = json.loads(result_file.read_text())
    result['scenarios']['baseline'][0]['metrics']['net_realized_pnl_usd'] = value
    result_file.write_text(json.dumps(result))
    out = tmp_path / 'bad.html'
    with pytest.raises(ValueError):
        build_report(result_file, out)
    assert not out.exists()


def test_missing_measurements_are_not_zero_and_unknown_blocker_is_preserved(result_file):
    result = json.loads(result_file.read_text())
    result['data_quality'].pop('priced_fraction')
    result['scenarios'] = {}
    result['assessment']['blockers'].append('future_quality_blocker')
    page = render(result, 'hash')
    assert '<td>Anteil mit Kurs</td><td>nicht verfügbar</td>' in page
    assert 'Keine Simulationsläufe verfügbar' in page
    assert 'future_quality_blocker' in page


def test_synthetic_results_cannot_claim_reviewable_holdout(result_file):
    result = json.loads(result_file.read_text())
    result['assessment']['status'] = 'REVIEWABLE_HOLDOUT'
    result['assessment']['blockers'] = []
    result['prospective'] = True
    result['kind'] = 'PROSPECTIVE_WINDOW_EVALUATION'
    with pytest.raises(ValueError, match='Contradictory'):
        render(result, 'hash')


def test_reviewable_label_is_not_a_trading_approval(result_file):
    result = json.loads(result_file.read_text())
    # Rendering fixture only, not an actual holdout or evaluated market result.
    result['inputs']['source'] = 'dexscreener'
    result['assessment']['status'] = 'REVIEWABLE_HOLDOUT'
    result['assessment']['blockers'] = []
    result['prospective'] = True
    result['kind'] = 'PROSPECTIVE_WINDOW_EVALUATION'
    page = render(result, 'hash')
    assert 'Status laut Ergebnisdatei' in page
    assert 'keine Handelsfreigabe' in page
    assert 'bestätigt deren Herkunft nicht unabhängig' in page
