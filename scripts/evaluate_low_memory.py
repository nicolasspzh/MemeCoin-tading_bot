"""Run backtesting.evaluation.evaluate step by step with the same frozen functions.

Identical calls, arguments and order as evaluate(); the only difference is that the
in-memory observations are released before the frozen input copy is read back for
its fingerprint, and result.json is written before that read. The frozen core code
is not changed. Used for R3 after evaluate() ran out of memory (15 GB) at that step.
"""
import gc
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtesting.evaluation import (data_quality, freeze_input, load_protocol, merge_inputs,  # noqa: E402
                                    read_observations, readiness, run_scenarios, utc, write_json, write_notes)
from config.settings import Settings  # noqa: E402

protocol_path, db, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
envelope = load_protocol(protocol_path)
plan, now = envelope["plan"], datetime.now(UTC)
start, end = utc(plan["test_start_utc"]), utc(plan["test_end_exclusive_utc"])
if now < end:
    raise SystemExit("Window has not ended; use backtesting.evaluation evaluate")
records, provenance = merge_inputs([db])
chosen, excluded = [], Counter()
for row in records:
    if row.snapshot.received_at < start: excluded["before_window"] += 1
    elif row.snapshot.received_at >= end: excluded["after_window"] += 1
    elif row.available_at >= end: excluded["risk_arrived_after_window"] += 1
    else: chosen.append(row)
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
has_rows = bool(chosen)
(out / "result.partial.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
del records, chosen, results
gc.collect()
if has_rows:
    _, frozen = read_observations(out / "input.sqlite3")
    result["frozen_snapshots_sha256"] = frozen["snapshots_sha256"]
write_json(out / "result.json", result)
write_notes(out, result)
(out / "result.partial.json").unlink()
print(json.dumps({"status": result["assessment"]["status"], "output": str(out),
                  "observations": result["data_quality"].get("observations")}))
