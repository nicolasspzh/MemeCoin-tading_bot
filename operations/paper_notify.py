"""Read-only Paper Telegram monitor. Preview by default; delivery is explicit."""
import argparse
from datetime import UTC, datetime, time as day_time, timedelta
from decimal import Decimal
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import time
import unicodedata
from zoneinfo import ZoneInfo

from backtesting.evaluation import digest
from config.settings import Settings
from deploy.telegram_notify import api, TelegramError
from operations.campaign import atomic_json
from operations.paper_service import Reader, load_manifest, read_status
from trading.engine import Engine

ZONE = ZoneInfo('Europe/Zurich')
MAX_EVENTS = 5
HEADER = 'PAPER – NUR VIRTUELLES GELD'
STATES = {'initialized': 'noch nicht gestartet', 'running': 'läuft',
          'source_exhausted': 'Testkursfolge beendet', 'scheduled_end': 'planmäßig beendet',
          'stopped_by_request': 'manuell gestoppt', 'service_error': 'Dienstfehler',
          'failure_limit': 'nach wiederholten Fehlern gestoppt', 'disk_space_low': 'wegen Speicherknappheit gestoppt'}


def label(value, limit=70):
    # Token labels can be provider-controlled. Plain text, bounded, no controls.
    value = ''.join(c for c in str(value) if unicodedata.category(c)[0] != 'C')
    value = ' '.join(value.split()).replace('://', ': / /').replace('@', '(at)')
    return value[:limit]


def money(value, places=2):
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError('Invalid monetary amount')
    return f'{number:.{places}f} USD'


def local_time(value):
    return datetime.fromisoformat(value).astimezone(ZONE).strftime('%d.%m.%Y %H:%M:%S %Z')


def amount(value):
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError('Invalid amount')
    return format(number, '.10g')


def yesterday(now):
    date = now.astimezone(ZONE).date()
    start = datetime.combine(date - timedelta(days=1), day_time(), ZONE)
    end = datetime.combine(date, day_time(), ZONE)
    return start, end


def event_hash(row):
    return digest(dict(row))


EVENT_SQL = '''SELECT l.id, l.payload AS ledger, o.payload AS orders,
    (SELECT f.payload FROM fills f WHERE f.snapshot_id=l.snapshot_id
      AND json_extract(f.payload,'$.order_id')=l.order_id LIMIT 1) AS fill
    FROM paper_ledger l JOIN paper_orders o ON o.id=l.order_id'''


def snapshot(directory, previous, now):
    manifest = load_manifest(directory)
    fingerprint = digest(manifest)
    if previous.get('manifest') not in (None, fingerprint):
        raise ValueError('Paper run changed; dedicated notification state required')
    result = read_status(directory)
    result.update(manifest=fingerprint, events=[], positions=[], previous_day=None)
    result['rpc_limits'] = {key: manifest['settings'][key] for key in ('rpc_daily_request_limit', 'rpc_total_request_limit')}
    path = directory / 'paper.sqlite3'
    cursor = previous.get('cursor', 0)
    if not path.exists():
        if cursor:
            raise ValueError('Previously reported database missing')
        return result
    reader = Reader(path, 'demo' if manifest['source'] == 'demo' else 'dexscreener')
    try:
        marker = reader.conn.execute("SELECT value FROM metadata WHERE key='paper_service_manifest'").fetchone()
        if marker is None or marker[0] != fingerprint:
            raise ValueError('Paper database identity mismatch')
        if cursor:
            anchor = reader.conn.execute(EVENT_SQL + ' WHERE l.id=?', (cursor,)).fetchone()
            if anchor is None or event_hash(anchor) != previous.get('cursor_hash'):
                raise ValueError('Previously reported history changed or was restored')
        result['paper'] = Engine.stored_summary(reader, Settings.model_validate(manifest['settings']))
        result['last_price_at'] = reader.conn.execute('SELECT max(received_at) FROM snapshots WHERE price IS NOT NULL').fetchone()[0]
        wallet = reader.load_wallet()
        result['positions'] = [p.model_dump(mode='json') for _, p in sorted(wallet.positions.items())]
        rows = reader.conn.execute(EVENT_SQL + ' WHERE l.id>? ORDER BY l.id LIMIT ?', (cursor, MAX_EVENTS)).fetchall()
        result['events'] = [dict(row) for row in rows]
        start, end = yesterday(now)
        pnl, buys, sells, failed = Decimal(0), 0, 0, 0
        for row in reader.conn.execute(EVENT_SQL + ' ORDER BY l.id'):
            entry, order = json.loads(row['ledger']), json.loads(row['orders'])
            if start <= datetime.fromisoformat(entry['at']) < end:
                pnl += Decimal(entry['realized_pnl_delta'])
                if entry['status'] == 'filled':
                    buys += order['action'] == 'BUY'
                    sells += order['action'] == 'SELL'
                else:
                    failed += 1
        result['previous_day'] = {'date': start.date().isoformat(), 'realized_net': str(pnl),
                                  'buys': buys, 'sells': sells, 'unfilled': failed}
    finally:
        reader.close()
    return result


