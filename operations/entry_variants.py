"""Isolated entry-policy research. No orders, database, credentials or network."""
import argparse
import hashlib
import html
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D, ROUND_DOWN
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from backtesting.replay import Observation
from config.settings import Settings
from data.models import MintRisk, Snapshot, Wallet
from trading.execution import Execution, valuation_settings
from trading.paper_wallet import equity
from trading.strategy import decide


class ResearchPolicy(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, frozen=True)
    # Hypotheses chosen before any comparison on R2 market observations.
    max_gain_5m: D = Field(default=D('.10'), gt=0, le=1)
    max_gain_15m: D = Field(default=D('.25'), gt=0, le=2)
    max_extension_15m: D = Field(default=D('.25'), gt=0, le=2)
    max_gap_seconds: int = Field(default=60, ge=1, le=120)
    anchor_tolerance_seconds: int = Field(default=30, ge=0, le=60)
    account_risk_fraction: D = Field(default=D('.006'), gt=0, le=D('.01'))
    extra_adverse_fraction: D = Field(default=D('.02'), ge=0, le=D('.20'))
    failed_attempt_allowance: int = Field(default=1, ge=0, le=10)


def anti_fomo(snapshot, history, now, policy):
    """Use only already available, same-token/pool quotes. Never interpolate."""
    if snapshot.price_usd is None or Observation(0, snapshot).available_at > now:
        return {'approved': False, 'reasons': ['missing_or_future_current_quote'], 'metrics': {}}
    start = snapshot.received_at - timedelta(seconds=900 + policy.anchor_tolerance_seconds)
    by_time = {}
    for row in history:
        s = row.snapshot
        if (s.token, s.pair, s.source) != (snapshot.token, snapshot.pair, snapshot.source):
            continue
        if not start <= s.received_at <= snapshot.received_at or row.available_at > now:
            continue
        if s.received_at in by_time and by_time[s.received_at] != s.price_usd:
            return {'approved': False, 'reasons': ['conflicting_history'], 'metrics': {}}
        by_time[s.received_at] = s.price_usd
    if snapshot.received_at in by_time and by_time[snapshot.received_at] != snapshot.price_usd:
        return {'approved': False, 'reasons': ['conflicting_history'], 'metrics': {}}
    by_time[snapshot.received_at] = snapshot.price_usd
    quotes = sorted(by_time.items())
    reasons, metrics = [], {}
    for seconds, cap in ((300, policy.max_gain_5m), (900, policy.max_gain_15m)):
        target = snapshot.received_at - timedelta(seconds=seconds)
        anchors = [(t, p) for t, p in quotes if target - timedelta(seconds=policy.anchor_tolerance_seconds) <= t <= target]
        label = f'{seconds // 60}m'
        if not anchors:
            reasons.append('missing_history_' + label)
            continue
        anchor = anchors[-1]
        window = [(t, p) for t, p in quotes if t >= anchor[0]]
        if any(p is None for _, p in window) or any(
                (b[0] - a[0]).total_seconds() > policy.max_gap_seconds for a, b in zip(window, window[1:])):
            reasons.append('incomplete_history_' + label)
            continue
        gain = snapshot.price_usd / anchor[1] - 1
        metrics['gain_' + label] = str(gain)
        metrics['anchor_' + label] = anchor[0].isoformat()
        if gain > cap:
            reasons.append('excessive_gain_' + label)
        if seconds == 900:
            extension = snapshot.price_usd / min(p for _, p in window) - 1
            metrics['extension_above_15m_low'] = str(extension)
            if extension > policy.max_extension_15m:
                reasons.append('excessive_extension_15m')
    return {'approved': not reasons, 'reasons': reasons, 'metrics': metrics}


