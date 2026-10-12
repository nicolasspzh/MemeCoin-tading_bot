"""Finite, restartable Paper service; demo by default, market requires reviewed evidence."""
import argparse
import asyncio
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import sys
from zoneinfo import ZoneInfo

from backtesting.evaluation import EXCLUDED_SETTINGS, code_digest, digest, load_protocol, utc
from collectors.demo import demo_snapshots
from config.settings import Settings, load_settings
from data.database import Database
from data.models import utcnow
from main import single_writer
from operations.campaign import atomic_json
from operations.paper_feed import MarketFeed
from trading.engine import Engine

ROOT = Path(__file__).resolve().parents[1]
TERMINAL = {'scheduled_end', 'stopped_by_request', 'source_exhausted', 'failure_limit', 'disk_space_low'}


def service_digest():
    return digest({name: hashlib.sha256((ROOT / 'operations' / name).read_bytes()).hexdigest()
                   for name in ('paper_service.py', 'paper_feed.py')})


def reviewed_settings(protocol, evaluation, now):
    envelope = load_protocol(protocol)
    plan = envelope['plan']
    # No prospective report is even opened during the independent collection window.
    if now < utc(plan['test_end_exclusive_utc']) + timedelta(seconds=3960):
        raise ValueError('Phase 6 collection and follow-up have not ended')
    result = json.loads(evaluation.read_text())
    assessment = result.get('assessment', {})
    if (result.get('kind') != 'PROSPECTIVE_WINDOW_EVALUATION' or result.get('prospective') is not True
            or result.get('protocol_sha256') != envelope['sha256'] or result.get('code_sha256') != code_digest()
            or assessment.get('status') != 'REVIEWABLE_HOLDOUT' or assessment.get('eligible_for_review') is not True
            or assessment.get('blockers') != [] or result.get('inputs', {}).get('source') != 'dexscreener'
            or result.get('scenario_definitions') != plan['scenario_definitions']):
        raise ValueError('Matching reviewable Phase 6 evidence required')
    return Settings.model_validate(plan['scenario_definitions']['baseline']['settings']), {
        'protocol_sha256': envelope['sha256'], 'evaluation_file_sha256': hashlib.sha256(evaluation.read_bytes()).hexdigest(),
        'meaning': 'Operator supplied reviewed report; local hashes are not signed attestation or profit approval'}


def initialize(directory, *, source='demo', duration=60, protocol=None, evaluation=None, now=None):
    now = now or utcnow()
    if source not in {'demo', 'market'} or not 1 <= duration <= 86400:
        raise ValueError('Choose demo/market and a duration of 1 to 86400 seconds')
    settings, evidence = Settings(), None
    if source == 'market':
        if protocol is None or evaluation is None:
            raise ValueError('Explicit --protocol and --reviewed-evaluation required for market mode')
        settings, evidence = reviewed_settings(protocol, evaluation, now)
    settings = Settings.model_validate(settings.model_copy(update={
        'observation_cohorts': False, 'max_watch_tokens': 8, 'discovery_poll_seconds': 120,
        'discovery_transactions_per_poll': 4, 'rpc_daily_request_limit': 70000,
        'rpc_total_request_limit': 600000}).model_dump())
    manifest = {'version': 1, 'kind': 'independent_paper_service', 'source': source,
                'created_at': now.isoformat(), 'until': (now + timedelta(seconds=duration)).isoformat(),
                'core_sha256': code_digest(), 'service_sha256': service_digest(),
                'settings': settings.model_dump(mode='json', exclude=EXCLUDED_SETTINGS),
                'poll_seconds': .2 if source == 'demo' else settings.poll_seconds,
                'minimum_free_bytes': 2 * 1024**3, 'backup_seconds': 3600,
                'max_failures': 5, 'review_evidence': evidence,
                'clock': 'synthetic observation timestamps' if source == 'demo' else 'wall clock UTC',
                'no_real_execution': True}
    directory.mkdir(parents=True, exist_ok=False)
    (directory / 'backups').mkdir()
    atomic_json(directory / 'manifest.json', {'manifest': manifest, 'sha256': digest(manifest)})
    return manifest


