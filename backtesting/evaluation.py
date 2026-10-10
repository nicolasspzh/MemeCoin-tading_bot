"""Read-only diagnostics and predeclared prospective holdout evaluation.

Known development observations never become an unseen test just by splitting
their rows. A plan locks a future window, code, parameters, seeds and quality
rules. No parameter search or automatic trading approval is performed here.
"""
import argparse
import hashlib
import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

from backtesting.__main__ import freeze_input, write_csv
from backtesting.replay import Observation, Replay, quality_profile, read_observations
from config.settings import Settings, load_settings
from trading.execution import Execution
from trading.risk import risk_reasons

SEEDS = (7, 17, 29)
POLICY = {"minimum_days": 3, "minimum_active_5min_fraction": 0.8,
          "minimum_priced_fraction": 0.95, "minimum_modern_risk_fraction": 0.95,
          "maximum_long_gap_fraction": 0.1, "minimum_pairs_with_followups": 30,
          "minimum_closed_trades": 100, "minimum_closed_trade_tokens": 20}
EXCLUDED_SETTINGS = {"solana_rpc_url", "solana_rpc_fallback_urls", "dex_base_url", "db_path"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def code_digest():
    root = Path(__file__).resolve().parents[1]
    files = [root / name for name in ("main.py", "requirements.txt", "pyproject.toml")]
    for folder in ("backtesting", "trading", "collectors", "config", "data"):
        files.extend((root / folder).glob("*.py"))
    return digest({str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)})


