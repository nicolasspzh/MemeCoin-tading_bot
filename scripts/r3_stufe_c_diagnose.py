"""Stage C: entry-check counts and replay of the 6 scenarios on rebuilt R2 rows (development only)."""
import json, pickle, resource, sys, time
from collections import Counter, defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config.settings import Settings
from backtesting.evaluation import scenario_definitions, run_scenarios
from trading.risk import risk_reasons

records = pickle.load(open(sys.argv[1], "rb"))
out = Path(sys.argv[2])
plan = json.load(open(ROOT / "uebergabe/2026-10-12/R2-Referenz/protocol.json"))["plan"]
r3_changes = {"paper_max_adverse_move_bps": "300"}
settings = Settings.model_validate({**plan["scenario_definitions"]["baseline"]["settings"], **r3_changes})
defs = scenario_definitions(settings)

def pool_kind(s):
    raw = s.raw or {}
    labels = raw.get("labels") or []
    return f"{raw.get('dexId')}{'/'+','.join(labels) if labels else ''}"

rows_pass, coins_pass, reasons, by_kind, single = 0, set(), Counter(), defaultdict(Counter), Counter()
coins_by_kind, pass_by_kind, status = defaultdict(set), Counter(), Counter()
for r in records:
    s = r.snapshot
    k = pool_kind(s)
    coins_by_kind[k].add(s.token)
    h = s.mint_risk.holder_risk if s.mint_risk else None
    status[(k, h.status if h else None)] += 1
    rs = risk_reasons(s, r.available_at, settings)
    reasons.update(set(rs))
    by_kind[k].update(set(rs))
    if not rs:
        rows_pass += 1; coins_pass.add(s.token); pass_by_kind[k] += 1
    elif len(rs) == 1:
        single[rs[0]] += 1
summary = {"rows": len(records), "coins": len({r.snapshot.token for r in records}),
           "entry_pass_rows": rows_pass, "entry_pass_coins": len(coins_pass),
           "reason_rows": dict(reasons.most_common()), "single_blocker_rows": dict(single.most_common()),
           "pool_kinds": {k: {"coins": len(v), "pass_rows": pass_by_kind[k],
                              "top_reasons": dict(by_kind[k].most_common(8))} for k, v in coins_by_kind.items()},
           "holder_status": {f"{k}|{st}": n for (k, st), n in status.most_common()}}
print(json.dumps({k: summary[k] for k in ("rows", "coins", "entry_pass_rows", "entry_pass_coins")}), flush=True)
out.mkdir(parents=True, exist_ok=False)
(out / "entry_checks.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
t = time.time()
results = run_scenarios(records, defs, out / "replay")
slim = {name: [{"seed": run["seed"], **{key: run["metrics"][key] for key in (
    "orders", "order_status_counts", "successful_fills", "completed_trades", "distinct_closed_trade_tokens",
    "net_realized_pnl_usd", "total_equity_mark_usd", "open_positions", "status", "decision_counts")}}
    for run in runs] for name, runs in results.items()}
(out / "replay_summary.json").write_text(json.dumps(slim, indent=1))
(out / "settings.json").write_text(json.dumps(defs, indent=1))
print(json.dumps(slim, indent=1)[:6000])
print("seconds", round(time.time() - t), "maxrss_gb", resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6)
