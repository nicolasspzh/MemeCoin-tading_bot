import base64
import struct
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

import main
from collectors.http import DataUnavailable
from collectors.mint import TOKEN_PROGRAM
from collectors.schedule import ObservationSchedule, RpcBudget
from collectors.solana import Solana
from config.settings import Settings
from data.database import Database
from data.models import Snapshot
from operations.campaign import Recorder
from trading.risk import risk_reasons

START = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def cohort(tmp_path):
    db = Database(tmp_path / 'cohort.sqlite3', 'dexscreener')
    settings = Settings(observation_cohorts=True, max_watch_tokens=2, pool_discovery_enabled=False)
    recorder = Recorder(db, settings)
    with db.conn:
        for token in ('A', 'B', 'C'):
            db.discover(token, START.timestamp(), 'test')
    yield db, settings, recorder, ObservationSchedule(db, settings)
    db.close()


def observe(schedule, recorder, token, seconds, price='1'):
    snapshot = Snapshot(token=token, pair=token + '-POOL', source='dexscreener',
                        received_at=START + timedelta(seconds=seconds),
                        price_usd=Decimal(price) if price else None)
    return recorder.process(schedule.decorate(snapshot), snapshot.received_at)


def test_full_timeline_follows_last_primary_quote_and_stops_creating_labels(cohort):
    db, settings, recorder, schedule = cohort
    for second in range(0, 5760, 20):
        assert schedule.select(START.timestamp() + second) == ['A', 'B']
        for token in ('A', 'B'):
            observe(schedule, recorder, token, second)
        if second == 1800:
            # Reload scheduler/engine against persisted state, as on worker restart.
            schedule = ObservationSchedule(db, settings)
            recorder = Recorder(db, settings)
    labels, resolved = db.conn.execute('SELECT count(*),count(future_snapshot_id) FROM outcomes').fetchone()
    assert labels == resolved == 2 * 90 * 6
    assert db.conn.execute("SELECT count(*) FROM snapshots WHERE json_extract(payload,'$.observation_phase')='followup'").fetchone()[0] > 0
    assert schedule.select(START.timestamp() + 5760) == []
    assert schedule.status(START.timestamp() + 5760)['completed'] == 2
    assert db.conn.execute('SELECT count(*) FROM paper_orders').fetchone()[0] == 0


def test_quote_at_minute_50_remains_tracked_until_its_hourly_outcome(cohort):
    db, settings, recorder, _ = cohort
    settings.observation_primary_seconds = 3600
    schedule = ObservationSchedule(db, settings)
    schedule.select(START.timestamp())
    observe(schedule, recorder, 'A', 50 * 60)
    assert 'A' in schedule.select(START.timestamp() + 67 * 60)
    observe(schedule, recorder, 'A', 110 * 60)
    row = db.conn.execute('SELECT future_snapshot_id FROM outcomes WHERE horizon_seconds=3600').fetchone()
    assert row[0] is not None


def test_missing_pool_keeps_slot_and_missing_windows_are_not_fabricated(cohort):
    db, _, recorder, schedule = cohort
    schedule.select(START.timestamp())
    observe(schedule, recorder, 'A', 0)
    observe(schedule, recorder, 'B', 0)
    for second in (20, 1800, 3600, 3940):
        assert 'A' in schedule.select(START.timestamp() + second)
        observe(schedule, recorder, 'A', second, price=None)
    assert db.conn.execute('SELECT count(*) FROM outcomes WHERE future_snapshot_id IS NOT NULL').fetchone()[0] == 0
    assert db.conn.execute('SELECT count(*) FROM observation_tracks WHERE token=\'C\'').fetchone()[0] == 0
    assert 'A' not in schedule.select(START.timestamp() + 3961)


def test_new_candidates_only_enter_free_slots_and_missing_ones_are_not_filtered(cohort):
    db, _, recorder, schedule = cohort
    assert schedule.select(START.timestamp()) == ['A', 'B']
    observe(schedule, recorder, 'A', 0, price=None)
    # Neither admission got a priced anchor: after primary interval both finish.
    assert schedule.select(START.timestamp() + 1801) == ['C']
    assert schedule.select(START.timestamp() + 1802) == ['C']
    assert db.conn.execute('SELECT count(*) FROM observation_tracks').fetchone()[0] == 3