def utc(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("A timestamp with UTC offset is required")
    return result.astimezone(UTC)


def merge_inputs(paths, *, allow_demo=False):
    merged, origins, provenance, sources = {}, defaultdict(list), [], set()
    for path in paths:
        records, info = read_observations(Path(path), allow_demo=allow_demo)
        provenance.append(info)
        sources.add(info["source"])
        if len(sources) > 1:
            raise ValueError("Demo and market sources cannot be mixed")
        for row in records:
            s = row.snapshot
            key = (s.received_at, s.token, s.pair)
            value = s.model_dump(mode="json")
            if key in merged and merged[key].model_dump(mode="json") != value:
                raise ValueError("Conflicting observations at the same token/pool/time")
            merged[key] = s
            origins[key].append({"source_path": info["path"], "source_row_id": row.id})
    if len(sources) != 1:
        raise ValueError("Demo and market sources cannot be mixed")
    records, mapping = [], []
    for sid, key in enumerate(sorted(merged), 1):
        records.append(Observation(sid, merged[key]))
        mapping.append({"id": sid, "origins": origins[key]})
    return records, {"source": sources.pop(), "inputs": provenance,
                     "duplicates_removed": sum(p["rows"] for p in provenance) - len(records),
                     "rows": len(records), "row_mapping": mapping}


def data_quality(records, settings, *, start=None, end=None, policy=None):
    policy = policy or POLICY
    if not records:
        return {"observations": 0, "blockers": ["no_observations"], "readiness": False}
    profile = quality_profile(records)
    start = start or min(r.snapshot.received_at for r in records)
    end = end or max(r.available_at for r in records) + timedelta(microseconds=1)
    priced, modern, complete, proof, entry_pass = 0, 0, 0, 0, 0
    bucket_days, days, per_pair, rejection = defaultdict(set), Counter(), defaultdict(list), Counter()
    active = set()
    for row in records:
        s, risk = row.snapshot, row.snapshot.mint_risk
        day = s.received_at.astimezone(UTC).date().isoformat()
        days[day] += 1
        blockers = risk_reasons(s, row.available_at, settings)
        rejection.update(blockers)
        entry_pass += not blockers
        if s.price_usd is not None:
            priced += 1
            bucket = int(s.received_at.timestamp() // 300)
            active.add(bucket)
            bucket_days[day].add(bucket)
            per_pair[(s.token, s.pair)].append(s.received_at)
            modern += bool(risk and risk.risk_version == 3)
        holder = risk.holder_risk if risk else None
        if holder and holder.status == "complete":
            complete += 1
            proof += bool(holder.evidence_sha256 and holder.evidence_payload is not None)
    gaps = [(b-a).total_seconds() for times in per_pair.values()
            for a, b in zip(sorted(times), sorted(times)[1:])]
    expected_buckets = max(1, math.ceil(end.timestamp() / 300) - int(start.timestamp() // 300))
    fraction = len(active) / expected_buckets
    followups = sum(len(times) >= 2 for times in per_pair.values())
    long_gap_fraction = sum(g > settings.max_quote_age_seconds for g in gaps) / len(gaps) if gaps else None
    priced_fraction = priced / len(records)
    modern_fraction = modern / priced if priced else 0
    blockers = []
    if len(bucket_days) < policy["minimum_days"]: blockers.append("too_few_observed_days")
    if fraction < policy["minimum_active_5min_fraction"]: blockers.append("sparse_time_coverage")
    if priced_fraction < policy["minimum_priced_fraction"]: blockers.append("missing_prices")
    if modern_fraction < policy["minimum_modern_risk_fraction"]: blockers.append("legacy_or_missing_risk_data")
    if complete != proof: blockers.append("incomplete_account_proof_coverage")
    if followups < policy["minimum_pairs_with_followups"]: blockers.append("too_few_observed_price_paths")
    if long_gap_fraction is None or long_gap_fraction > policy["maximum_long_gap_fraction"]:
        blockers.append("missing_or_sparse_same_pool_followups")
    return {**profile, "grain": "token/pool/received_at", "source_days_utc": dict(sorted(days.items())),
            "active_5min_buckets_by_day": {k: len(v) for k, v in sorted(bucket_days.items())},
            "window_start_utc": start.isoformat(), "window_end_exclusive_utc": end.isoformat(),
            "active_5min_buckets": len(active), "expected_5min_buckets": expected_buckets,
            "active_5min_fraction": fraction, "priced_rows": priced, "priced_fraction": priced_fraction,
            "modern_risk_rows_with_price": modern, "modern_risk_fraction": modern_fraction,
            "complete_holder_assessments": complete, "assessments_with_account_proof": proof,
            "priced_pairs_with_followups": followups, "long_same_pool_gap_fraction": long_gap_fraction,
            "entry_risk_pass_rows": entry_pass, "risk_rejection_counts": dict(rejection),
            "blockers": blockers, "readiness": not blockers}


def scenario_definitions(settings):
    baseline = Execution.from_settings(settings)
    stress = baseline.model_copy(update={"latency_seconds": max(5, baseline.latency_seconds * 5),
        "priority_fee_usd": max(D(".02"), baseline.priority_fee_usd * 4),
        "failure_probability": max(.1, baseline.failure_probability),
        "max_adverse_move_bps": min(D(500), baseline.max_adverse_move_bps)})
    costly = settings.model_copy(update={"slippage_bps": min(D(9999), max(D(300), settings.slippage_bps * 3)),
                                        "fixed_fee_usd": settings.fixed_fee_usd * 2})
    return {name: {"settings": s.model_dump(mode="json", exclude=EXCLUDED_SETTINGS),
                   "execution": e.model_dump(mode="json")}
            for name, s, e in (("baseline", settings, baseline), ("stress", costly, stress))}


def write_json(path, value):
    with Path(path).open("x") as output:
        output.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def run_scenarios(records, definitions, out, seeds=SEEDS):
    results = {}
    if not records:
        return results
    for name, definition in definitions.items():
        results[name] = []
        for seed in seeds:
            settings = Settings.model_validate(definition["settings"])
            execution = Execution.model_validate({**definition["execution"], "seed": seed})
            replay = Replay(settings, execution)
            metrics = replay.run(records)
            closed = [f for f in replay.fills if f["side"] == "SELL"]
            metrics["distinct_closed_trade_tokens"] = len({f["token"] for f in closed})
            metrics["excess_marked_equity_vs_cash_usd"] = str(D(metrics["total_equity_mark_usd"]) - 50)
            destination = out / name / f"seed-{seed}"
            destination.mkdir(parents=True)
            write_json(destination / "decisions.json", replay.decisions)
            for filename, rows in (("orders", replay.orders), ("fills", replay.fills), ("equity", replay.curve)):
                fields = list(dict.fromkeys(k for row in rows for k in row)) or ["no_records"]
                write_csv(destination / f"{filename}.csv", rows, fields)
            results[name].append({"seed": seed, "metrics": metrics})
    return results


def readiness(quality, results, source, prospective, policy=None):
    policy = policy or POLICY
    blockers = list(quality["blockers"])
    if source != "dexscreener": blockers.append("synthetic_data")
    if not prospective: blockers.append("previously_available_development_data")
    runs = [run["metrics"] for group in results.values() for run in group]
    if not runs or any(m["completed_trades"] < policy["minimum_closed_trades"] for m in runs):
        blockers.append("too_few_closed_trades")
    if not runs or any(m["distinct_closed_trade_tokens"] < policy["minimum_closed_trade_tokens"] for m in runs):
        blockers.append("too_few_distinct_traded_tokens")
    if any(m["open_positions"] for m in runs): blockers.append("unresolved_open_positions")
    if any(m["order_status_counts"].get("unfilled_end_of_data", 0) for m in runs):
        blockers.append("unresolved_orders_at_boundary")
    return {"status": "SYNTHETIC_ONLY" if source == "demo" else "INSUFFICIENT_EVIDENCE" if blockers else "REVIEWABLE_HOLDOUT",
            "blockers": blockers, "eligible_for_review": not blockers,
            "positive_net_realized_pnl_in_every_scenario": all(D(m["net_realized_pnl_usd"]) > 0 for m in runs) if runs else None,
            "live_trading_approved": False}


def write_notes(out, result):
    lines = ["# Phase 6 – technischer Auswertungslauf", "", f"Status: **{result['assessment']['status']}**", "",
             f"Beobachtungen: {result['data_quality']['observations']}. Unabhängiger zukünftiger Zeitraum: {result['prospective']}.",
             "", "| Szenario | Seed | Geschlossene Trades | Netto realisiert (USD) | Offene Positionen |",
             "| --- | ---: | ---: | ---: | ---: |"]
    for scenario, runs in result["scenarios"].items():
        for run in runs:
            m = run["metrics"]
            lines.append(f"| {scenario} | {run['seed']} | {m['completed_trades']} | {D(m['net_realized_pnl_usd']):.4f} | {len(m['open_positions'])} |")
    lines += ["", "Hindernisse:", "", *[f"- {b}" for b in result["assessment"]["blockers"]], "",
              "Die Seeds sind Kostensensitivitäten derselben Marktdaten, keine unabhängigen Stichproben. Kein bester Seed wird ausgewählt.",
              "Unterschiedliche Tokens können stark korreliert sein; ihre Anzahl ist keine Zahl unabhängiger Versuche.",
              "Zeitlücken und verschwundene Pools werden nicht aufgefüllt. Keine Parameteroptimierung, kein Lesen späterer Outcome-Labels.",
              "Null Trades bedeuten kein Profitabilitätsurteil. Die Schwellen sind vorläufige Forschungsanforderungen, keine statistische Poweranalyse.",
              "Ein zukünftiges Zeitfenster und lokale Hashes beweisen nicht, dass niemand die Daten anderweitig betrachtet hat.",
              "Der Cash-Vergleich bleibt ohne Orders bei 50 USD. Offene Positionen bleiben offen; Mark-to-market-Werte sind keine ausführbaren Erlöse.",
              "Kosten/Impact/Ausfälle sind Modellannahmen; dieser Lauf erteilt keine Live-Handelsfreigabe."]
    (out / "notes.md").write_text("\n".join(lines) + "\n")


def diagnostic(paths, out, settings, *, allow_demo=False):
    records, provenance = merge_inputs(paths, allow_demo=allow_demo)
    out.mkdir(parents=True, exist_ok=False)
    freeze_input(out / "input.sqlite3", records, provenance["source"])
    _, frozen = read_observations(out / "input.sqlite3", allow_demo=allow_demo)
    definitions = scenario_definitions(settings)
    quality = data_quality(records, settings)
    results = run_scenarios(records, definitions, out)
    result = {"version": 1, "generated_at_utc": datetime.now(UTC).isoformat(), "kind": "DEVELOPMENT_DIAGNOSTIC",
              "prospective": False, "inputs": provenance, "frozen_snapshots_sha256": frozen["snapshots_sha256"],
              "code_sha256": code_digest(), "data_quality": quality, "scenario_definitions": definitions,
              "seeds": list(SEEDS), "quality_policy": POLICY, "scenarios": results,
              "cash_benchmark_usd": "50", "assessment": readiness(quality, results, provenance["source"], False)}
    write_json(out / "result.json", result)
    write_notes(out, result)
    return result


def prepare(paths, out, settings, *, start=None, days=7, now=None):
    now = now or datetime.now(UTC)
    if not settings.require_verified_holder_risk:
        raise ValueError("Prospective validation requires verified holder risk")
    if days < 3:
        raise ValueError("Holdout requires at least three calendar days")
    records, provenance = merge_inputs(paths)
    last = max(r.available_at for r in records)
    if last > now:
        raise ValueError("Development input contains future observations")
    boundary = max(now, last) + timedelta(hours=1)
    start = utc(start) if start else datetime.combine(boundary.date() + timedelta(days=1), datetime.min.time(), UTC)
    if start < boundary:
        raise ValueError("Holdout must begin in the future after a one-hour embargo")
    out.mkdir(parents=True, exist_ok=False)
    freeze_input(out / "development.sqlite3", records, provenance["source"])
    _, frozen = read_observations(out / "development.sqlite3")
    plan = {"version": 1, "created_at_utc": now.isoformat(), "development_end_utc": last.isoformat(),
            "test_start_utc": start.isoformat(), "test_end_exclusive_utc": (start + timedelta(days=days)).isoformat(),
            "embargo_seconds": 3600, "development_snapshots_sha256": frozen["snapshots_sha256"],
            "development_sources": provenance, "code_sha256": code_digest(),
            "scenario_definitions": scenario_definitions(settings), "seeds": list(SEEDS), "quality_policy": POLICY,
            "rules": ["No tuning on holdout", "Fresh USD 50 per scenario", "No carried positions or signals across boundary",
                      "Do not evaluate performance before window end", "Restart with a new future plan after strategy/code changes"]}
    envelope = {"plan": plan, "sha256": digest(plan)}
    write_json(out / "protocol.json", envelope)
    return envelope


def load_protocol(path):
    envelope = json.loads(path.read_text())
    plan = envelope["plan"]
    if digest(plan) != envelope["sha256"]:
        raise ValueError("Protocol fingerprint mismatch")
    if plan["version"] != 1 or plan["code_sha256"] != code_digest():
        raise ValueError("Code changed since protocol preparation; a new future plan is required")
    _, development = read_observations(path.parent / "development.sqlite3")
    if development["snapshots_sha256"] != plan["development_snapshots_sha256"]:
        raise ValueError("Frozen development evidence changed")
    if (utc(plan["test_start_utc"]) < max(utc(plan["created_at_utc"]), utc(plan["development_end_utc"])) + timedelta(seconds=plan["embargo_seconds"])
            or utc(plan["test_end_exclusive_utc"]) <= utc(plan["test_start_utc"])):
        raise ValueError("Invalid holdout time boundaries")
    return envelope


def evaluate(protocol_path, paths, out, *, now=None):
    envelope = load_protocol(protocol_path)
    plan, now = envelope["plan"], now or datetime.now(UTC)
    start, end = utc(plan["test_start_utc"]), utc(plan["test_end_exclusive_utc"])
    if now < end:
        # Do not even open the prospective input before the scheduled window ends.
        out.mkdir(parents=True, exist_ok=False)
        result = {"status": "WAITING_FOR_WINDOW_END", "test_start_utc": start.isoformat(),
                  "test_end_exclusive_utc": end.isoformat(), "protocol_sha256": envelope["sha256"],
                  "performance_evaluated": False}
        write_json(out / "result.json", result)
        return result
    records, provenance = merge_inputs(paths)
    chosen, excluded = [], Counter()
    for row in records:
        if row.snapshot.received_at < start: excluded["before_window"] += 1
        elif row.snapshot.received_at >= end: excluded["after_window"] += 1
        elif row.available_at >= end: excluded["risk_arrived_after_window"] += 1
        else: chosen.append(row)
    # No earlier prices, positions, outcome tables or risk facts cross the boundary.
    settings = Settings.model_validate(plan["scenario_definitions"]["baseline"]["settings"])
    out.mkdir(parents=True, exist_ok=False)
    freeze_input(out / "input.sqlite3", chosen, provenance["source"])
    quality = data_quality(chosen, settings, start=start, end=end, policy=plan["quality_policy"])
    results = run_scenarios(chosen, plan["scenario_definitions"], out, plan["seeds"])
    result = {"version": 1, "generated_at_utc": now.isoformat(), "kind": "PROSPECTIVE_WINDOW_EVALUATION",
              "prospective": True, "protocol_sha256": envelope["sha256"], "code_sha256": plan["code_sha256"],
              "inputs": provenance, "excluded_rows": dict(excluded), "data_quality": quality,
              "scenario_definitions": plan["scenario_definitions"], "seeds": plan["seeds"],
              "quality_policy": plan["quality_policy"], "scenarios": results, "cash_benchmark_usd": "50",
              "assessment": readiness(quality, results, provenance["source"], True, plan["quality_policy"])}
    if chosen:
        _, frozen = read_observations(out / "input.sqlite3")
        result["frozen_snapshots_sha256"] = frozen["snapshots_sha256"]
    write_json(out / "result.json", result)
    write_notes(out, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("diagnose", "prepare", "evaluate"):
        command = commands.add_parser(name)
        command.add_argument("--db", type=Path, action="append", required=True)
        command.add_argument("--out", type=Path, required=True)
        if name == "diagnose": command.add_argument("--allow-demo", action="store_true")
        if name == "prepare":
            command.add_argument("--test-start")
            command.add_argument("--days", type=int, default=7)
        if name == "evaluate": command.add_argument("--protocol", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result = prepare(args.db, args.out, load_settings(), start=args.test_start, days=args.days)
            print(json.dumps({"status": "PROTOCOL_PREPARED", "output": str(args.out),
                              "test_start_utc": result["plan"]["test_start_utc"],
                              "test_end_exclusive_utc": result["plan"]["test_end_exclusive_utc"]}))
            return 0
        result = (diagnostic(args.db, args.out, load_settings(), allow_demo=args.allow_demo)
                  if args.command == "diagnose" else evaluate(args.protocol, args.db, args.out))
        status = result.get("status") or result["assessment"]["status"]
        print(json.dumps({"status": status, "output": str(args.out),
                          "observations": result.get("data_quality", {}).get("observations"),
                          "blockers": result.get("assessment", {}).get("blockers", [])}))
        return 0 if status == "REVIEWABLE_HOLDOUT" else 2
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as error:
        print(f"Evaluation failed: {type(error).__name__}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