def load_manifest(directory):
    envelope = json.loads((directory / 'manifest.json').read_text())
    manifest = envelope['manifest']
    if (digest(manifest) != envelope['sha256'] or manifest.get('kind') != 'independent_paper_service'
            or manifest['core_sha256'] != code_digest() or manifest['service_sha256'] != service_digest()):
        raise ValueError('Paper service manifest or software changed')
    return manifest


class Reader(Database):
    def __init__(self, path, source):
        self.source = source
        self.conn = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('BEGIN')


def check_database(path, manifest):
    if not path.exists():
        return
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        marker = db.execute("SELECT value FROM metadata WHERE key='paper_service_manifest'").fetchone()
        source = db.execute("SELECT value FROM metadata WHERE key='source'").fetchone()
        expected = 'demo' if manifest['source'] == 'demo' else 'dexscreener'
        if marker != (digest(manifest),) or source != (expected,):
            raise ValueError('Database does not belong to this Paper service')


def read_status(directory):
    manifest = load_manifest(directory)
    path = directory / 'state.json'
    state = json.loads(path.read_text()) if path.exists() else {'status': 'initialized'}
    result = {'directory': str(directory), 'source': manifest['source'], 'until': manifest['until'], 'state': state}
    dbpath = directory / 'paper.sqlite3'
    if dbpath.exists():
        check_database(dbpath, manifest)
        db = Reader(dbpath, 'demo' if manifest['source'] == 'demo' else 'dexscreener')
        try:
            result['paper'] = Engine.stored_summary(db, Settings.model_validate(manifest['settings']))
            result['rpc_requests_by_day'] = dict(db.conn.execute('SELECT utc_day,requests FROM rpc_request_budget'))
            result['last_observation_at'] = db.conn.execute('SELECT max(received_at) FROM snapshots').fetchone()[0]
            result['last_price_at'] = db.conn.execute('SELECT max(received_at) FROM snapshots WHERE price IS NOT NULL').fetchone()[0]
        finally:
            db.close()
    # The last written state alone is not proof that its process still runs.
    import fcntl
    lockpath = Path(str(dbpath) + '.lock')
    running = False
    if lockpath.exists():
        with lockpath.open('r') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(lock, fcntl.LOCK_UN)
            except BlockingIOError:
                running = True
    result['process_running'] = running
    return result


def format_status(result):
    state, paper = result['state'], result.get('paper', {})
    end = utc(result['until']).astimezone(ZoneInfo('Europe/Zurich')).strftime('%d.%m.%Y %H:%M:%S %Z')
    lines = ['PAPER-DIENST – NUR VIRTUELLES GELD',
             'Daten: ' + ('KÜNSTLICHE TESTKURSE' if result['source'] == 'demo' else 'Marktbeobachtungen'),
             'Prozess: ' + ('aktiv' if result['process_running'] else 'nicht aktiv'),
             f"Gespeicherter Betriebszustand: {state['status']}", f'Geplantes Ende: {end}']
    if state.get('status') == 'running' and not result['process_running']:
        lines.append('PRÜFEN: letzter Zustand meldet running, aber kein aktiver Schreiber vorhanden.')
    if paper:
        lines += [f"Beobachtungen: {paper['snapshots']}; simulierte Ausführungen: {paper['fills']}",
                  f"Virtuelles Cash: {paper['cash_usd']} USD; reserviert: {paper['reserved_cash_usd']} USD",
                  f"Offene Positionen: {paper['open_positions']}; ausstehende Orders: {paper['pending_orders']}",
                  'Buchhaltung: ' + ('stimmig' if paper['accounting']['balanced'] else 'FEHLER'),
                  f"Bewertungswarnungen: {len(paper['valuation_warnings'])}"]
        if not result['process_running'] and (paper['open_positions'] or paper['pending_orders']):
            lines.append('Offene Positionen/Orders bleiben gespeichert; es wurde keine Liquidation erfunden.')
    if state.get('backup_error_type'):
        lines.append('PRÜFEN: Sicherung fehlgeschlagen (' + state['backup_error_type'] + ').')
    last = state.get('last_backup')
    lines.append('Letzte Sicherung: ' + (f"{last['at']} – Integrität {last['integrity']}" if last else 'noch keine bestätigt'))
    total = sum(result.get('rpc_requests_by_day', {}).values())
    lines.append(f'RPC-Versuche dieser Paper-Sammlung: {total}; keine Umrechnung in Helius-Credits.')
    if result['source'] == 'market':
        quote_at = result.get('last_price_at')
        age = utcnow().timestamp() - quote_at if quote_at is not None else None
        lines.append('Letzter numerischer Kurs: ' + (f'vor {age:.0f} Sekunden' if age is not None else 'noch keiner'))
        if result['process_running'] and (age is None or not 0 <= age < 120):
            lines.append('PRÜFEN: keine bestätigten frischen Kursdaten.')
    return '\n'.join(lines)


