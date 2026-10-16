"""Stage C: rebuild R2 window observations with R3 holder assessments from stored evidence."""
import json, pickle, sqlite3, sys
from pathlib import Path
from collections import Counter
from datetime import datetime
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from collectors.holders import PUMP_FEE_CONFIG, assess_bundle, pool_state
from collectors.http import DataUnavailable
from data.models import Snapshot
from backtesting.replay import Observation

db_path, out = sys.argv[1], sys.argv[2]
fee = json.load(open(ROOT / "tests/fixtures/pumpswap_fee_config_20260908.json"))["account"]
plan = json.load(open(ROOT / "uebergabe/2026-10-12/R2-Referenz/protocol.json"))["plan"]
start, end = datetime.fromisoformat(plan["test_start_utc"]), datetime.fromisoformat(plan["test_end_exclusive_utc"])
c = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
cache, stats, records = {}, Counter(), []
for sid, payload in c.execute("SELECT id,payload FROM snapshots ORDER BY id"):
    s = Snapshot.model_validate_json(payload)
    if not (start <= s.received_at < end) or Observation(sid, s).available_at >= end:
        continue
    h = s.mint_risk.holder_risk if s.mint_risk else None
    if h is not None and h.evidence_sha256:
        if h.evidence_sha256 not in cache:
            e = json.loads(c.execute("SELECT payload FROM risk_evidence WHERE sha256=?", (h.evidence_sha256,)).fetchone()[0])
            accounts = dict(e["accounts"])
            try:
                expected = pool_state(accounts[e["pair"]], e["pair"])
                if expected and expected["program"].startswith("pAMM"):
                    accounts[PUMP_FEE_CONFIG] = fee
                keys = list(accounts)
                new, _ = assess_bundle(e["token"], e["pair"], keys, {"context": {"slot": e["slot"]}, "value": [accounts[k] for k in keys]},
                                       expected, e["sampled_addresses"], e["rpc_host"])
                new.evidence_payload = None
                cache[h.evidence_sha256] = new
                stats["rebuilt_ok"] += 1
            except (DataUnavailable, KeyError, ValueError) as exc:
                cache[h.evidence_sha256] = exc.__class__.__name__ + ":" + str(exc)[:60]
                stats["rebuilt_error"] += 1
        new = cache[h.evidence_sha256]
        if isinstance(new, str):
            stats["row_error:" + new] += 1
            s.mint_risk.holder_risk = None
            s.mint_risk.data_errors = [*s.mint_risk.data_errors, "R3 rebuild failed"]
        else:
            s.mint_risk.holder_risk = new.model_copy(update={"checked_at": h.checked_at, "evidence_sha256": None})
            stats["row_rebuilt"] += 1
    elif h is not None:
        h.evidence_payload = None
        stats["row_holder_without_evidence:" + h.status] += 1
    records.append(Observation(sid, s))
pickle.dump(records, open(out, "wb"))
print("rows:", len(records)); print(dict(stats.most_common(12)))