def test_campaign_cutoff_prevents_new_anchors_and_admissions(cohort):
    db, settings, recorder, _ = cohort
    cutoff = START.timestamp() + 600
    schedule = ObservationSchedule(db, settings, feature_until=cutoff)
    schedule.select(START.timestamp())
    observe(schedule, recorder, 'A', 599)
    observe(schedule, recorder, 'A', 600)
    assert db.latest('A', 'A-POOL').observation_phase == 'followup'
    assert db.conn.execute('SELECT count(*) FROM outcomes').fetchone()[0] == 6
    assert schedule.select(START.timestamp() + 600 + 3960) == []


def test_pinned_pool_never_switches(cohort):
    _, _, recorder, schedule = cohort
    schedule.select(START.timestamp())
    observe(schedule, recorder, 'A', 0)
    wrong = Snapshot(token='A', pair='DIFFERENT', source='dexscreener', received_at=START + timedelta(seconds=20))
    with pytest.raises(ValueError, match='pool cannot change'):
        schedule.decorate(wrong)


def test_staggered_admission_keeps_capacity_bounded_and_primary_observations_continuous(cohort):
    db, settings, recorder, _ = cohort
    settings.max_watch_tokens = 8
    settings.observation_admission_seconds = 720
    schedule = ObservationSchedule(db, settings)
    counts = []
    for second in range(0, 3 * 3600, 20):
        now = START.timestamp() + second
        if second % 720 == 0:
            with db.conn:
                db.discover('NEW' + str(second), now, 'test')
        selected = schedule.select(now)
        assert 1 <= len(selected) <= 8
        for token in selected:
            observe(schedule, recorder, token, second)
        assert schedule.status(now)['primary'] >= 1
        counts.append(len(selected))
        if second == 3600:
            schedule = ObservationSchedule(db, settings)  # cadence survives reload
    assert max(counts) == 8
    admitted = [row[0] for row in db.conn.execute('SELECT admitted_at FROM observation_tracks ORDER BY admitted_at')]
    assert all(b-a >= 720 for a,b in zip(admitted,admitted[1:]))


def test_budget_survives_restart_counts_failures_and_rolls_over_by_utc_day(cohort):
    db, _, _, _ = cohort
    budget = RpcBudget(db, daily=2, total=3)
    budget.reserve(START)
    RpcBudget(db, daily=2, total=3).reserve(START)
    with pytest.raises(DataUnavailable, match='budget exhausted'):
        budget.reserve(START)
    budget.reserve(START + timedelta(days=1))
    with pytest.raises(DataUnavailable, match='budget exhausted'):
        budget.reserve(START + timedelta(days=2))
    assert budget.status(START + timedelta(days=1))['total'] == 3


async def test_rpc_budget_is_enforced_before_network_and_counts_fallbacks(cohort):
    db, _, _, _ = cohort
    calls = []
    class Http:
        async def request(self, *args, **kwargs):
            calls.append(args[1])
            raise DataUnavailable('HTTP 500', status=500)
    rpc = Solana(Http(), 'https://first.example', ['https://second.example'], budget=RpcBudget(db, 1, 10))
    with pytest.raises(DataUnavailable, match='budget exhausted'):
        await rpc.rpc('getHealth', [])
    assert calls == ['https://first.example']
    assert RpcBudget(db, 1, 10).status()['total'] == 1


async def test_partial_risk_cache_preserves_failure_and_original_timestamp(quote, monkeypatch):
    clock = [START]
    monkeypatch.setattr('collectors.solana.utcnow', lambda: clock[0])
    calls = []
    class Http:
        async def request(self, *args, **kwargs):
            method = kwargs['json']['method']
            calls.append(method)
            if method != 'getAccountInfo':
                raise DataUnavailable('Holder service unavailable')
            data = bytearray(82)
            struct.pack_into('<Q', data, 36, 1000)
            data[45] = 1
            return {'result': {'context': {'slot': 100}, 'value': {'owner': TOKEN_PROGRAM,
                      'data': [base64.b64encode(data).decode(), 'base64']}}}
    rpc = Solana(Http(), 'https://rpc.example', cache_seconds=60, cache_partial=True)
    first = await rpc.mint_risk('So11111111111111111111111111111111111111112')
    clock[0] += timedelta(seconds=20)
    second = await rpc.mint_risk('So11111111111111111111111111111111111111112')
    assert len(calls) == 2
    assert second.checked_at == first.checked_at == START
    assert second.data_errors == first.data_errors and second.data_errors
    sample = quote(20, mint_risk=second)
    assert 'incomplete_onchain_checks' in risk_reasons(sample, sample.received_at, Settings())
    clock[0] += timedelta(seconds=41)
    await rpc.mint_risk('So11111111111111111111111111111111111111112')
    assert calls.count('getAccountInfo') == 2