def backup(directory, slot):
    target = directory / 'backups' / f'paper-{slot}.sqlite3'
    temporary = target.with_suffix('.pending')
    with sqlite3.connect((directory / 'paper.sqlite3').as_uri() + '?mode=ro', uri=True) as src:
        size = src.execute('PRAGMA page_count').fetchone()[0] * src.execute('PRAGMA page_size').fetchone()[0]
        if shutil.disk_usage(directory).free < size + 2 * 1024**3:
            raise OSError('Not enough space for safe Paper backup')
        with sqlite3.connect(temporary) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Paper backup integrity check failed')
    temporary.replace(target)
    return {'at': utcnow().isoformat(), 'path': str(target), 'integrity': 'ok', 'bytes': target.stat().st_size}


def restore(source, backup_path, destination):
    manifest = load_manifest(source)
    if backup_path.resolve().parent != (source / 'backups').resolve() or backup_path.suffix != '.sqlite3':
        raise ValueError('Choose a checked SQLite backup from this Paper directory')
    check_database(backup_path, manifest)
    if not backup_path.is_file():
        raise ValueError('Backup is missing')
    # Refuse a live writer; stop marker prevents its later automatic restart.
    with single_writer(source / 'paper.sqlite3'):
        destination.mkdir(parents=True, exist_ok=False)
        (destination / 'backups').mkdir()
        with sqlite3.connect(backup_path.resolve().as_uri() + '?mode=ro', uri=True) as src:
            with sqlite3.connect(destination / 'paper.sqlite3') as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Restored Paper backup integrity failed')
        check_database(destination / 'paper.sqlite3', manifest)
        atomic_json(destination / 'manifest.json', {'manifest': manifest, 'sha256': digest(manifest)})
        reader = Reader(destination / 'paper.sqlite3', 'demo' if manifest['source'] == 'demo' else 'dexscreener')
        try:
            summary = Engine.stored_summary(reader, Settings.model_validate(manifest['settings']))
            if not summary['accounting']['balanced']:
                raise ValueError('Restored Paper accounting failed')
        finally:
            reader.close()
        atomic_json(destination / 'state.json', {'status': 'initialized', 'restored_at': utcnow().isoformat(),
                    'restored_from': str(backup_path), 'paper': summary})
        (source / 'stop.request').touch()
    return {'status': 'restored_not_started', 'directory': str(destination), 'original_stop_requested': True,
            'deadline_preserved': manifest['until'], 'note': 'Only the saved backup point is recovered; later data is not invented'}


