from datetime import UTC, datetime, timedelta
import fcntl
import json
from pathlib import Path
import sqlite3

import pytest

from backtesting.evaluation import digest
from collectors.demo import demo_snapshots
from config.settings import Settings
from data.database import Database
from deploy.telegram_notify import TelegramError
from operations import paper_notify as notify
from operations.paper_service import initialize
from trading.engine import Engine

NOW = datetime(2026, 10, 9, 7, tzinfo=UTC)


def prepare(tmp_path, count=18):
    directory = tmp_path / 'paper'
    manifest = initialize(directory, now=NOW, duration=3600)
    db = Database(directory / 'paper.sqlite3', 'demo')
    with db.conn:
        db.conn.execute("INSERT INTO metadata VALUES('paper_service_manifest',?)", (digest(manifest),))
    engine = Engine(db, Settings())
    for quote in list(demo_snapshots())[:count]:
        engine.process(quote, quote.received_at)
    db.close()
    (directory / 'state.json').write_text(json.dumps({'status': 'source_exhausted'}))
    return directory, tmp_path / 'notifier/state.json'


def call(directory, state, send, **kwargs):
    return notify.run_once(directory, state, token='TEST_ONLY', chat_id='123', send=send,
                           deliver=True, now=kwargs.pop('now', NOW), pause=lambda _: None, **kwargs)


def accepted(token, method, payload):
    assert method == 'sendMessage' and payload['chat_id'] == '123'
    assert payload['link_preview_options']['is_disabled']
    return {'chat': {'id': 123}, 'message_id': 12}


def test_buy_sell_report_and_restart_do_not_duplicate_or_modify_wallet(tmp_path):
    directory, state = prepare(tmp_path)
    before = (directory / 'paper.sqlite3').read_bytes()
    messages = call(directory, state, accepted)
    assert len(messages) == 3
    assert 'Paper-Tagesbericht' in messages[0]
    assert 'SIMULIERTER KAUF' in messages[1]
    assert 'SIMULIERTER VERKAUF' in messages[2]
    assert 'Realisiertes Nettoergebnis dieses Trades' in messages[2]
    assert all('NUR VIRTUELLES GELD' in message for message in messages)
    assert call(directory, state, accepted) == []
    assert json.loads(state.read_text())['cursor'] == 2
    assert (directory / 'paper.sqlite3').read_bytes() == before


def test_partial_delivery_failure_retries_only_unacknowledged_event(tmp_path):
    directory, state = prepare(tmp_path)
    sent = []
    def fail_third(token, method, payload):
        sent.append(payload['text'])
        if len(sent) == 3:
            raise TelegramError('simulated network failure')
        return accepted(token, method, payload)
    with pytest.raises(TelegramError):
        call(directory, state, fail_third)
    assert json.loads(state.read_text())['cursor'] == 1
    retry = call(directory, state, accepted)
    assert len(retry) == 1 and 'SIMULIERTER VERKAUF' in retry[0]


def test_wrong_recipient_ack_does_not_advance_delivery(tmp_path):
    directory, state = prepare(tmp_path)
    with pytest.raises(TelegramError):
        call(directory, state, lambda *_: {'chat': {'id': 456}, 'message_id': 1})
    assert not state.exists()
    call(directory, state, accepted)
    with pytest.raises(ValueError, match='another run or recipient'):
        notify.run_once(directory, state, token='TEST_ONLY', chat_id='456', deliver=True, send=accepted, now=NOW)


def test_preview_never_sends_or_advances_cursor(tmp_path):
    directory, state = prepare(tmp_path)
    def forbidden(*args):
        pytest.fail('Preview attempted network')
    assert len(notify.run_once(directory, state, send=forbidden, now=NOW)) == 3
    assert not state.exists()
    assert len(call(directory, state, accepted)) == 3
    before = state.read_bytes()
    notify.run_once(directory, state, send=forbidden, now=NOW)
    assert state.read_bytes() == before


