from datetime import timedelta
from decimal import Decimal as D
import json

import pytest

from backtesting.replay import Observation
from config.settings import Settings
from data.models import Position, Wallet
from operations.entry_variants import (ResearchPolicy, anti_fomo, compare_entry,
                                       demo, risk_size, synthetic_cases)
from trading.execution import Execution


@pytest.fixture
def history():
    _, quotes = next(synthetic_cases())
    return [Observation(i+1, q) for i, q in enumerate(quotes)]


def gate(history, **changes):
    current = history[-1].snapshot.model_copy(update=changes)
    earlier = history[:-1]
    return anti_fomo(current, earlier, current.received_at, ResearchPolicy())


def sizing(**changes):
    args = dict(capital=D('50'), free_cash=D('50'), baseline_cap=D('2.5'),
                liquidity=D('20000'), stop_fraction=D('.12'), settings=Settings(),
                execution=Execution(), policy=ResearchPolicy())
    return risk_size(**(args | changes))


def test_three_synthetic_cases_exercise_variants(tmp_path):
    out = tmp_path/'new'
    result = demo(out)
    calm, pump, gap = result['cases']
    assert calm['variants']['combined']['action'] == 'BUY'
    assert D(calm['variants']['combined']['proposed_budget_usd']) < D('2.5')
    assert pump['variants']['baseline']['action'] == 'BUY'
    assert pump['variants']['anti_fomo']['action'] == 'SKIP'
    assert gap['variants']['baseline']['action'] == 'BUY'
    assert gap['variants']['combined']['action'] == 'SKIP'
    assert not result['profitability_evaluated'] and result['orders_created'] == 0
    assert 'Keine Trades' in (out/'Vorschau.html').read_text()
    with pytest.raises(FileExistsError):
        demo(out)


def test_threshold_is_inclusive(history):
    assert gate(history, price_usd=D('1.10'))['approved']
    assert 'excessive_gain_5m' in gate(history, price_usd=D('1.10001'))['reasons']


def test_trough_extension_catches_rebound_with_small_endpoint_gain(history):
    altered = [Observation(r.id, r.snapshot.model_copy(update={'price_usd':D('.5')}))
               if r.id == 15 else r for r in history]
    result = gate(altered)
    assert 'excessive_extension_15m' in result['reasons']
    assert result['metrics']['gain_15m'] == '0.03'


def test_short_history_never_passes(history):
    result = gate(history[20:])
    assert not result['approved'] and 'missing_history_15m' in result['reasons']


def test_other_pool_or_source_cannot_supply_missing_history(history):
    mixed = [Observation(r.id, r.snapshot.model_copy(update={'pair':'OTHER'}))
             if r.id < 10 else r for r in history]
    assert 'missing_history_15m' in gate(mixed)['reasons']
    mixed = [Observation(r.id, r.snapshot.model_copy(update={'source':'dexscreener'}))
             if r.id < 10 else r for r in history]
    assert 'missing_history_15m' in gate(mixed)['reasons']


def test_future_and_late_information_cannot_change_current_gate(history):
    current = history[-1].snapshot
    expected = anti_fomo(current, history, current.received_at, ResearchPolicy())
    future = current.model_copy(update={'received_at':current.received_at+timedelta(seconds=20), 'price_usd':D('.001')})
    assert anti_fomo(current, history+[Observation(90, future)], current.received_at, ResearchPolicy()) == expected
    late = history[0].snapshot.model_copy(deep=True)
    late.mint_risk.checked_at = current.received_at+timedelta(seconds=1)
    altered = [Observation(1, late), *history[1:]]
    assert 'missing_history_15m' in anti_fomo(current, altered, current.received_at, ResearchPolicy())['reasons']


def test_conflicts_block_and_duplicate_rows_do_not_change_result(history):
    current = history[-1].snapshot
    policy = ResearchPolicy()
    expected = anti_fomo(current, history, current.received_at, policy)
    assert anti_fomo(current, history+history, current.received_at, policy) == expected
    conflict = history[10].snapshot.model_copy(update={'price_usd':D('2')})
    assert 'conflicting_history' in anti_fomo(current, history+[Observation(90, conflict)], current.received_at, policy)['reasons']


