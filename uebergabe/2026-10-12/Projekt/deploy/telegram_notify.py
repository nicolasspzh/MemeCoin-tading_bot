"""Optional Telegram health notifications; separate from collection and trading."""
import argparse
from datetime import UTC, datetime
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import sys
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from deploy.status import report
from operations.campaign import status


class TelegramError(Exception):
    pass


def api(token, method, payload):
    if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]{20,}', token):
        raise TelegramError('Ungültiges Tokenformat')
    if method not in {'getMe', 'getUpdates', 'sendMessage'}:
        raise TelegramError('Nicht unterstützte Methode')
    request = Request(f'https://api.telegram.org/bot{token}/{method}',
                      data=json.dumps(payload).encode(),
                      headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urlopen(request, timeout=20) as response:
            value = json.loads(response.read(1024 * 1024))
        if not value.get('ok'):
            raise TelegramError('Telegram hat die Anfrage abgelehnt')
        return value['result']
    except Exception:
        # HTTP exception strings contain the token-bearing URL. Never expose them.
        raise TelegramError('Telegram-Anfrage fehlgeschlagen; Verbindung und Zugang prüfen') from None


def issues(result, now, free_bytes):
    if result.get('status_unavailable'):
        return ['Sammlerstatus kann nicht gelesen werden; Betriebszustand unbekannt'], False
    state, data = result.get('state', {}), result.get('data', {})
    until = result.get('until')
    finished = bool(until and now >= datetime.fromisoformat(until))
    found = []
    if not finished:
        if not result.get('supervisor_running'):
            found.append('Sammler ist nicht aktiv')
        heartbeat = state.get('heartbeat_at')
        if not heartbeat or not 0 <= (now - datetime.fromisoformat(heartbeat)).total_seconds() < 300:
            found.append('Kein aktuelles Lebenszeichen')
        age = data.get('last_quote_age_seconds')
        if age is None or not 0 <= age < 300:
            found.append('Seit mindestens fünf Minuten kein frischer Kurs oder noch kein Kurs vorhanden')
        budget = result.get('rpc_request_budget', {})
        limits = result.get('rpc_budget_limits', {})
        for name, used, limit in [
            ('Tagesbudget', budget.get(now.astimezone(UTC).date().isoformat(), 0), limits.get('rpc_daily_request_limit')),
            ('Gesamtbudget', sum(budget.values()), limits.get('rpc_total_request_limit')),
        ]:
            if limit and used >= .9 * limit:
                found.append(f'{name} der RPC-Anfragen zu mindestens 90 % verbraucht')
    if data.get('orders', 0) or data.get('fills', 0):
        found.append('Unerwartete Orders oder Ausführungen im Beobachtungsmodus')
    if free_bytes < 2 * 1024**3:
        found.append('Weniger als 2 GiB freier Speicher')
    backup = state.get('last_backup')
    if backup and backup.get('integrity') != 'ok':
        found.append('Letzte Sicherung ohne bestätigte Integrität')
    if not finished:
        started = state.get('started_at')
        old_enough = started and (now - datetime.fromisoformat(started)).total_seconds() > 7200
        backup_at = backup.get('at') if backup else None
        if old_enough and (not backup_at or (now - datetime.fromisoformat(backup_at)).total_seconds() > 7200):
            found.append('Seit über zwei Stunden keine aktuelle Sicherung bestätigt')
    return sorted(found), finished


def notification(result, previous, *, now, free_bytes, daily=True):
    current, finished = issues(result, now, free_bytes)
    local = now.astimezone(ZoneInfo('Europe/Zurich'))
    today = local.date().isoformat()
    due_daily = daily and not finished and local.hour >= 9 and previous.get('daily_date') != today
    reasons = []
    if not previous.get('initialized'):
        reasons.append('Telegram verbunden – erster Status')
    elif current != previous.get('issues', []) and not finished:
        reasons.append('Betriebshinweise geändert' if current else 'Gemeldete Betriebsstörungen nicht mehr vorhanden')
    if finished and not previous.get('finished'):
        reasons.append('Geplante Sammelzeit ist abgelaufen – Auswertung kann vorbereitet werden')
    if due_daily:
        reasons.append('Tagesbericht')
    if not reasons:
        return None, previous
    heading = '\n'.join(reasons)
    if current:
        heading += '\n\nBitte prüfen:\n' + '\n'.join(f'• {item}' for item in current)
    summary = ('Keine Aussage zu Kursen oder Prozesszustand möglich. Bitte den Serverstatus prüfen.'
               if result.get('status_unavailable') else
               '\n'.join(line for line in report(result, now=now, free_bytes=free_bytes).splitlines()
                         if not line.startswith('Sammlung: ')))
    message = heading + '\n\n' + summary
    # Fixed plain-text report; avoid Telegram's 4096-character message limit.
    if len(message) > 4000:
        message = message[:3950] + '\n… Weitere Details im Serverstatus.'
    updated = {**previous, 'initialized': True, 'issues': current, 'finished': finished,
               'last_sent_at': now.isoformat()}
    if due_daily:
        updated['daily_date'] = today
    return message, updated


def run(directory, state_path, token, chat_id, *, daily=True, now=None, send=api):
    if not re.fullmatch(r'[1-9][0-9]*', chat_id):
        raise ValueError('Private Telegram-Chat-ID erforderlich')
    if not (directory / 'manifest.json').is_file():
        result = {'directory': str(directory), 'status_unavailable': True}
    else:
        try:
            result = status(directory)
        except Exception:
            # A broken collector DB must not silently disable its alert monitor.
            result = {'directory': str(directory), 'status_unavailable': True}
    free = shutil.disk_usage(directory if directory.exists() else directory.parent).free
    previous = json.loads(state_path.read_text()) if state_path.exists() else {}
    message, updated = notification(result, previous, now=now or datetime.now(UTC), free_bytes=free, daily=daily)
    if message is None:
        return False
    response = send(token, 'sendMessage', {'chat_id': chat_id, 'text': message})
    if str(response.get('chat', {}).get('id')) != chat_id:
        raise TelegramError('Versand nicht für den konfigurierten Chat bestätigt')
    # Persist only after Telegram acknowledges delivery. Failed sends retry next tick.
    temporary = state_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(updated))
    temporary.replace(state_path)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path('/var/lib/memecoin-collector/campaign-r2'))
    parser.add_argument('--state', type=Path, default=Path('/var/lib/memecoin-notifier/state.json'))
    args = parser.parse_args(argv)
    try:
        os.umask(0o077)
        args.state.parent.mkdir(parents=True, exist_ok=True)
        with args.state.with_suffix('.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return 0
            sent = run(args.directory, args.state, os.environ['TELEGRAM_BOT_TOKEN'],
                       os.environ['TELEGRAM_CHAT_ID'], daily=os.environ.get('TELEGRAM_DAILY_REPORT', '1') == '1')
        print('Telegram-Nachricht bestätigt.' if sent else 'Keine neue Meldung erforderlich.')
        return 0
    except Exception as error:
        print(f'Telegram-Status nicht übermittelt ({type(error).__name__}); nächster Versuch beim Timerlauf.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