def test_restored_or_rewritten_history_is_not_silently_skipped(tmp_path):
    directory, state = prepare(tmp_path)
    call(directory, state, accepted)
    with sqlite3.connect(directory / 'paper.sqlite3') as db:
        db.execute('DELETE FROM paper_ledger WHERE id=2')
    messages = call(directory, state, accepted)
    assert len(messages) == 1 and 'Historie geändert' in messages[0]
    assert 'SIMULIERTER VERKAUF' not in messages[0]
    assert json.loads(state.read_text())['cursor'] == 2
    assert call(directory, state, accepted) == []


def test_accounting_failure_blocks_trade_announcements(tmp_path):
    directory, state = prepare(tmp_path)
    with sqlite3.connect(directory / 'paper.sqlite3') as db:
        wallet = json.loads(db.execute('SELECT payload FROM wallet').fetchone()[0])
        wallet['cash'] = '999'
        db.execute('UPDATE wallet SET payload=?', (json.dumps(wallet),))
    messages = call(directory, state, accepted)
    assert len(messages) == 1 and 'Buchhaltungsfehler' in messages[0]
    assert 'cursor' not in json.loads(state.read_text())


def test_open_positions_are_named_and_not_claimed_closed_at_stop(tmp_path):
    directory, state = prepare(tmp_path, count=5)
    messages = call(directory, state, accepted)
    assert 'Offene Positionen: 1' in messages[0]
    assert 'DEMO_MOMENTUM' in messages[0]
    assert 'keine erfundene Liquidation' in messages[0]
    assert len(messages) == 2 and 'SIMULIERTER KAUF' in messages[1]


def test_expired_order_is_not_announced_as_purchase(tmp_path):
    directory, state = prepare(tmp_path, count=3)
    db = Database(directory / 'paper.sqlite3', 'demo')
    engine = Engine(db, Settings())
    engine.tick(list(demo_snapshots())[2].received_at + timedelta(minutes=5))
    db.close()
    messages = call(directory, state, accepted)
    assert len(messages) == 2
    assert 'ORDER OHNE AUSFÜHRUNG (KAUF)' in messages[1]
    assert 'verfallen' in messages[1] and 'SIMULIERTER KAUF' not in messages[1]


def test_daily_time_and_previous_day_use_swiss_calendar_with_dst(tmp_path):
    directory, state = prepare(tmp_path)
    initial = datetime(2026, 10, 9, 6, 55, tzinfo=UTC)
    messages = call(directory, state, accepted, now=initial)
    assert 'Paper-Tagesbericht' not in messages[0]
    messages = call(directory, state, accepted)
    assert len(messages) == 1 and 'Paper-Tagesbericht' in messages[0]
    assert 'Vollständiger Vortag 2026-10-08' in messages[0]
    assert call(directory, state, accepted) == []
    spring = datetime(2026, 3, 30, 7, tzinfo=UTC)
    autumn = datetime(2026, 10, 26, 8, tzinfo=UTC)
    for now, hours in ((spring, 23), (autumn, 25)):
        start, end = notify.yesterday(now)
        assert (end.astimezone(UTC) - start.astimezone(UTC)).total_seconds() == hours * 3600


def test_previous_day_net_is_sum_of_ledger_changes_not_wallet_equity(tmp_path):
    directory, _ = prepare(tmp_path)
    view = notify.snapshot(directory, {}, datetime(2026, 1, 2, 8, tzinfo=UTC))
    day = view['previous_day']
    assert day['buys'] == 1 and day['sells'] == 1
    assert day['date'] == '2026-01-01'
    assert 0 < float(day['realized_net']) < 1
    assert float(day['realized_net']) != float(view['paper']['cash_usd'])


