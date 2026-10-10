from datetime import UTC, datetime, timedelta
import json

import pytest

from deploy import telegram_notify as telegram
from deploy.setup_telegram import pairing_chat


NOW = datetime(2026, 10, 8, 7, tzinfo=UTC)  # 09:00 Switzerland
FREE = 10 * 1024**3


def healthy(now=NOW):
    return {'directory': '/example', 'supervisor_running': True,
            'until': '2026-10-16T01:06:00+00:00',
            'state': {'heartbeat_at': now.isoformat(), 'started_at': now.isoformat()},
            'data': {'snapshots': 3, 'priced_snapshots': 2, 'tokens': 1,
                     'last_quote_age_seconds': 10, 'orders': 0, 'fills': 0}}


def test_daily_report_deduplicates_and_tracks_swiss_day():
    message, state = telegram.notification(healthy(), {}, now=NOW, free_bytes=FREE)
    assert 'Tagesbericht' in message and 'Telegram verbunden' in message
    later = NOW + timedelta(minutes=5)
    assert telegram.notification(healthy(later), state, now=later, free_bytes=FREE)[0] is None
    tomorrow = NOW + timedelta(days=1)
    early = tomorrow - timedelta(minutes=5)
    assert telegram.notification(healthy(early), state, now=early, free_bytes=FREE)[0] is None
    assert 'Tagesbericht' in telegram.notification(healthy(tomorrow), state, now=tomorrow, free_bytes=FREE)[0]


def test_alert_deduplication_and_recovery_without_daily_reports():
    _, state = telegram.notification(healthy(), {}, now=NOW, free_bytes=FREE, daily=False)
    failed = healthy()
    failed['data']['last_quote_age_seconds'] = 301
    message, state = telegram.notification(failed, state, now=NOW, free_bytes=FREE, daily=False)
    assert 'Bitte prüfen' in message
    assert telegram.notification(failed, state, now=NOW, free_bytes=FREE, daily=False)[0] is None
    message, state = telegram.notification(healthy(), state, now=NOW, free_bytes=FREE, daily=False)
    assert 'nicht mehr vorhanden' in message
    assert 'Tagesbericht' not in message


def test_planned_end_is_not_a_stale_price_alarm_and_sent_once():
    done = datetime(2026, 10, 16, 2, tzinfo=UTC)
    value = healthy()
    value['supervisor_running'] = False
    value['data']['last_quote_age_seconds'] = 4000
    msg, state = telegram.notification(value, {'initialized': True}, now=done, free_bytes=FREE)
    assert 'Sammelzeit ist abgelaufen' in msg
    assert 'Bitte prüfen' not in msg and 'Tagesbericht' not in msg
    assert telegram.notification(value, state, now=done, free_bytes=FREE)[0] is None


def test_telegram_failure_retries_without_marking_notification_sent(tmp_path, monkeypatch):
    directory = tmp_path / 'campaign'
    directory.mkdir()
    (directory / 'manifest.json').write_text('{}')
    state = tmp_path / 'telegram-state.json'
    monkeypatch.setattr(telegram, 'status', lambda p: healthy())
    def failed(*args):
        raise telegram.TelegramError('simulated failure')
    with pytest.raises(telegram.TelegramError):
        telegram.run(directory, state, 'placeholder', '123', now=NOW, send=failed)
    assert not state.exists()
    calls = []
    def success(token, method, payload):
        calls.append(payload)
        return {'chat': {'id': 123}}
    assert telegram.run(directory, state, 'placeholder', '123', now=NOW, send=success)
    assert len(calls) == 1
    assert json.loads(state.read_text())['initialized']
    assert not telegram.run(directory, state, 'placeholder', '123', now=NOW, send=success)
    assert len(calls) == 1


def test_status_failure_reports_unknown_instead_of_false_healthy(tmp_path, monkeypatch):
    monkeypatch.setattr(telegram, 'status', lambda p: (_ for _ in ()).throw(ValueError('secret-detail')))
    (tmp_path / 'manifest.json').write_text('{}')
    sent = []
    def send(token, method, payload):
        sent.append(payload['text'])
        return {'chat': {'id': 123}}
    telegram.run(tmp_path, tmp_path / 'state.json', 'placeholder', '123', now=NOW, send=send)
    assert 'Betriebszustand unbekannt' in sent[0]
    assert 'secret-detail' not in sent[0] and 'NICHT AKTIV' not in sent[0]