def risk_size(*, capital, free_cash, baseline_cap, liquidity, stop_fraction,
              settings, execution, policy):
    """Conservative planning allowance, NOT a bound on actual losses.

    Linear stop + two-sided fees/slippage + extra adverse-move allowance;
    quadratic approximate two-sided impact; entry/exit and failed-attempt fees.
    Baseline allocation and liquidity-participation limits can only shrink.
    """
    values = (capital, free_cash, baseline_cap, liquidity, stop_fraction)
    if any(not isinstance(v, D) or not v.is_finite() for v in values):
        raise ValueError('Finite Decimal inputs required')
    if min(capital, free_cash, baseline_cap, liquidity) < 0 or not 0 < stop_fraction < 1:
        raise ValueError('Invalid sizing inputs')
    ceiling = min(baseline_cap, free_cash, liquidity * settings.max_pool_fraction)
    limit = capital * policy.account_risk_fraction
    fixed = (2 + policy.failed_attempt_allowance) * (settings.fixed_fee_usd + execution.priority_fee_usd)
    slope = stop_fraction + 2 * (settings.fee_bps + settings.slippage_bps) / 10000 + policy.extra_adverse_fraction

    def loss(budget):
        return fixed + budget * slope + 4 * budget * budget / liquidity

    result = {'budget_usd': '0', 'planned_loss_usd': None, 'risk_limit_usd': str(limit),
              'ceiling_usd': str(ceiling), 'fixed_cost_allowance_usd': str(fixed),
              'stop_fraction': str(stop_fraction), 'approved': False, 'reason': 'no_affordable_position'}
    if ceiling <= 0 or liquidity <= 0 or limit <= fixed:
        return result
    lo, hi = D(0), ceiling
    for _ in range(100):
        mid = (lo + hi) / 2
        if loss(mid) <= limit:
            lo = mid
        else:
            hi = mid
    budget = lo.quantize(D('.000001'), rounding=ROUND_DOWN)
    if budget <= settings.fixed_fee_usd + execution.priority_fee_usd:
        return result
    result.update(budget_usd=str(budget), planned_loss_usd=str(loss(budget)),
                  approved=True, reason='within_planning_budget')
    return result


def compare_entry(snapshot, previous, history, wallet, now, *, settings=None,
                  execution=None, policy=None, pending_buys=0, reserved_cash=D(0)):
    """Four advisory decisions on identical inputs. Never alters wallet/history.

    Exits remain the original strategy's decision in every variant. This is not
    a portfolio replay: variants do not own wallets and no fills are generated.
    """
    settings = settings or Settings()
    execution = execution or Execution.from_settings(settings)
    policy = policy or ResearchPolicy()
    if not isinstance(pending_buys, int) or pending_buys < 0 or not reserved_cash.is_finite() or reserved_cash < 0:
        raise ValueError('Invalid reservations')
    if previous is not None and ((previous.token, previous.pair, previous.source) !=
            (snapshot.token, snapshot.pair, snapshot.source) or Observation(0, previous).available_at > now):
        previous = None
    decision = decide(snapshot, previous, wallet, now, settings)
    capital = equity(wallet, valuation_settings(settings, execution))
    free = max(D(0), wallet.cash - reserved_cash)
    cap = min(free, capital * settings.position_fraction)
    action, reasons = decision.action, list(decision.reasons)
    if action == 'BUY' and len(wallet.positions) + pending_buys >= settings.max_positions:
        action, reasons = 'SKIP', ['position_limit_including_pending']
    if action == 'BUY' and cap <= settings.fixed_fee_usd + execution.priority_fee_usd:
        action, reasons = 'SKIP', ['insufficient_unreserved_cash']
    gate = sizing = None
    if action == 'BUY':
        gate = anti_fomo(snapshot, history, now, policy)
        sizing = risk_size(capital=capital, free_cash=free, baseline_cap=cap,
                           liquidity=snapshot.liquidity_usd or D(0), stop_fraction=settings.stop_loss_fraction,
                           settings=settings, execution=execution, policy=policy)
    variants = {}
    for name, fomo, sized in (('baseline', False, False), ('anti_fomo', True, False),
                              ('risk_sizing', False, True), ('combined', True, True)):
        a, why, budget = action, list(reasons), cap if action == 'BUY' else D(0)
        if a == 'BUY':
            if fomo and not gate['approved']:
                a, why = 'SKIP', gate['reasons']
            if sized and not sizing['approved']:
                a, why = 'SKIP', [*why, sizing['reason']]
            if sized:
                budget = D(sizing['budget_usd'])
            if a != 'BUY':
                budget = D(0)
        variants[name] = {'action': a, 'reasons': why, 'proposed_budget_usd': str(budget)}
    return {'variants': variants, 'anti_fomo': gate, 'risk_sizing': sizing}


