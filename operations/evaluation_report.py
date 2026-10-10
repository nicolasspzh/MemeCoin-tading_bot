"""Render an existing Phase-6 result as offline HTML; never run an evaluation."""
import argparse
import hashlib
import html
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo


BLOCKERS = {
    "no_observations": "Keine Beobachtungen im Testfenster",
    "too_few_observed_days": "Zu wenige Tage mit Kursbeobachtungen",
    "sparse_time_coverage": "Zeitliche Abdeckung zu gering",
    "missing_prices": "Zu viele Beobachtungen ohne Kurs",
    "legacy_or_missing_risk_data": "Aktuelle Risikoprüfungen fehlen",
    "incomplete_account_proof_coverage": "Kontobelege für Risikoprüfungen unvollständig",
    "too_few_observed_price_paths": "Zu wenige Handelspaare mit Folgekursen",
    "missing_or_sparse_same_pool_followups": "Folgekurse fehlen oder liegen zu weit auseinander",
    "synthetic_data": "Künstliche Daten, keine Marktevidenz",
    "previously_available_development_data": "Bereits bekannte Entwicklungsdaten, kein unabhängiger Test",
    "too_few_closed_trades": "Zu wenige abgeschlossene Trades",
    "too_few_distinct_traded_tokens": "Zu wenige unterschiedliche Coins mit abgeschlossenen Trades",
    "unresolved_open_positions": "Offene Positionen am Datenende",
    "unresolved_orders_at_boundary": "Nicht ausgeführte Orders am Datenende",
}


def esc(value):
    return html.escape(str(value), quote=True)


def number(value, *, percent=False):
    if value is None:
        return "nicht verfügbar"
    try:
        result = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError("Invalid numeric report field") from error
    if not result.is_finite() or abs(result) > Decimal('1e30'):
        raise ValueError("Non-finite or out-of-range report field")
    return f"{result * (100 if percent else 1):,.2f}" + (" %" if percent else "")


def swiss(value):
    if value is None:
        return "nicht verfügbar"
    date = datetime.fromisoformat(value)
    if date.tzinfo is None:
        raise ValueError("Report timestamp requires a timezone")
    return date.astimezone(ZoneInfo('Europe/Zurich')).strftime('%d.%m.%Y %H:%M:%S %Z')


def table(headers, rows):
    return '<div class="scroll"><table><thead><tr>' + ''.join(
        f'<th>{esc(h)}</th>' for h in headers
    ) + '</tr></thead><tbody>' + ''.join(
        '<tr>' + ''.join(f'<td>{esc(cell)}</td>' for cell in row) + '</tr>' for row in rows
    ) + '</tbody></table></div>'