def test_only_nonce_matched_private_chat_can_be_paired():
    def update(chat_id, text, kind='private'):
        return {'message': {'text': text, 'chat': {'type': kind, 'id': chat_id}}}
    updates = [update(123, '/start wrong'), update(-5, '/start code', 'group'), update(456, '/start code')]
    assert pairing_chat(updates, 'code')['id'] == 456
    with pytest.raises(ValueError):
        pairing_chat(updates + [update(789, '/start code')], 'code')
    with pytest.raises(ValueError):
        pairing_chat(updates, 'unknown')


def test_http_errors_do_not_expose_token(monkeypatch):
    token = '123:' + 'sensitive_token_' * 3
    def fail(*args, **kwargs):
        raise OSError('https://api.telegram.org/bot' + token)
    monkeypatch.setattr(telegram, 'urlopen', fail)
    with pytest.raises(telegram.TelegramError) as error:
        telegram.api(token, 'getMe', {})
    assert token not in str(error.value)
    assert error.value.__suppress_context__


def test_budget_alert_does_not_infer_helius_credits():
    value = healthy()
    value.update(rpc_request_budget={'2026-10-08': 63000},
                 rpc_budget_limits={'rpc_daily_request_limit': 70000, 'rpc_total_request_limit': 600000})
    msg, _ = telegram.notification(value, {}, now=NOW, free_bytes=FREE)
    assert 'Tagesbudget der RPC-Anfragen zu mindestens 90 % verbraucht' in msg
    assert 'Anfragen sind keine Credits' in msg


def test_stale_heartbeat_is_an_alert_and_daily_time_follows_winter_offset():
    late = NOW + timedelta(minutes=5)
    assert 'Kein aktuelles Lebenszeichen' in telegram.issues(healthy(), late, FREE)[0]
    winter = datetime(2026, 11, 1, 8, tzinfo=UTC)  # 09:00 CET
    value = healthy(winter)
    value['until'] = '2026-11-03T00:00:00+00:00'
    message, _ = telegram.notification(value, {'initialized': True, 'issues': []}, now=winter, free_bytes=FREE)
    assert 'Tagesbericht' in message and '09:00:00 CET' in message


def test_setup_writes_private_config_and_only_starts_telegram(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace
    from deploy import setup_telegram as setup
    config = tmp_path / 'telegram.env'
    (tmp_path / 'manifest.json').write_text('{}')
    calls = []
    token = '123:' + 'test_only_token_' * 3
    monkeypatch.setattr(setup.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(setup.sys, 'stdin', SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(setup.getpass, 'getpass', lambda prompt: token)
    monkeypatch.setattr(setup.secrets, 'token_urlsafe', lambda n: 'nonce')
    monkeypatch.setattr('builtins.input', lambda prompt: '')
    monkeypatch.setattr(setup.subprocess, 'run', lambda args, **kw: calls.append(args))
    def fake_api(token, method, payload):
        if method == 'getMe':
            return {'is_bot': True, 'username': 'example_bot'}
        return [{'message': {'text': '/start nonce', 'chat': {'id': 12345, 'type': 'private'}}}]
    monkeypatch.setattr(setup, 'api', fake_api)
    old_umask = setup.os.umask(0o077)
    try:
        assert setup.main(app=tmp_path, config=config, units=tmp_path, campaign=tmp_path) == 0
    finally:
        setup.os.umask(old_umask)
    assert config.stat().st_mode & 0o777 == 0o600
    assert 'TELEGRAM_CHAT_ID=12345\nTELEGRAM_DAILY_REPORT=1' in config.read_text()
    assert token not in capsys.readouterr().out
    assert ['systemctl', 'start', 'memecoin-telegram.service'] in calls
    assert not any('memecoin-collector.service' in call for call in calls)
    before = config.read_bytes()
    assert setup.main(app=tmp_path, config=config, units=tmp_path, campaign=tmp_path) == 1
    assert config.read_bytes() == before
