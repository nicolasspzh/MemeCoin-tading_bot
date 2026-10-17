"""Summarise a supply sampler log: new and prefilter-eligible coins per DEX Screener list."""
import json, sys
from collections import Counter, defaultdict
rows = [json.loads(l) for l in open(sys.argv[1])]
t0 = min(r["t"] for r in rows if "new" in r)
backlog = {r["new"] for r in rows if "new" in r and r["t"] == t0}
first = {r["new"]: r["feed"] for r in rows if "new" in r and r["new"] not in backlog}
end = max(r["t"] for r in rows)
hours = (end - t0) / 3600
elig, elig_young, dex = defaultdict(set), defaultdict(set), Counter()
for r in rows:
    if "screen" in r and r["screen"] in first and not r["reasons"]:
        feed = first[r["screen"]]
        elig[feed].add(r["screen"])
        if r["pair_age"] is not None and r["pair_age"] <= 86400:
            elig_young[feed].add(r["screen"])
        dex[r["dex"]] += 1
new = Counter(first.values())
print(f"hours {hours:.2f}  backlog excluded {len(backlog)}")
for feed in sorted(new, key=lambda f: -new[f]):
    print(f"{feed:36s} new {new[feed]:4d} ({new[feed]/hours:5.1f}/h)  eligible {len(elig[feed]):3d} ({len(elig[feed])/hours:4.1f}/h)  eligible&pool<=24h {len(elig_young[feed]):3d} ({len(elig_young[feed])/hours:4.1f}/h)")
tot = set().union(*elig.values()) if elig else set(); young = set().union(*elig_young.values()) if elig_young else set()
print(f"TOTAL eligible {len(tot)} ({len(tot)/hours:.1f}/h), pool<=24h {len(young)} ({len(young)/hours:.1f}/h)")
print("eligible screens by dex", dict(dex))
print("errors", Counter(("feed_error" in r and r["feed_error"]) or ("screen_error" in r and "screen") for r in rows if "feed_error" in r or "screen_error" in r))
