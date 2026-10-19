"""Read-only stage D probe report: admission supply, provider load and technical entry checks.

The probe has no test character. Entry-check counts show whether checks work,
not whether the strategy earns money; no prices or outcomes are evaluated.
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

from backtesting.evaluation import EXCLUDED_SETTINGS
from backtesting.replay import Observation
from config.settings import Settings
from data.models import Snapshot
from operations.campaign import read_json
from trading.risk import risk_reasons


def iso(timestamp):
    return datetime.fromtimestamp(timestamp, UTC).isoformat() if timestamp is not None else None


def hour(timestamp):
    """UTC clock hour; supply may depend on the time of day."""
    return datetime.fromtimestamp(timestamp, UTC).strftime("%H")


def by_hour(timestamps):
    return dict(sorted(Counter(hour(t) for t in timestamps).items()))


def pool_kind(dex_id, labels):
    return f"{dex_id}{'/' + ','.join(labels) if labels else ''}"


def probe_report(directory, now=None):
    manifest = read_json(directory / "manifest.json")["manifest"]
    state = read_json(directory / "state.json", {})
    settings = Settings.model_validate({k: v for k, v in manifest["settings"].items() if k not in EXCLUDED_SETTINGS})
    start = datetime.fromisoformat(manifest["created_at"]).timestamp()
    end = min((now or datetime.now(UTC)).timestamp(), datetime.fromisoformat(manifest["until"]).timestamp())
    if state.get("stopped_at") and state.get("status") not in ("starting", "running", "restarting"):
        # A probe stopped early observed only until its stop, not until the planned end.
        end = min(end, datetime.fromisoformat(state["stopped_at"]).timestamp())
    hours = max(end - start, 1) / 3600
    result = {"profile": manifest.get("profile", "r2"), "created_at": manifest["created_at"], "until": manifest["until"],
              "hours_observed": round(hours, 2), "admission_prefilter": settings.admission_prefilter,
              "slots": settings.max_watch_tokens, "admission_interval_seconds": settings.observation_admission_seconds,
              "state": {k: state.get(k) for k in ("status", "stopped_at", "completed_cycles", "worker_launches", "rpc_requests",
                                                   "rpc_successes", "data_degraded", "backup_error_type")}}
    path = directory / "observations.sqlite3"
    if not path.exists():
        result["database"] = None
        return result
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10) as db:
        db.execute("BEGIN")
        discovered = Counter(dict(db.execute("SELECT source,count(*) FROM tokens WHERE discovered_at>=? GROUP BY source", (start,))))
        result["discovered"] = {"total": sum(discovered.values()), "per_hour": round(sum(discovered.values()) / hours, 1),
                                "by_source": dict(discovered), "by_utc_hour": by_hour(
                                    row[0] for row in db.execute("SELECT discovered_at FROM tokens WHERE discovered_at>=?", (start,)))}
        reasons, eligible_kinds, screened, eligible_tokens, total, eligible = Counter(), Counter(), set(), {}, 0, 0
        for token, ok, at, payload in db.execute("SELECT token,eligible,screened_at,payload FROM admission_screens ORDER BY id"):
            value = json.loads(payload)
            total += 1
            screened.add(token)
            if ok:
                eligible += 1
                eligible_tokens.setdefault(token, at)
                eligible_kinds[pool_kind(value.get("dex_id"), value.get("labels"))] += 1
            reasons.update(value.get("reasons") or [])
        result["screens"] = {"total": total, "eligible": eligible, "tokens_screened": len(screened),
                             "tokens_eligible": len(eligible_tokens),
                             "eligible_tokens_per_hour": round(len(eligible_tokens) / hours, 1),
                             "eligible_tokens_by_utc_hour": by_hour(eligible_tokens.values()),
                             "rejection_reasons": dict(reasons.most_common()), "eligible_pool_kinds": dict(eligible_kinds)}
        admitted = [row[0] for row in db.execute("SELECT admitted_at FROM observation_tracks ORDER BY admitted_at")]
        gaps = [b - a for a, b in zip(admitted, admitted[1:])]
        result["admissions"] = {"total": len(admitted), "first": iso(admitted[0]) if admitted else None,
                                "last": iso(admitted[-1]) if admitted else None,
                                "gap_seconds_median": round(median(gaps)) if gaps else None,
                                "gap_seconds_max": round(max(gaps)) if gaps else None,
                                "gaps": len(gaps), "gaps_over_900_seconds": sum(g > 900 for g in gaps),
                                "by_utc_hour": by_hour(admitted)}
        result["rpc_request_budget"] = dict(db.execute("SELECT utc_day,requests FROM rpc_request_budget"))
        result["rpc_requests_per_hour"] = round((state.get("rpc_requests") or 0) / hours)
        result["health"] = {f"{s}:{k}": n for s, k, n in db.execute(
            "SELECT source,kind,count(*) FROM collector_health WHERE kind!='cycle' GROUP BY 1,2 ORDER BY 3 DESC")}
        result["orders"] = db.execute("SELECT count(*) FROM paper_orders").fetchone()[0]
        result["fills"] = db.execute("SELECT count(*) FROM fills").fetchone()[0]
        rows, priced, holder, errors, passed, passed_tokens, blockers = 0, 0, Counter(), 0, 0, set(), Counter()
        for sid, payload in db.execute("SELECT id,payload FROM snapshots"):
            snapshot = Snapshot.model_validate_json(payload)
            rows += 1
            priced += snapshot.price_usd is not None
            risk = snapshot.mint_risk
            holder[risk.holder_risk.status if risk and risk.holder_risk else "none"] += 1
            errors += bool(risk and risk.data_errors)
            found = risk_reasons(snapshot, Observation(sid, snapshot).available_at, settings)
            blockers.update(set(found))
            if not found:
                passed += 1
                passed_tokens.add(snapshot.token)
        result["observations"] = {"total": rows, "priced": priced, "holder_status": dict(holder),
                                  "with_data_errors": errors, "entry_check_pass_rows": passed,
                                  "entry_check_pass_tokens": len(passed_tokens),
                                  "top_blockers": dict(blockers.most_common(12))}
    return result


def german(result):
    lines = [f"PROBELAUF STUFE D ({result['profile']})",
             f"Beobachtet: {result['hours_observed']} Stunden; Vorfilter: {'an' if result['admission_prefilter'] else 'AUS'}",
             f"Status: {result['state'].get('status')}; Runden: {result['state'].get('completed_cycles')}"]
    if "screens" not in result:
        return "\n".join(lines + ["Datenbank: noch nicht vorhanden."]) + "\n"
    s, a, o = result["screens"], result["admissions"], result["observations"]
    lines += [f"Entdeckte Coins: {result['discovered']['total']} ({result['discovered']['per_hour']} pro Stunde)",
              f"Vorfilter: {s['tokens_screened']} Coins geprüft, {s['tokens_eligible']} geeignet "
              f"({s['eligible_tokens_per_hour']} pro Stunde)",
              f"Aufnahmen: {a['total']}; Abstand Median {a['gap_seconds_median']} s, längster {a['gap_seconds_max']} s, "
              f"über 900 s: {a['gaps_over_900_seconds']} von {a['gaps']}",
              f"RPC-Anfragen pro Stunde: {result['rpc_requests_per_hour']}",
              f"Beobachtungen: {o['total']}; bestehen alle Einstiegsprüfungen: {o['entry_check_pass_rows']} "
              f"Zeilen von {o['entry_check_pass_tokens']} Coins",
              f"Orders/Ausführungen: {result['orders']}/{result['fills']} (müssen 0 sein)",
              "Bitte die ganze Ausgabe inklusive JSON zurückschicken."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args(argv)
    directory = args.directory.resolve()
    if not (directory / "manifest.json").is_file():
        print("Keine initialisierte Sammlung an diesem Pfad. Verzeichnis prüfen.", file=sys.stderr)
        return 2
    try:
        result = probe_report(directory)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        print(f"Bericht konnte nicht erstellt werden ({type(error).__name__}).", file=sys.stderr)
        return 2
    print(german(result) + "\n" + json.dumps(result, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
