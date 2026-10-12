"""Phase 7 operational rehearsal using synthetic data only; no network calls."""
import argparse
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import sqlite3
import subprocess
import sys

from backtesting.evaluation import code_digest
from collectors.demo import demo_snapshots
from config.settings import Settings
from data.database import Database
from data.models import utcnow
from main import single_writer
from trading.engine import Engine

ROOT = Path(__file__).resolve().parents[1]


def worker(path, pause=None):
    if path.exists():
        with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as existing:
            source = existing.execute("SELECT value FROM metadata WHERE key='source'").fetchone()
            if source != ('demo',):
                raise ValueError('Rehearsal only accepts synthetic databases')
    with single_writer(path):
        db = Database(path, 'demo')
        try:
            engine = Engine(db, Settings())  # no .env, credentials or lowered risk limits
            for snapshot in demo_snapshots():
                engine.process(snapshot, snapshot.received_at)
                pending = bool(db.pending_orders())
                position = bool(db.load_wallet().positions)
                if (pause == 'pending' and pending) or (pause == 'position' and position):
                    print(json.dumps({'checkpoint': pause, 'pending': pending, 'position': position}), flush=True)
                    # Parent verifies writer exclusion, then sends actual SIGKILL.
                    sys.stdin.readline()
                    raise RuntimeError('Crash worker must be killed, not continued')
            print(json.dumps({'completed': True}), flush=True)
        finally:
            db.close()


def invoke(path, pause=None):
    command = [sys.executable, '-m', 'operations.paper_rehearsal', '--worker', str(path)]
    if pause:
        command += ['--pause', pause]
    env = {key: value for key, value in os.environ.items() if key in {'PATH', 'LANG', 'LC_ALL', 'TZ'}}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    process = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        if not pause:
            stdout, _ = process.communicate(timeout=30)
            if process.returncode != 0:
                raise RuntimeError('Synthetic worker failed')
            return json.loads(stdout)
        if not select.select([process.stdout], [], [], 20)[0]:
            raise RuntimeError('Synthetic worker did not reach crash checkpoint')
        checkpoint = json.loads(process.stdout.readline())
        if checkpoint.get('checkpoint') != pause:
            raise RuntimeError('Crash checkpoint mismatch')
        excluded = False
        try:
            with single_writer(path):
                pass
        except ValueError:
            excluded = True
        if not excluded:
            raise RuntimeError('Second writer was not excluded')
        process.kill()
        process.communicate(timeout=5)
        if process.returncode != -signal.SIGKILL:
            raise RuntimeError('Worker did not terminate by SIGKILL')
        return {**checkpoint, 'second_writer_excluded': True, 'exit_code': process.returncode}
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


def inspect(path):
    # All inspected paths are newly created rehearsal DBs, never campaign inputs.
    db = Database(path, 'demo')
    try:
        summary = Engine.stored_summary(db, Settings())
        if not summary['accounting']['balanced']:
            raise ValueError('Unbalanced paper accounting')
        contents = {}
        for table, columns in (
            ('snapshots', 'id,token,pair,received_at,price,payload'),
            ('decisions', 'snapshot_id,signal_at,action,payload'),
            ('paper_orders', '*'), ('fills', '*'), ('paper_ledger', '*'), ('wallet', '*'),
        ):
            contents[table] = [list(row) for row in db.conn.execute(f'SELECT {columns} FROM {table} ORDER BY 1')]
        encoded = json.dumps(contents, sort_keys=True, separators=(',', ':')).encode()
        return {'summary': summary, 'semantic_sha256': hashlib.sha256(encoded).hexdigest()}
    finally:
        db.close()


def backup(source, target):
    if target.exists():
        raise FileExistsError('Preserve existing rehearsal backup')
    with sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True) as src:
        with sqlite3.connect(target) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Backup integrity failure')


