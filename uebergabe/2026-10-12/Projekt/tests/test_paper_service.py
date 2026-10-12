import asyncio
from datetime import timedelta
import json
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time

import pytest

from backtesting.evaluation import digest, prepare
from backtesting.__main__ import freeze_input
from backtesting.replay import Observation
from collectors.demo import demo_snapshots
from config.settings import Settings
from data.database import Database
from data.models import utcnow
from operations import paper_service as service
from operations.paper_feed import MarketFeed, select_pairs
from trading.engine import Engine


@pytest.fixture
def market_protocol(tmp_path, quote):
    """Synthetic schema fixture, independent of private runtime evidence.

    The market source label exercises the protocol gate in these unit tests;
    this is not a real market evaluation or a deployable collection plan.
    """
    source = tmp_path / 'fixture-development.sqlite3'
    freeze_input(source, [Observation(1, quote(source='dexscreener'))], 'dexscreener')
    directory = tmp_path / 'fixture-protocol'
    prepare([source], directory, Settings(), now=quote(3600).received_at)
    return directory / 'protocol.json'


def edit_manifest(directory, **changes):
    envelope = json.loads((directory / 'manifest.json').read_text())
    envelope['manifest'].update(changes)
    envelope['sha256'] = digest(envelope['manifest'])
    (directory / 'manifest.json').write_text(json.dumps(envelope))


@pytest.mark.asyncio
async def test_demo_service_backups_readonly_status_and_terminal_restart(tmp_path):
    directory = tmp_path / 'paper'
    service.initialize(directory)
    edit_manifest(directory, poll_seconds=.001)
    assert await service.run(directory) == 0
    result = service.read_status(directory)
    assert result['state']['status'] == 'source_exhausted'
    assert not result['process_running']
    assert result['paper']['snapshots'] == 18 and result['paper']['fills'] == 2
    assert result['paper']['accounting']['balanced']
    assert result['state']['last_backup']['integrity'] == 'ok'
    before = (directory / 'paper.sqlite3').read_bytes()
    service.read_status(directory)
    assert await service.run(directory) == 0
    assert (directory / 'paper.sqlite3').read_bytes() == before
    for backup in (directory / 'backups').glob('*.sqlite3'):
        with sqlite3.connect(backup) as db:
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_actual_service_sigkill_resumes_pending_order_without_duplicate_trades(tmp_path):
    directory = tmp_path / 'paper'
    service.initialize(directory, duration=45)
    command = [sys.executable, '-m', 'operations.paper_service', 'run', '--directory', str(directory)]
    child = subprocess.Popen(command, cwd=service.ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            path = directory / 'state.json'
            state = json.loads(path.read_text()) if path.exists() else {}
            if state.get('paper', {}).get('pending_orders') == 1:
                break
            if child.poll() is not None:
                pytest.fail('Service exited before pending-order checkpoint')
            time.sleep(.01)
        else:
            pytest.fail('No pending-order checkpoint')
        assert service.read_status(directory)['process_running']
        child.kill()
        child.communicate(timeout=5)
        assert child.returncode == -signal.SIGKILL
        assert not service.read_status(directory)['process_running']
        result = subprocess.run(command, cwd=service.ROOT, capture_output=True, timeout=15)
        assert result.returncode == 0, result.stderr
        status = service.read_status(directory)
        assert status['state']['launches'] == 2
        assert status['paper']['snapshots'] == 18 and status['paper']['fills'] == 2
        assert status['paper']['accounting']['balanced']
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=5)
        child.stderr.close()


@pytest.mark.asyncio
async def test_end_preserves_open_position_and_does_not_fabricate_liquidation(tmp_path, monkeypatch):
    directory = tmp_path / 'paper'
    service.initialize(directory)
    edit_manifest(directory, poll_seconds=.001)
    monkeypatch.setattr(service, 'demo_snapshots', lambda: iter(list(demo_snapshots())[:5]))
    assert await service.run(directory) == 0
    value = service.read_status(directory)
    assert value['paper']['fills'] == 1
    assert value['paper']['open_positions'] == 1
    assert value['paper']['accounting']['balanced']


@pytest.mark.asyncio
async def test_requested_stop_persists_and_never_resets_wallet(tmp_path):
    directory = tmp_path / 'paper'
    service.initialize(directory)
    stop = asyncio.Event()
    task = asyncio.create_task(service.run(directory, stop=stop))
    while not (directory / 'state.json').exists():
        await asyncio.sleep(.01)
    stop.set()
    assert await task == 0
    value = service.read_status(directory)
    assert value['state']['status'] == 'stopped_by_request'
    before = (directory / 'paper.sqlite3').read_bytes()
    assert await service.run(directory) == 0
    assert (directory / 'paper.sqlite3').read_bytes() == before