async def run(directory, *, stop=None, feed_factory=MarketFeed):
    manifest = load_manifest(directory)
    stop = stop or asyncio.Event()
    state_path = directory / 'state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    if state.get('status') in TERMINAL:
        return 0 if state['status'] in {'scheduled_end', 'stopped_by_request', 'source_exhausted'} else 1
    if utcnow() >= utc(manifest['until']) or (directory / 'stop.request').exists():
        state['status'] = 'scheduled_end' if utcnow() >= utc(manifest['until']) else 'stopped_by_request'
        atomic_json(state_path, state)
        return 0
    settings = Settings.model_validate(manifest['settings'])
    if manifest['source'] == 'market':
        credentials = load_settings()
        settings = settings.model_copy(update={name: getattr(credentials, name)
                                              for name in ('solana_rpc_url', 'solana_rpc_fallback_urls', 'dex_base_url')})
    with single_writer(directory / 'paper.sqlite3'):
        check_database(directory / 'paper.sqlite3', manifest)
        db = Database(directory / 'paper.sqlite3', 'demo' if manifest['source'] == 'demo' else 'dexscreener')
        try:
            # Refuse a DB not created specifically for this service.
            marker = db.conn.execute("SELECT value FROM metadata WHERE key='paper_service_manifest'").fetchone()
            if marker is None and db.counts()['snapshots']:
                raise ValueError('Paper service cannot adopt an existing observation database')
            if marker and marker[0] != digest(manifest):
                raise ValueError('Paper database belongs to a different manifest')
            with db.conn:
                db.conn.execute("INSERT OR IGNORE INTO metadata VALUES('paper_service_manifest',?)", (digest(manifest),))
            engine = Engine(db, settings)
            state.update(status='running', pid=os.getpid(), started_at=utcnow().isoformat(),
                         launches=state.get('launches', 0) + 1)
            state.setdefault('cycles', 0)
            state.setdefault('consecutive_failures', 0)
            state.setdefault('backup_count', 0)
            quotes = list(demo_snapshots()) if manifest['source'] == 'demo' else None
            context = feed_factory(db, settings) if quotes is None else nullcontext(None)
            async with context as feed:
                while True:
                    now = utcnow()
                    if stop.is_set() or (directory / 'stop.request').exists():
                        state['status'] = 'stopped_by_request'
                        break
                    if now >= utc(manifest['until']):
                        state['status'] = 'scheduled_end'
                        break
                    if shutil.disk_usage(directory).free < manifest['minimum_free_bytes']:
                        state['status'] = 'disk_space_low'
                        break
                    if state['consecutive_failures'] >= manifest['max_failures']:
                        state['status'] = 'failure_limit'
                        break
                    state['heartbeat_at'] = now.isoformat()
                    atomic_json(state_path, state)
                    row = db.conn.execute("SELECT value FROM metadata WHERE key='paper_demo_cursor'").fetchone()
                    cursor = int(row[0]) if row else 0
                    if quotes is not None and cursor >= len(quotes):
                        state['status'] = 'source_exhausted'
                        break
                    if quotes is None:
                        engine.tick(now)
                        task = asyncio.create_task(feed.cycle())
                        stopping = asyncio.create_task(stop.wait())
                        try:
                            done, _ = await asyncio.wait({task, stopping}, timeout=min(60, (utc(manifest['until']) - now).total_seconds()),
                                                         return_when=asyncio.FIRST_COMPLETED)
                            if task not in done:
                                if stop.is_set():
                                    state['status'] = 'stopped_by_request'
                                    break
                                raise TimeoutError('Bounded Paper feed cycle expired')
                            batch, diagnostics = task.result()
                        except (TimeoutError, OSError, ValueError) as error:
                            batch, diagnostics = [], {'feed_error_type': type(error).__name__}
                        finally:
                            for pending in (task, stopping):
                                if not pending.done():
                                    pending.cancel()
                            await asyncio.gather(task, stopping, return_exceptions=True)
                    else:
                        batch, diagnostics = [quotes[cursor]], {'synthetic': True}
                    progressed = False
                    for quote in batch:
                        if stop.is_set() or utcnow() >= utc(manifest['until']):
                            break
                        when = quote.received_at if quotes is not None else utcnow()
                        decision = engine.process(quote, when)
                        progressed |= (decision is not None and quote.price_usd is not None
                                       and 0 <= (when - quote.received_at).total_seconds() <= settings.max_quote_age_seconds)
                        if quotes is not None:
                            with db.conn:
                                db.conn.execute("INSERT OR REPLACE INTO metadata VALUES('paper_demo_cursor',?)", (str(cursor + 1),))
                    if quotes is None:
                        engine.tick(utcnow())
                    summary = engine.summary()
                    if not summary['accounting']['balanced']:
                        raise ValueError('Paper accounting failed')
                    state.update(cycles=state['cycles'] + 1, heartbeat_at=utcnow().isoformat(),
                                 diagnostics=diagnostics, paper=summary,
                                 consecutive_failures=0 if progressed else state['consecutive_failures'] + 1)
                    last_backup = utc(state['last_backup']['at']) if state.get('last_backup') else None
                    if last_backup is None or (utcnow() - last_backup).total_seconds() >= manifest['backup_seconds']:
                        try:
                            state['last_backup'] = backup(directory, state['backup_count'] % 2)
                            state['backup_count'] += 1
                            state.pop('backup_error_type', None)
                        except (OSError, sqlite3.Error, ValueError) as error:
                            state['backup_error_type'] = type(error).__name__
                    atomic_json(state_path, state)
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=min(manifest['poll_seconds'], max(0, (utc(manifest['until']) - utcnow()).total_seconds())))
                    except TimeoutError:
                        pass
            # No invented liquidation: retain open positions and unexpired orders.
            if quotes is None:
                engine.tick(utcnow())
            state.update(paper=engine.summary(), stopped_at=utcnow().isoformat(), pid=None)
            try:
                state['last_backup'] = backup(directory, state['backup_count'] % 2)
                state['backup_count'] += 1
            except (OSError, sqlite3.Error, ValueError) as error:
                state['backup_error_type'] = type(error).__name__
            atomic_json(state_path, state)
            return 0 if state['status'] in {'scheduled_end', 'stopped_by_request', 'source_exhausted'} else 1
        except Exception as error:
            state.update(status='service_error', error_type=type(error).__name__, pid=None,
                         consecutive_failures=state.get('consecutive_failures', 0) + 1,
                         stopped_at=utcnow().isoformat())
            atomic_json(state_path, state)
            raise
        finally:
            db.close()


