"""German, read-only collection health summary; no provider requests or returns."""
import argparse
from datetime import UTC, datetime
from pathlib import Path
import shutil
import sqlite3
import sys
from zoneinfo import ZoneInfo

from operations.campaign import status


def number(value):
    return f"{value:,}".replace(',', "'")


def local_time(value):
    if not value:
        return 'unbekannt'
    return datetime.fromisoformat(value).astimezone(ZoneInfo('Europe/Zurich')).strftime('%d.%m.%Y %H:%M:%S %Z')


def report(result, *, now=None, free_bytes=None):
    now = now or datetime.now(UTC)
    state, data = result.get('state', {}), result.get('data', {})
    until = result.get('until')
    ended = bool(until and now >= datetime.fromisoformat(until))
    running = result.get('supervisor_running', False)
    process = 'aktiv' if running else ('beendet; Sammelzeit abgelaufen' if ended else 'NICHT AKTIV')
    lines = ['MEMECOIN – SAMMELSTATUS', f"Stand: {local_time(now.isoformat())}",
             f"Sammlung: {result['directory']}", f"Sammler-Prozess: {process}",
             f"Geplantes Sammelende: {local_time(until)}"]
    if result.get('stop_requested'):
        lines.append('Hinweis: Ein Stopp wurde angefordert.')
    heartbeat = state.get('heartbeat_at')
    if running:
        age = (now - datetime.fromisoformat(heartbeat)).total_seconds() if heartbeat else None
        lines.append('Lebenszeichen: ' + ('unbekannt' if age is None else
                     f'vor {age:.0f} Sekunden' + (' – BITTE PRÜFEN' if age < 0 or age > 120 else '')))
    if not data:
        lines.append('Datenbank: noch nicht vorhanden; keine Datensammlung bestätigt.')
    else:
        total, priced = data['snapshots'], data['priced_snapshots']
        fraction = f'{100 * priced / total:.1f} %' if total else 'noch keine'
        lines += [f"Beobachtungen: {number(total)}; Coins mit Beobachtungen: {number(data['tokens'])}",
                  f"Mit Kurs: {number(priced)} ({fraction}); ohne Kurs: {number(total - priced)}"]
        age = data.get('last_quote_age_seconds')
        fresh = age is not None and 0 <= age < 120
        lines.append('Letzter Kurs: ' + ('keiner' if age is None else f'vor {age:.0f} Sekunden') +
                     (' – BITTE PRÜFEN' if not fresh and not ended else ''))
        lines.append(f"Orders: {number(data['orders'])}; Ausführungen: {number(data['fills'])}" +
                     (' – UNERWARTET: Beobachtungsmodus prüfen!' if data['orders'] or data['fills'] else ' (reine Beobachtung)'))
        lines.append('Folgekurse: belegt / bereits fällig')
        for row in data.get('outcomes', []):
            due, observed = row['due'], row['observed']
            label = f"{row['horizon_seconds']} s"
            ratio = f'{100 * observed / due:.1f} %' if due else 'noch nicht fällig'
            lines.append(f"  {label}: {number(observed)} / {number(due)} ({ratio})")
        lines.append('  Unbelegte fällige Kurse können noch im erlaubten Zeitspielraum eintreffen.')
        lines.append('  Diese Zahlen bewerten Datenabdeckung, nicht Gewinn oder Handelsreife.')
    if state.get('data_degraded'):
        lines.append('Qualitätsflag: data_degraded=true; die Ursache ist aus diesem Flag allein nicht ersichtlich.')
    tracks = result.get('observation_tracks')
    if tracks is not None:
        lines.append(f"Beobachtungsgruppen: {tracks.get('primary', 0)} Anfangsphase, "
                     f"{tracks.get('followup', 0)} Nachbeobachtung, {tracks.get('completed', 0)} abgeschlossen")
    budget, limits = result.get('rpc_request_budget'), result.get('rpc_budget_limits', {})
    if budget is not None:
        today = budget.get(now.astimezone(UTC).date().isoformat(), 0)
        for label, used, limit in [('Heute (UTC)', today, limits.get('rpc_daily_request_limit')),
                                   ('Gesamte Sammlung', sum(budget.values()), limits.get('rpc_total_request_limit'))]:
            text = f'RPC-Anfragen – {label}: {number(used)}'
            if limit is not None:
                text += f' / {number(limit)}; verbleibend {number(max(0, limit - used))}'
                if used >= limit:
                    text += ' – LIMIT ERREICHT; neue RPC-Prüfungen blockiert'
            else:
                text += '; Limit unbekannt'
            lines.append(text)
    else:
        lines.append('Dauerhaftes RPC-Anfragebudget: in dieser Sammlung nicht verfügbar.')
    lines.append('Helius-Credits: hier nicht abrufbar; Anfragen sind keine Credits. Im Helius-Dashboard prüfen.')
    backup = state.get('last_backup')
    if backup:
        lines.append(f"Letzte Sicherung: {local_time(backup.get('at'))}; "
                     f"Integritätsprüfung: {backup.get('integrity', 'unbekannt')}")
    else:
        lines.append('Sicherung: noch keine bestätigt.')
    if free_bytes is not None:
        lines.append(f'Freier Speicher am Datenverzeichnis: {free_bytes / 1024**3:.1f} GiB' +
                     (' – KNAPP (unter 2 GiB)' if free_bytes < 2 * 1024**3 else ''))
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path('/var/lib/memecoin-collector/campaign-r2'))
    args = parser.parse_args(argv)
    directory = args.directory.resolve()
    if not (directory / 'manifest.json').is_file():
        print('Keine initialisierte Sammlung an diesem Pfad. Verzeichnis prüfen.', file=sys.stderr)
        return 2
    try:
        result = status(directory)
        print(report(result, free_bytes=shutil.disk_usage(directory).free), end='')
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        # Never print arbitrary exception details that might include private data.
        print(f'Status konnte nicht gelesen werden ({type(error).__name__}).', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