def render(result, source_sha256):
    """Whitelist displayed fields; raw payloads, endpoints and local paths stay out."""
    if not isinstance(result, dict):
        raise ValueError("Expected a result object")
    waiting = result.get('status') == 'WAITING_FOR_WINDOW_END'
    if waiting:
        title = 'Auswertung noch gesperrt'
        body = '<p>Das unabhängige Testfenster ist noch nicht abgeschlossen. Keine Ergebnisbewertung.</p>'
        body += table(['Zeitraum', 'Schweizer Zeit'], [
            ['Beginn', swiss(result.get('test_start_utc'))],
            ['Ende des Testfensters (exklusiv)', swiss(result.get('test_end_exclusive_utc'))]])
        body += '<p>Zusätzlich die geplante Nachbeobachtung vollständig abwarten und erst danach die finale Sicherung auswerten. Das Testfensterende allein ist nicht das Sammelende.</p>'
    else:
        if result.get('version') != 1 or result.get('kind') not in (
                'DEVELOPMENT_DIAGNOSTIC', 'PROSPECTIVE_WINDOW_EVALUATION'):
            raise ValueError("Unsupported evaluation result")
        for key in ('assessment', 'inputs', 'data_quality', 'scenarios', 'quality_policy'):
            if not isinstance(result.get(key), dict):
                raise ValueError(f"Missing or invalid {key}")
        assessment, quality = result['assessment'], result['data_quality']
        source = result['inputs'].get('source')
        if source not in ('demo', 'dexscreener'):
            raise ValueError("Unknown data source")
        status = assessment.get('status')
        if status not in ('SYNTHETIC_ONLY', 'INSUFFICIENT_EVIDENCE', 'REVIEWABLE_HOLDOUT'):
            raise ValueError("Unknown assessment status")
        demo = source == 'demo'
        title = 'KÜNSTLICHE TESTDATEN – keine Marktergebnisse' if demo else 'Gespeicherte Marktdaten-Auswertung'
        blockers = assessment.get('blockers')
        if not isinstance(blockers, list):
            raise ValueError("Missing blocker list")
        if status == 'REVIEWABLE_HOLDOUT' and (demo or blockers or
                result.get('prospective') is not True or
                result['kind'] != 'PROSPECTIVE_WINDOW_EVALUATION'):
            raise ValueError("Contradictory review status")
        status_label = {'SYNTHETIC_ONLY': 'Nur synthetische Betriebsprobe',
                        'INSUFFICIENT_EVIDENCE': 'Evidenz reicht noch nicht aus',
                        'REVIEWABLE_HOLDOUT': 'Zur inhaltlichen Prüfung geeignet – keine Handelsfreigabe'}[status]
        body = f'<p><strong>Status laut Ergebnisdatei: {esc(status_label)}</strong></p>'
        body += f'<p>Erstellt: {esc(swiss(result.get("generated_at_utc")))}. '
        body += 'Dieser Bericht stellt eine vorhandene Ergebnisdatei dar; er bestätigt deren Herkunft nicht unabhängig.</p>'
        if demo:
            body += '<p class="notice">Alle Geldbeträge sind Simulationen mit künstlichen Kursen. Auch ein positiver Wert belegt keine profitable Strategie.</p>'
        body += '<h2>Offene Anforderungen</h2><ul>'
        body += ''.join(f'<li>{esc(BLOCKERS.get(b, b))}</li>' for b in blockers)
        body += '</ul>' if blockers else '<li>Keine Hindernisse in der Ergebnisdatei verzeichnet. Inhaltliche Prüfung bleibt erforderlich.</li></ul>'
        qrows = [
            ['Beobachtungen', quality.get('observations', 'nicht verfügbar')],
            ['Anteil mit Kurs', number(quality.get('priced_fraction'), percent=True)],
            ['Abdeckung der 5-Minuten-Zeitabschnitte', number(quality.get('active_5min_fraction'), percent=True)],
            ['Aktuelle Risikoprüfung unter Beobachtungen mit Kurs', number(quality.get('modern_risk_fraction'), percent=True)],
            ['Handelspaare mit mindestens zwei Kursen', quality.get('priced_pairs_with_followups', 'nicht verfügbar')],
            ['Anteil langer Lücken innerhalb desselben Handelspaars', number(quality.get('long_same_pool_gap_fraction'), percent=True)],
            ['Fensterbeginn', swiss(quality.get('window_start_utc'))],
            ['Fensterende (exklusiv)', swiss(quality.get('window_end_exclusive_utc'))]]
        body += '<h2>Datenabdeckung</h2>' + table(['Merkmal', 'Wert'], qrows)
        body += '<p>Gute Folgekurse der aufgenommenen Coins belegen keine vollständige Marktabdeckung. Zurückgestellte Kandidaten, unvollständige Pool-Erkennung und fehlende Coins bleiben eine Einschränkung. Deren Umfang wird aus dieser Ergebnisdatei nicht quantifiziert.</p>'
        body += '<h2>Vorab festgelegte Anforderungen</h2>'
        body += table(['Regel (Protokollschlüssel)', 'Wert aus Ergebnisdatei'], sorted(result['quality_policy'].items()))
        rows, costs, unresolved = [], [], []
        definitions = result.get('scenario_definitions', {})
        for scenario, runs in result['scenarios'].items():
            for run in runs:
                m, seed = run['metrics'], run['seed']
                prefix = [scenario, seed]
                positions = m.get('open_positions')
                rows.append(prefix + [number(m.get('completed_trades')),
                    number(m.get('distinct_closed_trade_tokens')), number(m.get('net_realized_pnl_usd')),
                    number(m.get('total_equity_mark_usd')), number(m.get('max_sampled_drawdown_pct')),
                    len(positions) if isinstance(positions, list) else 'nicht verfügbar'])
                costs.append(prefix + [number(m.get(k)) for k in (
                    'successful_fees_usd', 'failed_fees_usd', 'priority_fees_included_usd', 'slippage_and_impact_usd')])
                unresolved.append(prefix + [json.dumps(m.get('order_status_counts', {}), ensure_ascii=False),
                    json.dumps(positions, ensure_ascii=False) if positions is not None else 'nicht verfügbar'])
        body += '<h2>Alle Simulationsläufe</h2>'
        body += '<p>baseline = normale Kostenannahmen; stress = erhöhte Kosten, Verzögerung und Ausfallrisiken. Seeds steuern Zufallsvarianten desselben Datensatzes; sie sind keine unabhängigen Stichproben. Kein bester Lauf wird ausgewählt.</p>'
        body += table(['Szenario', 'Seed', 'Geschlossene Trades', 'Coins mit geschlossenen Trades',
                       'Netto realisiert USD', 'Geschätztes Gesamtvermögen USD', 'Größter beobachteter Rückgang %', 'Offene Positionen'], rows) if rows else '<p>Keine Simulationsläufe verfügbar. Das ist kein Ergebnis von null Gewinn oder null Risiko.</p>'
        body += '<p>Netto realisiert berücksichtigt modellierte Kosten. Geschätztes Vermögen enthält bewertete offene Positionen und Reserven; es ist kein garantierter Verkaufserlös. Der Rückgang wird nur an gespeicherten Messpunkten erfasst. Null Trades erlauben kein Profitabilitätsurteil.</p>'
        body += '<h2>Kosten je Lauf (USD)</h2>' + table(
            ['Szenario', 'Seed', 'Gebühren erfolgreicher Ausführungen', 'Gebühren fehlgeschlagener Versuche',
             'Darin enthaltene Prioritätsgebühren', 'Slippage und Preiseinfluss'], costs)
        body += '<p>Prioritätsgebühren sind bereits enthalten, nicht nochmals addieren. Slippage und Preiseinfluss stecken bereits in den simulierten Ausführungspreisen.</p>'
        body += '<h2>Offene Positionen und Orderzustände</h2>' + table(
            ['Szenario', 'Seed', 'Orderzustände', 'Offene Positionen und Bewertungswarnungen'], unresolved)
        # Only cost assumptions, never dump settings containing endpoints or private fields.
        assumptions = []
        for scenario, definition in definitions.items():
            for section, keys in (('settings', ('slippage_bps', 'fixed_fee_usd')),
                                  ('execution', ('latency_seconds', 'priority_fee_usd', 'failure_probability'))):
                for key in keys:
                    assumptions.append([scenario, key, number(definition.get(section, {}).get(key))])
        body += '<h2>Ausgewählte Modellannahmen</h2>' + table(['Szenario', 'Parameter', 'Wert'], assumptions)
        body += '<p>Die vollständigen Annahmen stehen in der ursprünglichen result.json. Dieser Bericht ändert weder Anforderungen noch Parameter und erteilt keine Freigabe für echtes Geld.</p>'
    return '''<!doctype html><html lang="de"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MemeCoin – Auswertungsbericht</title><style>
body{font:16px/1.6 system-ui,sans-serif;background:#f1f5f9;color:#152438;margin:0}
main{max-width:1180px;margin:auto;padding:28px}h1{line-height:1.2}h2{margin-top:36px}
.notice{background:#fff0cb;padding:18px;border-left:5px solid #ac6a00}
.scroll{overflow-x:auto}table{border-collapse:collapse;background:white;width:100%}
td,th{border:1px solid #d2dce8;text-align:left;padding:10px;max-width:500px;overflow-wrap:anywhere}
th{background:#e3ebf6}footer{margin-top:30px;font-size:13px;overflow-wrap:anywhere}
</style><main><h1>''' + esc(title) + '</h1>' + body + (
        '<footer>Offline-Bericht · SHA-256 der gelesenen Ergebnisdatei: ' + esc(source_sha256) +
        '<br>Kein Zugriff auf Datenbanken, Netzwerk, Telegram oder laufende Dienste.</footer></main></html>')


def build_report(source, output):
    raw = Path(source).read_bytes()
    result = json.loads(raw)
    page = render(result, hashlib.sha256(raw).hexdigest())
    # Rendering must succeed before creating output; never overwrite evidence.
    with Path(output).open('x', encoding='utf-8') as stream:
        stream.write(page)
    return Path(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        build_report(args.result, args.out)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(f'Bericht nicht erstellt: {type(error).__name__}')
        return 2
    print(f'Offline-Bericht erstellt: {args.out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