def alerts(value, now, free):
    if value.get('unavailable'):
        return ['Paper-Daten nicht zuverlässig lesbar oder Historie geändert; keine Trade-Meldungen möglich.']
    state, paper = value['state'], value.get('paper', {})
    running = value['process_running']
    expected_stop = state['status'] in {'scheduled_end', 'stopped_by_request', 'source_exhausted'}
    found = []
    if not running and not expected_stop:
        found.append('Paper-Dienst ist nicht aktiv.')
    if state['status'] in {'service_error', 'failure_limit', 'disk_space_low'}:
        found.append('Paper-Dienst hat einen Betriebsfehler gemeldet.')
    if running:
        heartbeat = state.get('heartbeat_at')
        if heartbeat is None or not 0 <= (now - datetime.fromisoformat(heartbeat)).total_seconds() <= 120:
            found.append('Kein aktuelles Lebenszeichen des Paper-Dienstes.')
        if now >= datetime.fromisoformat(value['until']):
            found.append('Paper-Prozess läuft über sein geplantes Ende hinaus.')
        quote = value.get('last_price_at')
        if value['source'] == 'market' and (quote is None or not 0 <= now.timestamp() - quote < 120):
            found.append('Keine bestätigten frischen Marktpreise.')
    if paper and not paper['accounting']['balanced']:
        found.append('Buchhaltungsfehler: virtuelle Wallet und Buchungen stimmen nicht überein.')
    if paper.get('status') == 'DEAD':
        found.append('Virtuelle Wallet ist gesperrt (DEAD).')
    if not running and (paper.get('open_positions') or paper.get('pending_orders')):
        found.append('Gestoppter Dienst hat offene Positionen oder ausstehende Orders; keine erfundene Liquidation.')
    if paper.get('valuation_warnings'):
        found.append('Offene Positionen haben unsichere Bewertungen.')
    backup = state.get('last_backup')
    if state.get('backup_error_type') or (backup and backup.get('integrity') != 'ok'):
        found.append('Sicherung fehlgeschlagen oder Integrität unbestätigt.')
    if running:
        started = state.get('started_at')
        if started and (now - datetime.fromisoformat(started)).total_seconds() > 7200:
            if not backup or (now - datetime.fromisoformat(backup['at'])).total_seconds() > 7200:
                found.append('Seit über zwei Stunden keine aktuelle Sicherung bestätigt.')
    if free < 2 * 1024**3:
        found.append('Weniger als 2 GiB freier Speicher.')
    requests, limits = value.get('rpc_requests_by_day', {}), value.get('rpc_limits', {})
    for name, used, limit in (
        ('UTC-Tagesbudget', requests.get(now.astimezone(UTC).date().isoformat(), 0), limits.get('rpc_daily_request_limit')),
        ('Gesamtbudget', sum(requests.values()), limits.get('rpc_total_request_limit')),
    ):
        if running and limit and used >= .9 * limit:
            found.append(f'RPC-{name} ist zu mindestens 90 % verbraucht; Anfragen sind keine Helius-Credits.')
    return sorted(found)