@pytest.mark.asyncio
async def test_expired_window_does_not_create_wallet_or_open_network(tmp_path):
    directory = tmp_path / 'paper'
    service.initialize(directory, now=utcnow() - timedelta(minutes=5))
    assert await service.run(directory) == 0
    assert not (directory / 'paper.sqlite3').exists()
    assert service.read_status(directory)['state']['status'] == 'scheduled_end'


def test_market_initialization_blocks_before_reading_future_evaluation(tmp_path, market_protocol):
    protocol = market_protocol
    nonexistent = tmp_path / 'future-evaluation.json'
    envelope = json.loads(protocol.read_text())
    with pytest.raises(ValueError, match='have not ended'):
        service.initialize(tmp_path / 'paper', source='market', protocol=protocol, evaluation=nonexistent,
                           now=service.utc(envelope['plan']['test_start_utc']))
    assert not (tmp_path / 'paper').exists()


def test_tampered_manifest_and_existing_directory_are_rejected(tmp_path):
    directory = tmp_path / 'paper'
    service.initialize(directory)
    with pytest.raises(FileExistsError):
        service.initialize(directory)
    path = directory / 'manifest.json'
    payload = json.loads(path.read_text())
    payload['manifest']['source'] = 'market'
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        service.load_manifest(directory)


@pytest.mark.asyncio
async def test_service_will_not_adopt_observation_database(tmp_path):
    directory = tmp_path / 'paper'
    service.initialize(directory)
    path = directory / 'paper.sqlite3'
    Database(path, 'dexscreener').close()
    before = path.read_bytes()
    with pytest.raises(ValueError, match='does not belong'):
        await service.run(directory)
    assert path.read_bytes() == before


def test_positions_and_pending_orders_keep_priority_and_pair(tmp_path):
    db = Database(tmp_path / 'db.sqlite3', 'demo')
    engine = Engine(db, Settings())
    quotes = list(demo_snapshots())
    for quote in quotes[:3]:
        engine.process(quote, quote.received_at)
    with db.conn:
        for index in range(12):
            db.discover(f'candidate{index}', utcnow().timestamp(), 'demo')
    settings = Settings(max_watch_tokens=1)
    assert select_pairs(db, settings) == {'DEMO_MOMENTUM': 'DEMO_POOL_A'}
    for quote in quotes[3:5]:
        engine.process(quote, quote.received_at)
    assert select_pairs(db, settings) == {'DEMO_MOMENTUM': 'DEMO_POOL_A'}
    db.close()


@pytest.mark.asyncio
async def test_market_feed_keeps_missing_position_and_budget_after_restart(tmp_path):
    from collectors.http import DataUnavailable
    db = Database(tmp_path / 'db.sqlite3', 'demo')
    engine = Engine(db, Settings())
    for quote in list(demo_snapshots())[:5]:
        engine.process(quote, quote.received_at)
    settings = Settings(max_watch_tokens=1, pool_discovery_enabled=False, rpc_daily_request_limit=1)
    class Dex:
        async def snapshots(self, tokens, pairs):
            return {}
        async def snapshot(self, token, pair):
            assert pair == 'DEMO_POOL_A'
            return None
    # Session exists but every data request is replaced; no network call.
    async with MarketFeed(db, settings) as feed:
        feed.dex = Dex()
        feed.last_discovery = time.monotonic()
        feed.budget.reserve()
        batch, diagnostics = await feed.cycle()
        assert len(batch) == 1 and batch[0].price_usd is None
        assert batch[0].pair == 'DEMO_POOL_A'
    async with MarketFeed(db, settings) as feed:
        with pytest.raises(DataUnavailable, match='budget exhausted'):
            feed.budget.reserve()
    assert db.load_wallet().positions
    db.close()


@pytest.mark.asyncio
async def test_backup_restore_preserves_deadline_and_stops_original(tmp_path):
    from main import single_writer
    directory = tmp_path / 'paper'
    service.initialize(directory)
    edit_manifest(directory, poll_seconds=.001)
    assert await service.run(directory) == 0
    saved = directory / 'backups/paper-0.sqlite3'
    target = tmp_path / 'restored'
    with single_writer(directory / 'paper.sqlite3'):
        with pytest.raises(ValueError, match='process already uses'):
            service.restore(directory, saved, target)
    assert not target.exists()
    original = (directory / 'paper.sqlite3').read_bytes()
    result = service.restore(directory, saved, target)
    assert result['status'] == 'restored_not_started'
    assert (directory / 'stop.request').exists()
    assert (directory / 'paper.sqlite3').read_bytes() == original
    assert service.load_manifest(target)['until'] == service.load_manifest(directory)['until']
    assert await service.run(target) == 0
    actual = service.read_status(target)['paper']
    assert actual['snapshots'] == 18 and actual['fills'] == 2
    assert actual['accounting']['balanced']