def test_followup_prices_cannot_start_new_trades_but_can_close_positions(quote):
    sample = quote(observation_phase='followup')
    assert 'followup_only_no_new_entry' in risk_reasons(sample, sample.received_at, Settings())
    assert 'followup_only_no_new_entry' not in risk_reasons(sample, sample.received_at, Settings(), entry=False)


async def test_pinned_pool_batch_omission_recovers_without_extra_risk_on_missing_prices(tmp_path, monkeypatch, quote):
    db = Database(tmp_path / 'live.sqlite3', 'dexscreener')
    settings = Settings(observation_cohorts=True, pool_discovery_enabled=False, max_watch_tokens=1)
    recorder = Recorder(db, settings)
    now = main.utcnow()
    with db.conn:
        db.discover('A', now.timestamp(), 'test')
    schedule = ObservationSchedule(db, settings)
    schedule.select(now.timestamp())
    recorder.process(schedule.decorate(quote(source='dexscreener', token='A', received_at=now)))
    recovered, risk_calls = [], []
    class Dex:
        def __init__(self, *args): pass
        async def discover_feeds(self, feeds): return dict.fromkeys(await self.discover(), 'dexscreener-profile'), []
        async def discover(self): return ['A']
        async def snapshots(self, tokens, preferred): return {'A': None}
        async def snapshot(self, token, preferred):
            assert preferred == 'POOL'
            recovered.append(token)
            return quote(source='dexscreener', token=token, received_at=main.utcnow())
    class RPC:
        def __init__(self, *args, **kwargs): self.stats = {}
        async def mint_risk(self, token, pair):
            risk_calls.append(token)
            return quote().mint_risk.model_copy(update={'checked_at': main.utcnow()})
    monkeypatch.setattr(main, 'DexScreener', Dex)
    monkeypatch.setattr(main, 'Solana', RPC)
    try:
        assert await main.collect(recorder, once=True) == 0
        assert recovered == risk_calls == ['A']
        assert db.counts()['snapshots'] == 2
    finally:
        db.close()


WSOL = 'So11111111111111111111111111111111111111112'


def dex_quote(token, pair, *, dex_id='pumpswap', labels=None, quote_mint=WSOL, liquidity='20000', at=START,
              pool_age=timedelta(minutes=10)):
    return Snapshot(token=token, pair=pair, source='dexscreener', received_at=at, price_usd=Decimal('1'),
                    pair_created_at=at - pool_age if pool_age is not None else None,
                    liquidity_usd=Decimal(liquidity) if liquidity is not None else None,
                    raw={'dexId': dex_id, 'labels': labels, 'quoteToken': {'address': quote_mint}})


@pytest.mark.parametrize('kwargs,reasons', [
    ({}, []),
    ({'dex_id': 'raydium', 'labels': ['CPMM']}, []),
    ({'dex_id': 'raydium', 'labels': ['CLMM']}, ['unsupported_dex_pool']),
    ({'dex_id': 'pumpfun'}, ['unsupported_dex_pool']),
    ({'dex_id': 'meteoradbc'}, ['unsupported_dex_pool']),
    ({'quote_mint': 'Xs3eBt7uRfJX8QUs4suhyU8p2M6DoUDrJyWBa8LLZsg'}, ['unsupported_quote_mint']),
    ({'liquidity': '9999'}, ['insufficient_or_unknown_liquidity']),
    ({'liquidity': None}, ['insufficient_or_unknown_liquidity']),
    ({'pool_age': timedelta(hours=24)}, []),
    ({'pool_age': timedelta(hours=24, seconds=1)}, ['pool_older_than_entry_window']),
    ({'pool_age': None}, ['unknown_pair_age']),
])
def test_admission_prefilter_reasons(kwargs, reasons):
    from collectors.schedule import admission_reasons
    assert admission_reasons(dex_quote('A', 'P', **kwargs), Settings()) == reasons
    assert admission_reasons(None, Settings()) == ['no_dex_pair']