def outage(path):
    db = Database(path, 'demo')
    try:
        engine = Engine(db, Settings())
        quotes = list(demo_snapshots())
        for quote in quotes[:3]:
            engine.process(quote, quote.received_at)
        if len(db.pending_orders()) != 1:
            raise ValueError('Outage test requires a pending entry')
        resumed_at = quotes[2].received_at + timedelta(minutes=10)
        engine.tick(resumed_at)
        engine.process(quotes[4], resumed_at)  # stale quote cannot invent a fill
        summary = engine.summary()
        if (db.pending_orders() or summary['fills'] or summary['open_positions']
                or not summary['accounting']['balanced'] or db.load_wallet().cash != 50):
            raise ValueError('Quote outage produced incorrect state')
        if summary['order_status_counts'].get('expired') != 1:
            raise ValueError('Pending entry did not expire')
        return {'expired_orders': 1, 'fills': 0, 'cash_usd': '50.00', 'accounting_balanced': True}
    finally:
        db.close()


def rehearse(out):
    out.mkdir(parents=True, exist_ok=False)
    core_before = code_digest()
    continuous = out / 'continuous.sqlite3'
    invoke(continuous)
    baseline = inspect(continuous)
    if baseline['summary']['fills'] != 2 or baseline['summary']['pending_orders'] or baseline['summary']['open_positions']:
        raise ValueError('Synthetic reference did not exercise a full round trip')
    checks = {}
    for stage in ('pending', 'position'):
        path = out / f'crash-{stage}.sqlite3'
        crash = invoke(path, stage)
        saved = inspect(path)
        if stage == 'pending' and saved['summary']['pending_orders'] != 1:
            raise ValueError('Committed pending order lost')
        if stage == 'position' and saved['summary']['open_positions'] != 1:
            raise ValueError('Committed position lost')
        copy = out / f'restored-{stage}.sqlite3'
        backup(path, copy)
        backup_hash = hashlib.sha256(copy.read_bytes()).hexdigest()
        for destination in (path, copy):
            invoke(destination)
            actual = inspect(destination)
            if actual['semantic_sha256'] != baseline['semantic_sha256']:
                raise ValueError('Restart/restore changed paper observations or accounting')
            invoke(destination)  # replaying committed input must be idempotent
            if inspect(destination)['semantic_sha256'] != baseline['semantic_sha256']:
                raise ValueError('Repeated restart duplicated committed work')
        checks[stage] = {**crash, 'checkpoint': saved['summary'], 'backup_integrity': 'ok',
                         'backup_before_resume_sha256': backup_hash,
                         'resume_matches_continuous': True, 'restore_matches_continuous': True,
                         'repeated_resume_idempotent': True}
    checks['quote_outage'] = outage(out / 'outage.sqlite3')
    if code_digest() != core_before:
        raise ValueError('Frozen core changed during rehearsal')
    result = {'phase': 7, 'status': 'SYNTHETIC_OPERATIONAL_REHEARSAL_PASSED',
              'checked_at': utcnow().isoformat(), 'data_source': 'demo', 'network_requests': 0,
              'core_sha256': core_before, 'reference': baseline, 'checks': checks,
              'live_trading_approved': False, 'market_paper_service_started': False,
              'limitations': ['Synthetic process recovery only, not host power-loss recovery',
                              'No market profitability or holdout acceptance demonstrated',
                              'No production Paper service, monitoring or resource-load test deployed',
                              'No real-time market Paper run started; Phase 6 evidence still pending']}
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--worker', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--pause', choices=('pending', 'position'), help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.worker:
            worker(args.worker.resolve(), args.pause)
            return 0
        if not args.out:
            parser.error('--out is required')
        result = rehearse(args.out.resolve())
        print(json.dumps({'status': result['status'], 'output': str(args.out),
                          'market_paper_service_started': False}, indent=2))
        return 0
    except Exception as error:
        print(f'Betriebsprobe fehlgeschlagen ({type(error).__name__}); vorhandene Dateien bleiben erhalten.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
