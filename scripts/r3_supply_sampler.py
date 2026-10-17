"""Cloud supply sampler: which DEX Screener lists yield prefilter-eligible coins (no RPC, no trading)."""
import asyncio, json, sys, time
from datetime import datetime, UTC
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
import aiohttp
from collectors.dexscreener import DexScreener
from collectors.http import JsonClient, DataUnavailable
from collectors.schedule import admission_reasons
from config.settings import Settings, ADDRESS

FEEDS = ["token-profiles/latest/v1", "token-boosts/latest/v1", "community-takeovers/latest/v1",
         "ads/latest/v1", "token-profiles/recent-updates/v1", "token-boosts/top/v1"]
out, hours = sys.argv[1], float(sys.argv[2])
settings = Settings()

async def main():
    first, sources, screened, log = {}, {}, {}, open(out, "a")
    end = time.time() + hours * 3600
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20), trust_env=True) as session:
        http = JsonClient(session); dex = DexScreener(http, "https://api.dexscreener.com")
        while time.time() < end:
            start = time.time()
            for feed in FEEDS:
                try:
                    rows = await http.request("GET", "https://api.dexscreener.com/" + feed)
                except DataUnavailable as e:
                    log.write(json.dumps({"t": start, "feed_error": feed, "e": str(e)[:80]}) + "\n"); continue
                for r in rows if isinstance(rows, list) else []:
                    tok = r.get("tokenAddress") if isinstance(r, dict) else None
                    if r.get("chainId") == "solana" and tok and ADDRESS.fullmatch(tok):
                        if tok not in first:
                            first[tok] = start
                            log.write(json.dumps({"t": start, "new": tok, "feed": feed}) + "\n")
                        sources.setdefault(tok, set()).add(feed)
            now = time.time()
            due = [t for t, f in first.items() if now - f <= 3960 and now - screened.get(t, 0) >= 300]
            for i in range(0, len(due), 30):
                batch = due[i:i + 30]
                try:
                    quotes = await dex.snapshots(batch, {})
                except DataUnavailable as e:
                    log.write(json.dumps({"t": now, "screen_error": str(e)[:80]}) + "\n"); continue
                for t in batch:
                    s = quotes.get(t); screened[t] = now
                    age = (datetime.now(UTC) - s.pair_created_at).total_seconds() if s and s.pair_created_at else None
                    log.write(json.dumps({"t": now, "screen": t, "reasons": admission_reasons(s, settings),
                                          "pair_age": age, "dex": (s.raw.get("dexId") if s else None)}) + "\n")
            log.flush()
            await asyncio.sleep(max(0, 60 - (time.time() - start)))
asyncio.run(main())