def test_fault_recovery_and_planned_stop_do_not_produce_false_crash_alarm(tmp_path):
    directory, state = prepare(tmp_path)
    call(directory, state, accepted)
    state_file = directory / 'state.json'
    state_file.write_text(json.dumps({'status': 'failure_limit'}))
    assert 'Betriebsfehler' in call(directory, state, accepted)[0]
    assert call(directory, state, accepted) == []
    state_file.write_text(json.dumps({'status': 'scheduled_end'}))
    text = call(directory, state, accepted)[0]
    assert 'Störungen nicht mehr vorhanden' in text
    assert 'Paper-Dienst ist nicht aktiv.' not in text


def test_concurrent_notifier_leaves_cursor_and_messages_untouched(tmp_path):
    directory, state = prepare(tmp_path)
    state.parent.mkdir()
    with state.with_suffix('.lock').open('a') as fd:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert call(directory, state, accepted) == []
    assert not state.exists()


def test_bounded_backlog_keeps_unsent_events_for_next_run(tmp_path, monkeypatch):
    directory, state = prepare(tmp_path)
    monkeypatch.setattr(notify, 'MAX_EVENTS', 1)
    messages = call(directory, state, accepted)
    assert len(messages) == 2 and json.loads(state.read_text())['cursor'] == 1
    assert len(call(directory, state, accepted)) == 1
    assert json.loads(state.read_text())['cursor'] == 2


def test_unicode_limits_and_private_error_output(tmp_path, capsys, monkeypatch):
    directory, state = prepare(tmp_path)
    assert len(notify.bounded_message('😀' * 5000).encode('utf-16-le')) // 2 < 4096
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'TOP-SECRET')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '123')
    def fail(*args, **kwargs):
        raise OSError('TOP-SECRET in external URL')
    monkeypatch.setattr(notify, 'run_once', fail)
    assert notify.main(['--directory', str(directory), '--state', str(state), '--send']) == 1
    assert 'TOP-SECRET' not in capsys.readouterr().err


@pytest.mark.parametrize('status', ['failed', 'rejected', 'cancelled'])
def test_unsuccessful_orders_show_costs_but_never_a_fill(status):
    event = {'ledger': json.dumps({'at': NOW.isoformat(), 'status': status, 'fee_usd': '.025'}),
             'orders': json.dumps({'action': 'SELL', 'id': 7, 'token': 'DEMO', 'pair': 'POOL'}), 'fill': None}
    text = notify.event_message(event, 'demo')
    assert 'ORDER OHNE AUSFÜHRUNG' in text
    assert 'Simulierte Kosten: 0.0250 USD' in text
    assert 'SIMULIERTER VERKAUF' not in text


def test_state_cannot_be_written_into_paper_data_directory(tmp_path):
    directory, _ = prepare(tmp_path)
    with pytest.raises(ValueError, match='outside'):
        notify.run_once(directory, directory / 'notifier.json', now=NOW)
    assert not (directory / 'notifier.json').exists()


def test_unreadable_status_then_recovery_does_not_drop_event_backlog(tmp_path):
    directory, state = prepare(tmp_path)
    path = directory / 'manifest.json'
    original = path.read_bytes()
    path.write_text('broken json')
    messages = call(directory, state, accepted)
    assert len(messages) == 1 and 'nicht bestätigt' in messages[0]
    assert 'cursor' not in json.loads(state.read_text())
    path.write_bytes(original)
    messages = call(directory, state, accepted)
    assert len(messages) == 3
    assert 'Störungen nicht mehr vorhanden' in messages[0]


def test_same_ledger_id_with_changed_content_requires_review(tmp_path):
    directory, state = prepare(tmp_path)
    call(directory, state, accepted)
    with sqlite3.connect(directory / 'paper.sqlite3') as db:
        entry = json.loads(db.execute('SELECT payload FROM paper_ledger WHERE id=2').fetchone()[0])
        entry['at'] = (NOW - timedelta(days=1)).isoformat()
        db.execute('UPDATE paper_ledger SET payload=? WHERE id=2', (json.dumps(entry),))
    text = call(directory, state, accepted)[0]
    assert 'Historie geändert' in text
    assert 'cursor_hash' in json.loads(state.read_text())
