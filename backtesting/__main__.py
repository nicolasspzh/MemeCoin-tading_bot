import argparse
import csv
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from config.settings import load_settings
from backtesting.replay import Execution, Replay, quality_profile, read_observations


def write_csv(path: Path, rows: list[dict], fields: list[str]):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def freeze_input(path: Path, records, source: str):
    connection = sqlite3.connect(path)
    try:
        with connection:
            connection.executescript("""
                CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE snapshots(id INTEGER PRIMARY KEY, token TEXT, pair TEXT, received_at REAL, payload TEXT);
                CREATE TABLE risk_evidence(sha256 TEXT PRIMARY KEY, payload TEXT NOT NULL);
            """)
            connection.execute("INSERT INTO metadata VALUES('source',?)", (source,))
            connection.executemany("INSERT INTO snapshots VALUES(?,?,?,?,?)", [
                (r.id, r.snapshot.token, r.snapshot.pair, r.snapshot.received_at.timestamp(), r.snapshot.model_dump_json())
                for r in records])
            for record in records:
                risk = record.snapshot.mint_risk
                holder = risk.holder_risk if risk else None
                if holder and holder.evidence_sha256:
                    if holder.evidence_payload is None:
                        raise ValueError("Missing risk evidence for frozen input")
                    payload = json.dumps(holder.evidence_payload, sort_keys=True, separators=(",", ":"))
                    if hashlib.sha256(payload.encode()).hexdigest() != holder.evidence_sha256:
                        raise ValueError("Invalid risk evidence fingerprint for frozen input")
                    connection.execute("INSERT OR IGNORE INTO risk_evidence VALUES(?,?)", (holder.evidence_sha256, payload))
    finally:
        connection.close()


def source_code_digest() -> str:
    root = Path(__file__).resolve().parents[1]
    fingerprint = hashlib.sha256()
    for folder in ("backtesting", "trading", "config", "data"):
        for path in sorted((root / folder).glob("*.py")):
            fingerprint.update(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes())
    return fingerprint.hexdigest()