def summary(value):
    if value.get('unavailable'):
        return 'Betriebszustand und virtuelle Kontostände sind nicht bestätigt. Bitte Serverstatus prüfen.'
    state, paper = value['state'], value.get('paper', {})
    lines = ['Daten: ' + ('KÜNSTLICHE TESTKURSE' if value['source'] == 'demo' else 'Marktbeobachtungen'),
             'Prozess: ' + ('aktiv' if value['process_running'] else 'nicht aktiv'),
             f"Betriebszustand: {STATES.get(state['status'], 'unbekannt')}", f"Geplantes Ende: {local_time(value['until'])}"]
    if paper:
        lines += [f"Virtuelles Cash: {paper['cash_usd']} USD",
                  f"Davon reserviert: {money(paper['reserved_cash_usd'])}; verfügbar: {money(paper['available_cash_usd'])}",
                  f"Geschätztes Handelsvermögen: {paper['estimated_trading_equity_usd']} USD (kein garantierter Verkaufserlös)",
                  f"Virtuelle News-Reserve: {paper['news_reserve_usd']} USD; Eigentümeranteil: {paper['owner_profit_usd']} USD",
                  f"Realisiertes Nettoergebnis seit Start: {paper['realized_pnl_usd']} USD (simulierte Kosten berücksichtigt)",
                  f"Offene Positionen: {paper['open_positions']}; ausstehende Orders: {paper['pending_orders']}",
                  'Buchhaltung: ' + ('stimmig' if paper['accounting']['balanced'] else 'FEHLER')]
    for position in value.get('positions', [])[:5]:
        lines.append(f"• {label(position['token'])}: Menge {amount(position['quantity'])}, "
                     f"Einstandskosten {money(position['entry_cost'])}; offen seit {local_time(position['opened_at'])}")
    if len(value.get('positions', [])) > 5:
        lines.append('Weitere offene Positionen stehen im Serverstatus.')
    day = value.get('previous_day')
    if day:
        lines += [f"Vollständiger Vortag {day['date']} (Schweizer Zeit):",
                  f"{day['buys']} simulierte Käufe, {day['sells']} simulierte Verkäufe, {day['unfilled']} Orders ohne Ausführung; "
                  f"realisiertes Nettoergebnis {money(day['realized_net'])}."]
    return '\n'.join(lines)


def event_message(event, source):
    order, entry = json.loads(event['orders']), json.loads(event['ledger'])
    filled = entry['status'] == 'filled'
    side = {'BUY': 'KAUF', 'SELL': 'VERKAUF'}[order['action']]
    title = f'SIMULIERTER {side}' if filled else f'PAPER-ORDER OHNE AUSFÜHRUNG ({side})'
    lines = [HEADER, 'KÜNSTLICHE TESTKURSE' if source == 'demo' else 'Marktbeobachtungen, simulierte Ausführung',
             title, f"Order #{order['id']} · Ereigniszeit: {local_time(entry['at'])}",
             f"Token: {label(order['token'])}", f"Pool: {label(order['pair'])}"]
    if filled:
        if not event['fill']:
            raise ValueError('Filled order has no execution evidence')
        fill = json.loads(event['fill'])
        lines += [f"Menge: {amount(fill['quantity'])}", f"Simulierter Ausführungspreis: {amount(fill['price'])} USD",
                  f"Cash-Veränderung: {money(fill['cash_flow'])}", f"Simulierte Gebühren: {money(fill['fee'], 4)}"]
        if side == 'VERKAUF':
            lines.append('Realisiertes Nettoergebnis dieses Trades: ' + money(fill.get('net_trade_pnl', fill['realized_pnl'])))
    else:
        states = {'failed': 'fehlgeschlagen', 'rejected': 'abgelehnt', 'expired': 'verfallen', 'cancelled': 'storniert'}
        lines += [f"Status: {states[entry['status']]}", f"Simulierte Kosten: {money(entry['fee_usd'], 4)}"]
    lines.append('Gespeichertes Ereignis; Zustellung kann nachgeholt sein. Keine echte Transaktion.')
    return '\n'.join(lines)