@pytest.fixture
def prefiltered(cohort):
    db, settings, recorder, _ = cohort
    settings = settings.model_copy(update={'admission_prefilter': True})
    return db, settings, recorder, ObservationSchedule(db, settings)


def test_prefilter_admits_oldest_eligible_coin_with_screened_pool(prefiltered):
    db, settings, recorder, schedule = prefiltered
    now = START.timestamp() + 10
    assert schedule.admission_due(now) and schedule.screen_candidates(now) == ['A', 'B', 'C']
    schedule.record_screens(now, {'A': dex_quote('A', 'A-CURVE', dex_id='pumpfun'),
                                  'B': dex_quote('B', 'B-SWAP'), 'C': None})
    assert schedule.screen_candidates(now) == []          # no rescreen within 5 minutes
    assert schedule.select(now) == ['B']                  # A is older but not eligible
    assert schedule.preferred_pair('B') == 'B-SWAP'       # exactly the screened pool
    rows = dict(db.conn.execute('SELECT token,eligible FROM admission_screens'))
    assert rows == {'A': 0, 'B': 1, 'C': 0}
    assert schedule.status(now)['screens_last_hour'] == {'eligible': 1, 'rejected': 2}
    assert schedule.screen_candidates(now + 301) == ['A', 'C']  # rejected coins may qualify later


def test_prefilter_needs_fresh_latest_screen(prefiltered):
    db, settings, recorder, schedule = prefiltered
    now = START.timestamp() + 10
    schedule.record_screens(now, {'A': dex_quote('A', 'A-SWAP')})
    assert schedule.select(now + 121) == []               # screen too old to admit
    schedule.record_screens(now + 400, {'A': dex_quote('A', 'A-SWAP', liquidity='500')})
    assert schedule.select(now + 401) == []               # latest screen rejects
    schedule.record_screens(now + 800, {'A': dex_quote('A', 'A-SWAP')})
    assert schedule.select(now + 801) == ['A']


def test_without_prefilter_admission_is_unchanged(cohort):
    db, settings, recorder, schedule = cohort
    assert schedule.select(START.timestamp() + 10) == ['A', 'B']
    assert db.conn.execute('SELECT count(*) FROM admission_screens').fetchone()[0] == 0


async def test_collect_screens_candidates_before_admission(tmp_path, monkeypatch, quote):
    db = Database(tmp_path / 'live.sqlite3', 'dexscreener')
    settings = Settings(observation_cohorts=True, pool_discovery_enabled=False, max_watch_tokens=2,
                        admission_prefilter=True)
    recorder = Recorder(db, settings)
    batches = []

    class Dex:
        def __init__(self, *args): pass
        async def discover_feeds(self, feeds): return dict.fromkeys(await self.discover(), 'dexscreener-profile'), []
        async def discover(self): return ['OLD', 'GOOD']

        async def snapshots(self, tokens, preferred):
            batches.append((list(tokens), dict(preferred)))
            now = main.utcnow()
            if not preferred:  # screening round
                return {'OLD': dex_quote('OLD', 'OLD-CURVE', dex_id='pumpfun', at=now),
                        'GOOD': dex_quote('GOOD', 'GOOD-SWAP', at=now)}
            return {t: None for t in tokens}

        async def snapshot(self, token, preferred): return None

    class RPC:
        def __init__(self, *args, **kwargs): self.stats = {}

    monkeypatch.setattr(main, 'DexScreener', Dex)
    monkeypatch.setattr(main, 'Solana', RPC)
    try:
        await main.collect(recorder, once=True)
        assert batches[0] == (['OLD', 'GOOD'], {})
        assert batches[1][1] == {'GOOD': 'GOOD-SWAP'}
        tracks = dict(db.conn.execute('SELECT token,pair FROM observation_tracks'))
        assert tracks == {'GOOD': 'GOOD-SWAP'}
    finally:
        db.close()