def notes(result: dict) -> str:
    profile = result["data_quality"]
    lines = ["# Backtest-Lauf", "", f"Erstellt: {result['generated_at_utc']}",
             f"Quelle: `{result['input']['source']}`", "",
             f"{profile['observations']} Beobachtungen, {profile['tokens']} Coins, "
             f"{profile['pairs_with_multiple_quotes']} Pools mit Folgebeobachtungen.",
             f"Zeitraum UTC: {profile['start_utc']} bis {profile['end_utc']}.", "",
             "| Szenario | Abgeschlossene Trades | Netto realisiert (USD) | Cash (USD) | Reserve (USD) | Owner (USD) |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for name, scenario in result["scenarios"].items():
        m = scenario["metrics"]
        lines.append(f"| {name} | {m['completed_trades']} | {Decimal(m['net_realized_pnl_usd']):.4f} | "
                     f"{Decimal(m['ending_cash_usd']):.4f} | {Decimal(m['news_reserve_usd']):.4f} | "
                     f"{Decimal(m['owner_profit_usd']):.4f} |")
    lines += ["", "## Aussagekraft", "", *[f"- {item}" for item in result["limitations"]], "",
              "## Ausführungsmodell", "",
              "- Neue Wallet mit 50 USD pro Szenario; unveränderte Risk-/Momentum-Regeln, keine Optimierung.",
              "- Quote ab Empfangszeit verfügbar; Signale und Ausführung warten auf alle Risikomerkmale. Kein Lesen späterer Labels.",
              "- Marktorder mit am Signal eingefrorenem USD-Budget; Cash und Positionsplätze werden reserviert.",
              "- Fill erst an einer späteren Quote desselben Pools nach der Mindestlatenz. Keine interpolierten Preise.",
              "- Ohne passende Quote vor dem 120-Sekunden-Limit verfällt die Order; am Datenende bleibt sie unausgeführt.",
              "- Gebühren, Slippage und Priority Fees sind Annahmen. Ausfälle werden mit dokumentiertem Seed simuliert.",
              "- Bei zu großer ungünstiger Preisbewegung gilt die Order als fehlgeschlagen; Fix-/Priority-Kosten werden berechnet.",
              "- Mechanisch unsichere oder unbekannte Ausstiege bleiben offen; fehlgeschlagene Verkäufe mindern spätere ausschüttbare Gewinne.",
              "- Liquiditätsgrenzen nutzen den gemeldeten USD-Wert. Zusatzimpact ≈ 2 × Orderwert / Pool-Liquidität; "
              "das ist eine vereinfachte Annahme für einen ausgeglichenen Constant-Product-Pool, kein tatsächlicher AMM-Replay.",
              "- Offene Positionen werden am Ende nicht zwangsverkauft. Markierte Werte enthalten letzte bekannte Kurse; "
              "Warnungen zu veralteten/illiquiden Positionen stehen in result.json.",
              "- Maximaler Drawdown beruht auf beobachteten Zeitpunkten und Gesamtvermögen inklusive Reserve/Owner-Profit.",
              "- Trefferquote bleibt ohne abgeschlossene Trades null. Profit Factor bleibt bei fehlendem Verlustnenner null.",
              "", "## Dateien", "",
              "- `input.sqlite3`: gelesene Eingabebeobachtungen und referenzierte Account-Belege, ohne Live-Wallet/Orders.",
              "- `result.json`: Konfiguration, Datenprofil, Quell-/Code-Hashes, Metriken und Einschränkungen.",
              "- Je Szenario: `orders.csv`, `fills.csv`, `equity.csv` und `decisions.json` als Prüfspur.", "",
              "## Reproduktion", "", "```bash",
              f"python -m backtesting --db {result['output_directory']}/input.sqlite3 "
              f"--out runtime/backtests/reproduction --scenario {result['requested_scenario']} --seed {result['seed']}"
              + (" --allow-demo" if result["input"]["source"] == "demo" else ""),
              "```", "", "Die Parameter aus result.json und derselbe Code-Hash müssen für einen identischen Lauf übereinstimmen."]
    return "\n".join(lines) + "\n"


def run(args) -> dict:
    settings = load_settings()
    records, provenance = read_observations(args.db, allow_demo=args.allow_demo)
    profile = quality_profile(records)
    args.out.mkdir(parents=True, exist_ok=False)
    freeze_input(args.out / "input.sqlite3", records, provenance["source"])
    _, frozen = read_observations(args.out / "input.sqlite3", allow_demo=args.allow_demo)
    if frozen["snapshots_sha256"] != provenance["snapshots_sha256"]:
        raise ValueError("Frozen input does not match the analyzed source")
    scenarios = {"baseline": (settings, Execution(seed=args.seed)),
                 "stress": (settings.model_copy(update={"slippage_bps": Decimal("300")}),
                            Execution(latency_seconds=5, priority_fee_usd=Decimal("0.02"),
                                      failure_probability=0.10, max_adverse_move_bps=Decimal("300"), seed=args.seed))}
    selected = scenarios if args.scenario == "both" else {args.scenario: scenarios[args.scenario]}
    result = {"generated_at_utc": datetime.now(UTC).isoformat(), "input": provenance,
              "output_directory": str(args.out), "source_code_sha256": source_code_digest(),
              "requested_scenario": args.scenario, "seed": args.seed, "data_quality": profile,
              "scenarios": {}, "limitations": []}
    for name, (strategy_settings, execution) in selected.items():
        simulator = Replay(strategy_settings, execution)
        metrics = simulator.run(records)
        result["scenarios"][name] = {
            "strategy_settings": strategy_settings.model_dump(mode="json", exclude={"solana_rpc_url", "solana_rpc_fallback_urls", "dex_base_url"}),
            "execution": execution.model_dump(mode="json"), "metrics": metrics}
        destination = args.out / name
        destination.mkdir()
        write_csv(destination / "orders.csv", simulator.orders,
                  ["id", "token", "pair", "action", "signal_snapshot_id", "signal_at", "eligible_at", "expires_at",
                   "budget_usd", "reserved_cash_usd", "signal_price_usd", "status", "result_reason", "resolved_at", "failed_fee_usd"])
        write_csv(destination / "fills.csv", simulator.fills,
                  ["order_id", "side", "token", "pair", "signal_snapshot_id", "snapshot_id", "signal_at", "simulated_at",
                   "quote_received_at", "effective_delay_seconds", "quantity", "price", "fee", "cash_flow", "realized_pnl",
                   "liquidity_usd", "impact_bps", "slippage_cost_usd", "entry_snapshot_id", "priority_fee_usd", "net_trade_pnl"])
        write_csv(destination / "equity.csv", simulator.curve,
                  ["at", "total_marked_equity_usd", "cash_usd", "news_reserve_usd", "owner_profit_usd", "open_positions"])
        (destination / "decisions.json").write_text(json.dumps(simulator.decisions, indent=2) + "\n")
    limits = result["limitations"]
    if provenance["source"] == "demo":
        limits.append("Synthetische Daten: ausschließlich Funktionsprüfung, kein Ergebnis zur Marktprofitabilität.")
    if not profile["pairs_with_multiple_quotes"]:
        limits.append("Kein Pool hat mehrere Beobachtungen; keine historische Kursentwicklung testbar.")
    if profile["duration_seconds"] < 86400:
        limits.append("Weniger als ein Tag Daten; keine Abdeckung verschiedener Tage oder Marktphasen.")
    if profile["gaps_over_120_seconds"]:
        limits.append(f"{profile['gaps_over_120_seconds']} Beobachtungsabstände über 120 Sekunden; "
                      "Lücken werden nicht interpoliert und können Momentum-Signale oder Orderausführung verhindern.")
    if all(s["metrics"]["completed_trades"] == 0 for s in result["scenarios"].values()):
        limits.append("Keine abgeschlossenen Trades: Nullgewinn und Null-Drawdown sind kein Nachweis einer funktionierenden Strategie.")
    if any(profile["risk_data_status"].get(key, 0) for key in ("missing", "missing_concentration", "missing_verified_holder_risk")):
        limits.append("Fehlende On-Chain-Risikodaten verhindern Einstiege; die Filter wurden nicht gelockert.")
    if profile["risk_data_status"].get("holder_analysis_unsupported_pool", 0):
        limits.append("Nicht unterstützte Pool-Programme verhindern die verifizierte Halterprüfung und blockieren Einstiege.")
    if settings.require_verified_holder_risk and provenance["source"] == "dexscreener" and any(
            r.snapshot.mint_risk is not None and r.snapshot.mint_risk.risk_version != 3 for r in records):
        limits.append("Alte Marktbeobachtungen ohne Phase-3-Halterdaten erlauben unter den aktuellen Standardregeln keine Einstiege.")
    if profile["risk_data_status"].get("unsupported_program", 0):
        limits.append("Nicht unterstützte Token-Programme werden übersprungen.")
    if profile["risk_data_status"].get("blocked_extensions", 0):
        limits.append("Token-2022-Erweiterungen mit nicht unterstützter Übertragungs-/Berechtigungslogik blockieren Einstiege.")
    limits.extend(["Kein unabhängiger Out-of-Sample-Test und kein Profitabilitätsnachweis; historische Risikomerkmale wurden nicht nachträglich erfunden.",
                   "DEX-Profile sind ein selektiver Kandidatenfeed, keine vollständige Historie aller gestarteten Coins inklusive verschwundener Pools.",
                   "Zeitauflösung und historische Liquidität sind auf die gespeicherten Snapshots begrenzt; Gebühren, Latenz, Impact und Ausfallraten sind Szenarioannahmen."])
    (args.out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    (args.out / "notes.md").write_text(notes(result))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Chronological replay; source DB is opened read-only")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="New result directory; existing paths are not overwritten")
    parser.add_argument("--scenario", choices=("baseline", "stress", "both"), default="both")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--allow-demo", action="store_true")
    args = parser.parse_args()
    try:
        result = run(args)
    except (ValueError, OSError, sqlite3.Error) as error:
        # Do not expose invalid configuration values that may contain endpoints.
        print(f"Backtest failed: {type(error).__name__}")
        return 2
    print(json.dumps({"output": str(args.out), "input_source": result["input"]["source"],
                      "observations": result["data_quality"]["observations"],
                      "scenarios": {name: data["metrics"] for name, data in result["scenarios"].items()},
                      "limitations": result["limitations"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