@pytest.mark.asyncio
async def test_repeated_missing_prices_stop_without_infinite_restarts(tmp_path, monkeypatch):
    directory = tmp_path / 'paper'
    service.initialize(directory)
    edit_manifest(directory, poll_seconds=.001)
    quotes = [quote.model_copy(update={'price_usd': None}) for quote in demo_snapshots()]
    monkeypatch.setattr(service, 'demo_snapshots', lambda: iter(quotes))
    assert await service.run(directory) == 1
    value = service.read_status(directory)
    assert value['state']['status'] == 'failure_limit'
    assert value['state']['cycles'] == 5
    assert value['paper']['fills'] == 0
    before = (directory / 'paper.sqlite3').read_bytes()
    assert await service.run(directory) == 1
    assert (directory / 'paper.sqlite3').read_bytes() == before


@pytest.mark.asyncio
async def test_deadline_cancels_stalled_feed_without_creating_orders(tmp_path, monkeypatch):
    directory = tmp_path / 'paper'
    service.initialize(directory)
    edit_manifest(directory, source='market', until=(utcnow() + timedelta(seconds=.15)).isoformat())
    # Supply local settings and a fully synthetic stalled adapter; never load credentials or send RPCs.
    monkeypatch.setattr(service, 'load_settings', lambda: Settings())
    cancelled = []
    class Stalled:
        def __init__(self, db, settings):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def cycle(self):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)
    assert await service.run(directory, feed_factory=Stalled) == 0
    assert cancelled == [True]
    value = service.read_status(directory)
    assert value['state']['status'] == 'scheduled_end'
    assert value['paper']['fills'] == 0 and value['paper']['pending_orders'] == 0


@pytest.mark.asyncio
async def test_low_disk_space_stops_before_processing_quotes(tmp_path, monkeypatch):
    from types import SimpleNamespace
    directory = tmp_path / 'paper'
    service.initialize(directory)
    monkeypatch.setattr(service.shutil, 'disk_usage', lambda p: SimpleNamespace(free=100))
    assert await service.run(directory) == 1
    value = service.read_status(directory)
    assert value['state']['status'] == 'disk_space_low'
    assert value['paper']['snapshots'] == 0
    assert 'backup_error_type' in value['state']


@pytest.mark.asyncio
async def test_backup_failure_is_visible_without_resetting_wallet(tmp_path, monkeypatch):
    directory = tmp_path / 'paper'
    service.initialize(directory)
    edit_manifest(directory, poll_seconds=.001)
    def fail(*args):
        raise OSError('simulated backup storage error')
    monkeypatch.setattr(service, 'backup', fail)
    assert await service.run(directory) == 0
    value = service.read_status(directory)
    assert value['state']['backup_error_type'] == 'OSError'
    assert value['paper']['fills'] == 2 and value['paper']['accounting']['balanced']


def test_human_status_does_not_treat_old_running_state_as_liveness():
    text = service.format_status({'source': 'market', 'until': utcnow().isoformat(),
                                  'state': {'status': 'running'}, 'process_running': False})
    assert 'kein aktiver Schreiber' in text
    assert 'Letzter numerischer Kurs: noch keiner' in text


def test_market_evidence_must_match_frozen_protocol_and_be_reviewable(tmp_path, market_protocol):
    protocol = market_protocol
    envelope = json.loads(protocol.read_text())
    plan = envelope['plan']
    now = service.utc(plan['test_end_exclusive_utc']) + timedelta(days=1)
    report = tmp_path / 'evaluation.json'
    value = {'kind': 'PROSPECTIVE_WINDOW_EVALUATION', 'prospective': True,
             'protocol_sha256': envelope['sha256'], 'code_sha256': plan['code_sha256'],
             'assessment': {'status': 'INSUFFICIENT_EVIDENCE', 'eligible_for_review': False, 'blockers': ['too_few_closed_trades']},
             'inputs': {'source': 'dexscreener'}, 'scenario_definitions': plan['scenario_definitions']}
    report.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='reviewable'):
        service.reviewed_settings(protocol, report, now)
    value['assessment'] = {'status': 'REVIEWABLE_HOLDOUT', 'eligible_for_review': True, 'blockers': []}
    report.write_text(json.dumps(value))
    settings, evidence = service.reviewed_settings(protocol, report, now)
    assert settings.mode == 'PAPER'
    assert evidence['protocol_sha256'] == envelope['sha256']
    value['protocol_sha256'] = 'mismatched'
    report.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='reviewable'):
        service.reviewed_settings(protocol, report, now)