async def foreground(directory):
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    return await run(directory, stop=stop)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'run', 'status', 'stop', 'restore'))
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--source', choices=('demo', 'market'), default='demo')
    parser.add_argument('--duration', type=int, default=60)
    parser.add_argument('--protocol', type=Path)
    parser.add_argument('--reviewed-evaluation', type=Path)
    parser.add_argument('--from-directory', type=Path)
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--human', action='store_true', help='Readable German status')
    args = parser.parse_args()
    directory = args.directory.resolve()
    try:
        if args.command == 'init':
            value = initialize(directory, source=args.source, duration=args.duration,
                               protocol=args.protocol, evaluation=args.reviewed_evaluation)
        elif args.command == 'run':
            return asyncio.run(foreground(directory))
        elif args.command == 'status':
            value = read_status(directory)
        elif args.command == 'restore':
            if args.from_directory is None or args.backup is None:
                raise ValueError('--from-directory and --backup required')
            value = restore(args.from_directory.resolve(), args.backup.resolve(), directory)
        else:
            load_manifest(directory)
            (directory / 'stop.request').touch()
            value = {'stop_requested': True}
        print(format_status(value) if args.command == 'status' and args.human else json.dumps(value, indent=2))
        return 0
    except Exception as error:
        print(f'Paper-Dienst: {type(error).__name__}; keine Zugangsdaten protokolliert.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
