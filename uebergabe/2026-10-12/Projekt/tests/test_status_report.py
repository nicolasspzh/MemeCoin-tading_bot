from datetime import UTC, datetime
import json

from data.database import Database
from deploy.status import main, report


NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)


def test_legacy_coverage_and_credits_are_not_confused():
    text = report({'directory': '/example', 'supervisor_running': True,
                   'state': {'data_degraded': True}, 'data': {
                       'snapshots': 23012, 'priced_snapshots': 18541, 'tokens': 435,
                       'last_quote_age_seconds': 21.5, 'orders': 0, 'fills': 0,
                       'outcomes': [{'horizon_seconds': 3600, 'observed': 1380, 'due': 17113}]}}, now=NOW)
    assert "18'541 (80.6 %)" in text
    assert "1'380 / 17'113 (8.1 %)" in text
    assert 'Anfragen sind keine Credits' in text
    assert 'Lebenszeichen: unbekannt' in text
    assert 'Ursache ist aus diesem Flag allein nicht ersichtlich' in text


def test_stale_prices_budget_exhaustion_and_unexpected_orders_are_visible():
    text = report({'directory': '/example', 'supervisor_running': True,
                   'until': '2026-10-16T01:06:00+00:00',
                   'state': {'heartbeat_at': '2026-10-08T11:00:00+00:00'},
                   'rpc_request_budget': {'2026-10-07': 40, '2026-10-08': 60},
                   'rpc_budget_limits': {'rpc_daily_request_limit': 60, 'rpc_total_request_limit': 100},
                   'data': {'snapshots': 1, 'priced_snapshots': 1, 'tokens': 1,
                            'last_quote_age_seconds': 180, 'orders': 1, 'fills': 0}},
                  now=NOW, free_bytes=1024**3)
    assert text.count('LIMIT ERREICHT') == 2
    assert 'vor 180 Sekunden – BITTE PRÜFEN' in text
    assert 'vor 3600 Sekunden – BITTE PRÜFEN' in text
    assert 'UNERWARTET' in text and 'KNAPP' in text
    assert '16.10.2026 03:06:00 CEST' in text


def test_completed_campaign_is_not_reported_as_running():
    text = report({'directory': '/example', 'supervisor_running': False,
                   'until': '2026-10-07T00:00:00+00:00'}, now=NOW)
    assert 'beendet; Sammelzeit abgelaufen' in text
    assert 'keine Datensammlung bestätigt' in text


def test_cli_reads_real_database_without_changing_observations(tmp_path, quote, capsys):
    (tmp_path / 'manifest.json').write_text(json.dumps({'manifest': {}}))
    dbfile = tmp_path / 'observations.sqlite3'
    db = Database(dbfile, 'dexscreener')
    with db.conn:
        db.add_snapshot(quote(source='dexscreener'))
    db.close()
    before = dbfile.read_bytes()
    assert main(['--directory', str(tmp_path)]) == 0
    assert 'Beobachtungen: 1;' in capsys.readouterr().out
    assert dbfile.read_bytes() == before
    assert not (tmp_path / 'supervisor.lock').exists()


def test_missing_directory_does_not_create_a_campaign(tmp_path, capsys):
    missing = tmp_path / 'missing'
    assert main(['--directory', str(missing)]) == 2
    assert not missing.exists()
    assert 'Keine initialisierte Sammlung' in capsys.readouterr().err