def build_report(value, previous, now, free, daily):
    current = alerts(value, now, free)
    date = now.astimezone(ZONE).date().isoformat()
    daily_due = daily and now.astimezone(ZONE).hour >= 9 and previous.get('daily_date') != date
    lifecycle = value.get('state', {}).get('status', 'unavailable')
    reasons = []
    if not previous.get('initialized'):
        reasons.append('Paper-Benachrichtigungen – erster Status')
    elif current != previous.get('alerts', []):
        reasons.append('Paper-Betriebshinweise geändert' if current else 'Zuvor gemeldete Paper-Störungen nicht mehr vorhanden')
    if previous.get('initialized') and lifecycle != previous.get('lifecycle'):
        reasons.append('Paper-Betriebszustand geändert')
    if daily_due:
        reasons.append('Paper-Tagesbericht')
    if not reasons:
        return None, previous
    message = HEADER + '\n' + '\n'.join(reasons) + '\nStand: ' + local_time(now.isoformat())
    if current:
        message += '\n\nBitte prüfen:\n' + '\n'.join('• ' + item for item in current)
    message += '\n\n' + summary(value)
    updated = {**previous, 'initialized': True, 'alerts': current, 'lifecycle': lifecycle}
    if daily_due:
        updated['daily_date'] = date
    return message, updated


def bounded_message(message):
    # Telegram counts UTF-16 code units; astral characters use two units.
    if len(message.encode('utf-16-le')) // 2 > 3900:
        message = message.encode('utf-16-le')[:7400].decode('utf-16-le', errors='ignore') + '\n… Weitere Details im Paper-Status.'
    return message


def run_once(directory, state_path, *, token=None, chat_id=None, send=api, deliver=False,
             now=None, daily=True, pause=time.sleep):
    now = now or datetime.now(UTC)
    directory, state_path = directory.resolve(), state_path.resolve()
    if state_path.is_relative_to(directory):
        raise ValueError('Notification state must be outside the Paper data directory')
    if deliver and (not token or not chat_id or not re.fullmatch(r'[1-9][0-9]*', chat_id)):
        raise ValueError('Configured bot and private chat required')
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.with_suffix('.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return []
        previous = json.loads(state_path.read_text()) if state_path.exists() else {}
        if previous and (previous.get('directory') != str(directory) or (deliver and previous.get('chat_id') != chat_id)):
            raise ValueError('Notifier state belongs to another run or recipient')
        previous = {**previous, 'directory': str(directory), 'chat_id': chat_id or previous.get('chat_id')}
        try:
            value = snapshot(directory, previous, now)
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
            value = {'unavailable': True}
        free = shutil.disk_usage(directory if directory.exists() else directory.parent).free
        message, updated = build_report(value, previous, now, free, daily)
        messages = []
        def dispatch(text, state):
            text = bounded_message(text)
            if deliver:
                if messages:
                    pause(1.1)
                response = send(token, 'sendMessage', {'chat_id': chat_id, 'text': text,
                                                      'link_preview_options': {'is_disabled': True}})
                if str(response.get('chat', {}).get('id')) != chat_id or not response.get('message_id'):
                    raise TelegramError('Delivery not confirmed for configured chat')
                atomic_json(state_path, {**state, 'last_sent_at': now.isoformat()})
            messages.append(text)
        if not value.get('unavailable'):
            updated['manifest'] = value['manifest']
        if message:
            dispatch(message, updated)
            previous = updated
        if not value.get('unavailable') and value.get('paper', {}).get('accounting', {}).get('balanced'):
            for event in value['events']:
                updated = {**previous, 'manifest': value['manifest'], 'cursor': event['id'], 'cursor_hash': event_hash(event)}
                dispatch(event_message(event, value['source']), updated)
                previous = updated
        return messages


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--state', type=Path, default=Path('/var/lib/memecoin-paper-notifier/state.json'))
    parser.add_argument('--send', action='store_true', help='Deliver to the configured private Telegram chat')
    args = parser.parse_args(argv)
    try:
        os.umask(0o077)
        messages = run_once(args.directory, args.state, token=os.environ.get('TELEGRAM_BOT_TOKEN'),
                            chat_id=os.environ.get('TELEGRAM_CHAT_ID'), deliver=args.send,
                            daily=os.environ.get('TELEGRAM_DAILY_REPORT', '1') == '1')
        if args.send:
            print(f'{len(messages)} Paper-Nachrichten bestätigt.')
        else:
            print('VORSCHAU – KEIN VERSAND\n\n' + '\n\n'.join(messages))
        return 0
    except Exception as error:
        print(f'Paper-Benachrichtigung nicht abgeschlossen ({type(error).__name__}); Details ohne Zugangsdaten prüfen.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