def test_unavailable_current_or_unrelated_previous_is_not_usable(history):
    current = history[-1].snapshot.model_copy(deep=True)
    current.mint_risk.checked_at += timedelta(seconds=1)
    assert not anti_fomo(current, history[:-1], current.received_at, ResearchPolicy())['approved']
    current = history[-1].snapshot
    previous = history[-2].snapshot.model_copy(update={'token':'WRONG'})
    result = compare_entry(current, previous, history, Wallet(), current.received_at)
    assert all(v['action']=='SKIP' for v in result['variants'].values())


def test_missing_price_and_history_gap_block(history):
    changed = [Observation(r.id, r.snapshot.model_copy(update={'price_usd':None}))
               if r.id == 10 else r for r in history]
    assert not gate(changed)['approved']
    changed = [r for r in history if not 10 <= r.id <= 15]
    assert 'incomplete_history_15m' in gate(changed)['reasons']


def test_sizing_respects_risk_and_existing_caps():
    result = sizing()
    budget = D(result['budget_usd'])
    assert result['approved'] and 0 < budget <= D('2.5')
    expected_loss = D('.075') + budget * D('.166') + 4*budget*budget/D('20000')
    assert D(result['planned_loss_usd']) == expected_loss
    assert expected_loss <= D('.30')
    assert D(sizing(free_cash=D('.5'))['budget_usd']) <= D('.5')
    assert D(sizing(liquidity=D('500'))['budget_usd']) <= D('.5')


def test_wider_stop_and_higher_costs_reduce_budget():
    normal = D(sizing()['budget_usd'])
    assert D(sizing(stop_fraction=D('.25'))['budget_usd']) < normal
    assert D(sizing(settings=Settings(slippage_bps=D('300')))['budget_usd']) < normal
    assert D(sizing(execution=Execution(priority_fee_usd=D('.04')))['budget_usd']) < normal


def test_risk_sizing_does_not_escalate_after_loss():
    assert D(sizing(capital=D('40'))['budget_usd']) < D(sizing()['budget_usd'])


def test_unaffordable_costs_block_instead_of_ignoring_fees():
    result = sizing(capital=D('1'), baseline_cap=D('.05'))
    assert not result['approved'] and result['budget_usd'] == '0'
    assert not sizing(liquidity=D('0'))['approved']


@pytest.mark.parametrize('changes', [{'stop_fraction':D('0')}, {'free_cash':D('-1')}, {'capital':D('NaN')}])
def test_invalid_sizing_inputs_rejected(changes):
    with pytest.raises(ValueError):
        sizing(**changes)


def test_base_risk_veto_and_pending_limit_remain_effective(history):
    current, previous = history[-1].snapshot, history[-2].snapshot
    risky = current.model_copy(update={'liquidity_usd':D('1')})
    result = compare_entry(risky, previous, history, Wallet(), current.received_at)
    assert all(v['action']=='SKIP' for v in result['variants'].values())
    result = compare_entry(current, previous, history, Wallet(), current.received_at, pending_buys=3)
    assert all(v['action']=='SKIP' for v in result['variants'].values())
    result = compare_entry(current, previous, history, Wallet(), current.received_at, reserved_cash=D('50'))
    assert all(v['action']=='SKIP' for v in result['variants'].values())


def test_exit_never_blocked_by_entry_filter(history):
    current = history[-1].snapshot.model_copy(update={'price_usd':D('.8')})
    wallet = Wallet(positions={'DEMO':Position(token='DEMO', pair='POOL', quantity=D('1'),
        entry_cost=D('1'), entry_price=D('1'), opened_at=current.received_at-timedelta(seconds=100),
        entry_snapshot_id=1, peak_price=D('1'), last_price=D('.8'))})
    result = compare_entry(current, history[-2].snapshot, [], wallet, current.received_at)
    assert all(v['action']=='SELL' and 'stop_loss' in v['reasons'] for v in result['variants'].values())
    assert result['anti_fomo'] is None


def test_repeatable_pure_comparison_does_not_mutate_wallet_or_history(history):
    wallet = Wallet()
    before = wallet.model_dump_json(), [r.snapshot.model_dump_json() for r in history]
    current, previous = history[-1].snapshot, history[-2].snapshot
    one = compare_entry(current, previous, history, wallet, current.received_at)
    two = compare_entry(current, previous, history, wallet, current.received_at)
    assert one == two
    assert before == (wallet.model_dump_json(), [r.snapshot.model_dump_json() for r in history])
