from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from collectors.http import DataUnavailable, JsonClient
from config.settings import ADDRESS
from data.models import Snapshot, utcnow


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result >= 0 else None
    except InvalidOperation:
        return None


def parse_pair(pair: dict, received_at: datetime) -> Snapshot:
    price = number(pair.get("priceUsd"))
    created = number(pair.get("pairCreatedAt"))
    try:
        created_at = datetime.fromtimestamp(float(created / 1000), UTC) if created else None
    except (ValueError, OverflowError, OSError):
        created_at = None
    txns = (pair.get("txns") or {}).get("m5") or {}
    change = (pair.get("priceChange") or {}).get("m5")
    try:
        change = Decimal(str(change)) if change is not None else None
        if change is not None and not change.is_finite():
            change = None
    except InvalidOperation:
        change = None
    return Snapshot(
        token=pair["baseToken"]["address"], pair=pair["pairAddress"],
        symbol=pair["baseToken"].get("symbol") or "?", source="dexscreener",
        received_at=received_at, pair_created_at=created_at,
        price_usd=price if price else None,
        liquidity_usd=number((pair.get("liquidity") or {}).get("usd")),
        market_cap_usd=number(pair.get("marketCap")),
        volume_5m_usd=number((pair.get("volume") or {}).get("m5")),
        buys_5m=number(txns.get("buys")), sells_5m=number(txns.get("sells")),
        change_5m_pct=change, raw=pair)


# Candidate lists (each 60 requests per minute) and the source label stored per token.
FEEDS = {"token-profiles": ("/token-profiles/latest/v1", "dexscreener-profile"),
         "token-boosts": ("/token-boosts/latest/v1", "dexscreener-boost"),
         "community-takeovers": ("/community-takeovers/latest/v1", "dexscreener-takeover"),
         "ads": ("/ads/latest/v1", "dexscreener-ad")}


def solana_tokens(data) -> list[str]:
    return list(dict.fromkeys(row["tokenAddress"] for row in data
                if isinstance(row, dict) and row.get("chainId") == "solana"
                and ADDRESS.fullmatch(str(row.get("tokenAddress", "")))))


class DexScreener:
    def __init__(self, http: JsonClient, base_url: str):
        self.http, self.base_url = http, base_url

    async def discover(self) -> list[str]:
        data = await self.http.request("GET", self.base_url + "/token-profiles/latest/v1")
        if not isinstance(data, list):
            raise DataUnavailable("Unexpected profiles response")
        # Profiles are a biased, partial candidate feed, not all new pools.
        return solana_tokens(data)

    async def discover_feeds(self, feeds: list[str]) -> tuple[dict[str, str], list[str]]:
        """Tokens with the source of the first feed listing them, plus the feeds that failed.

        Every feed is a biased, partial candidate list. Fails only if all feeds fail.
        """
        found, failed = {}, []
        for feed in feeds:
            path, source = FEEDS[feed]
            try:
                data = await self.http.request("GET", self.base_url + path)
                if not isinstance(data, list):
                    raise DataUnavailable("Unexpected candidate list response")
            except DataUnavailable:
                failed.append(feed)
                continue
            for token in solana_tokens(data):
                found.setdefault(token, source)
        if feeds and len(failed) == len(feeds):
            raise DataUnavailable("All candidate lists unavailable")
        return found, failed

    async def snapshot(self, token: str, preferred_pair: str | None = None) -> Snapshot | None:
        data = await self.http.request("GET", f"{self.base_url}/token-pairs/v1/solana/{token}")
        if not isinstance(data, list):
            raise DataUnavailable("Unexpected token-pairs response")
        pairs = [p for p in data if isinstance(p, dict) and p.get("chainId") == "solana"
                 and (p.get("baseToken") or {}).get("address") == token and p.get("pairAddress")]
        if preferred_pair:
            pairs = [p for p in pairs if p["pairAddress"] == preferred_pair]
        if not pairs:
            return None
        selected = max(pairs, key=lambda p: number((p.get("liquidity") or {}).get("usd")) or 0)
        return parse_pair(selected, utcnow())

    async def snapshots(self, tokens: list[str], preferred: dict[str, str | None]) -> dict[str, Snapshot | None]:
        """Fetch up to 30 tokens per request; retain receive time before risk RPCs."""
        results = {}
        for offset in range(0, len(tokens), 30):
            batch = tokens[offset:offset + 30]
            data = await self.http.request("GET", self.base_url + "/tokens/v1/solana/" + ",".join(batch))
            received = utcnow()
            if not isinstance(data, list):
                raise DataUnavailable("Unexpected batch token response")
            for token in batch:
                pairs = [p for p in data if isinstance(p, dict) and p.get("chainId") == "solana"
                         and isinstance(p.get("baseToken"), dict) and p["baseToken"].get("address") == token
                         and p.get("pairAddress") and (not preferred.get(token) or p["pairAddress"] == preferred[token])]
                try:
                    selected = max(pairs, key=lambda p: number((p.get("liquidity") or {}).get("usd")) or 0) if pairs else None
                    results[token] = parse_pair(selected, received) if selected else None
                except (ValueError, TypeError, KeyError, AttributeError):
                    results[token] = None
        return results