def synthetic_cases():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for name, end_price, gap in (('Ruhiger Anstieg', '1.03', False),
                                 ('Starker Kurssprung', '1.40', False),
                                 ('Lücke in der Historie', '1.03', True)):
        quotes = []
        for seconds in range(0, 901, 20):
            if gap and 180 <= seconds <= 280:
                continue
            now = start + timedelta(seconds=seconds)
            quotes.append(Snapshot(token='DEMO', pair='POOL', source='demo', received_at=now,
                pair_created_at=start-timedelta(minutes=5), price_usd=D(end_price if seconds == 900 else '1'),
                liquidity_usd=D('20000'), volume_5m_usd=D('5000'), buys_5m=60, sells_5m=20,
                mint_risk=MintRisk(checked_at=now, supported_program=True, mint_authority=False,
                                  freeze_authority=False, top10_account_fraction=D('.25'))))
        yield name, quotes


def demo(out):
    settings, policy = Settings(), ResearchPolicy()
    cases = []
    for name, quotes in synthetic_cases():
        rows = [Observation(i+1, q) for i, q in enumerate(quotes)]
        comparison = compare_entry(quotes[-1], quotes[-2], rows, Wallet(), quotes[-1].received_at,
                                   settings=settings, policy=policy)
        cases.append({'name': name, 'synthetic_quotes': [q.model_dump(mode='json') for q in quotes], **comparison})
    from backtesting.evaluation import code_digest
    result = {'kind': 'SYNTHETIC_ENTRY_RULE_TEST', 'market_data_used': False, 'orders_created': 0,
              'profitability_evaluated': False, 'policy': policy.model_dump(mode='json'),
              'baseline_core_sha256': code_digest(),
              'variant_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'cases': cases}
    out.mkdir(parents=True, exist_ok=False)
    (out/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    e = html.escape
    rows = ''.join('<tr><td>'+e(case['name'])+'</td>'+''.join(
        '<td>'+e(v['action'])+'<br>'+e(v['proposed_budget_usd'])+' USD</td>'
        for v in case['variants'].values())+'</tr>' for case in cases)
    page = '''<!doctype html><html lang="de"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Einstiegsregeln – künstliche Testfälle</title><style>body{font:17px/1.6 system-ui;background:#f2f5fa;color:#16243a;margin:30px auto;max-width:1050px;padding:20px}table{border-collapse:collapse;background:white;width:100%}td,th{border:1px solid #cad5e4;padding:14px;text-align:left}.scroll{overflow:auto}.notice{padding:18px;background:#fff0cc}</style>
<h1>Zwei neue Regeln für die Forschung</h1><p class="notice"><strong>Künstliche Testfälle. Keine Trades, keine Renditeberechnung, kein Markttest.</strong> Die Tabelle zeigt nur, welche Einstiegsanfragen freigegeben oder blockiert würden.</p>
<div class="scroll"><table><tr><th>Testfall</th><th>Bisherige Regeln</th><th>Anti-FOMO</th><th>Risikogröße</th><th>Kombiniert</th></tr>'''+rows+'''</table></div>
<p>BUY = Einstieg vorgeschlagen; SKIP = Einstieg blockiert. Der Betrag ist ein vorgeschlagenes Budget, keine Ausführung.</p>
<h2>Anti-FOMO: erste Testannahmen</h2><p>Mehr als 10 % Anstieg über 5 Minuten, mehr als 25 % über 15 Minuten oder mehr als 25 % Abstand zum beobachteten 15-Minuten-Tief blockieren den Einstieg. Fehlende Historie oder Abstände über 60 Sekunden blockieren ebenfalls. Es werden nur bereits verfügbare Kurse desselben Coins und Pools verwendet.</p>
<h2>Positionsgröße nach geplantem Risiko</h2><p>Planungsbudget: 0,6 % des Handelskapitals inklusive Stop-Abstand, Gebühren, Slippage, geschätztem Preiseinfluss, einem Fehlversuch und 2 % zusätzlichem Kursbewegungspuffer. Die bisherige Positionsobergrenze bleibt bestehen. Das ist keine Garantie eines maximalen Verlusts.</p>
<p>Diese Werte sind nicht optimiert. Die Varianten können gute Trades aussortieren oder zu kleinen Positionen führen. Größere Kurslücken, illiquide Pools und weitere Fehlversuche können das geplante Risiko überschreiten.</p>
<p>Der laufende Sammler und die eingefrorene R2-Strategie sind unverändert. Diese Ergänzung ist noch nicht an den Paper-Dienst angeschlossen. Vor Einsatz braucht sie Ausführungsprüfungen und einen getrennten, vorab festgelegten Vergleich.</p></html>'''
    (out/'Vorschau.html').write_text(page)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = demo(args.out)
    print(json.dumps({'status': result['kind'], 'cases': len(result['cases']), 'output': str(args.out)}))


if __name__ == '__main__':
    main()
