"""Read-only RPC, per-method endpoint cooldowns, and timestamp-preserving cache."""
import time
from collections import Counter
from decimal import Decimal
from urllib.parse import urlsplit

from collectors.http import DataUnavailable, JsonClient
from collectors.mint import TOKEN_PROGRAM, decode_mint
from data.models import MintRisk, utcnow


class Solana:
    def __init__(self, http: JsonClient, url: str, fallback_urls: list[str] | None = None,
                 *, cache_seconds: float = 30, budget=None, cache_partial=False):
        self.http = http
        self.urls = list(dict.fromkeys([url, *(fallback_urls or [])]))
        self.cache_seconds = cache_seconds
        self.budget, self.cache_partial = budget, cache_partial
        self._cooldown, self._preferred, self._cache = {}, {}, {}
        self._diagnostics = {}
        self._last_host = None
        self.stats = Counter()

    def endpoint_status(self) -> list[dict]:
        """Expose method availability without URLs, credentials or response bodies."""
        now = time.monotonic()
        return [{"endpoint": index + 1, "host": urlsplit(url).hostname,
                 "methods": {method: {
                     **self._diagnostics.get((index, method), {"state": "not_exercised", "attempts": 0}),
                     "cooldown_remaining_seconds": round(max(0, self._cooldown.get((index, method), 0) - now), 3),
                 } for method in ("getAccountInfo", "getTokenLargestAccounts")}}
                for index, url in enumerate(self.urls)]

    async def rpc(self, method: str, params: list):
        if method not in {"getHealth", "getAccountInfo", "getTokenLargestAccounts",
                          "getSignaturesForAddress", "getTransaction", "getMultipleAccounts"}:
            raise ValueError("Unsupported read-only RPC method")
        preferred = self._preferred.get(method, 0)
        indices = [preferred, *(i for i in range(len(self.urls)) if i != preferred)]
        for index in indices:
            key = (index, method)
            if self._cooldown.get(key, 0) > time.monotonic():
                self.stats["cooldown_skips"] += 1
                continue
            if self.budget is not None:
                self.budget.reserve()
            diagnostic = self._diagnostics.setdefault(key, {"attempts": 0})
            diagnostic["attempts"] += 1
            started, code = time.monotonic(), None
            try:
                self.stats["requests"] += 1
                data = await self.http.request("POST", self.urls[index], attempts=1,
                    json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
                if not isinstance(data, dict) or "result" not in data or "error" in data:
                    error = data.get("error", {}) if isinstance(data, dict) else {}
                    code = error.get("code") if isinstance(error, dict) else None
                    code = code if isinstance(code, int) and not isinstance(code, bool) else None
                    status = 429 if code in (429, -32005) else 403 if code in (-32601, -32602) else None
                    raise DataUnavailable(f"RPC {method} failed", status=status)
                self._preferred[method] = index
                self._last_host = urlsplit(self.urls[index]).hostname
                self.stats["successes"] += 1
                if index:
                    self.stats["fallback_successes"] += 1
                diagnostic.update(state="response_received", http_status=None, rpc_code=None,
                                  checked_at=utcnow().isoformat())
                return data["result"]
            except DataUnavailable as exc:
                self.stats[f"errors_{exc.status or 'transport'}"] += 1
                delay = 300 if exc.status in (401, 403) else 60 if exc.status == 429 else 15
                self._cooldown[key] = time.monotonic() + max(delay, exc.retry_after)
                diagnostic.update(state="unavailable", http_status=exc.status if code is None else None, rpc_code=code,
                                  checked_at=utcnow().isoformat())
            finally:
                diagnostic["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
        raise DataUnavailable(f"RPC {method}: no endpoint available (failed or cooling down)")

    async def mint_risk(self, token: str, pair: str | None = None) -> MintRisk:
        cache_key = (token, pair)
        cached = self._cache.get(cache_key)
        if cached and 0 <= (utcnow() - cached.checked_at).total_seconds() < self.cache_seconds:
            self.stats["cache_hits"] += 1
            return cached.model_copy(deep=True)
        result = await self.rpc("getAccountInfo", [token, {"encoding": "base64", "commitment": "confirmed"}])
        account = result.get("value") if isinstance(result, dict) else None
        if not isinstance(account, dict):
            raise DataUnavailable("Mint account not found")
        values = decode_mint(account, token)
        now = utcnow()
        slot = (result.get("context") or {}).get("slot")
        if not isinstance(slot, int) or isinstance(slot, bool) or slot < 0:
            raise DataUnavailable("Missing mint context slot")
        risk = MintRisk(checked_at=now, mint_checked_at=now, mint_slot=slot,
                        mint_rpc_host=self._last_host, risk_version=3 if pair else None, **values)
        needs_concentration = (risk.supported_program and risk.extension_checks_passed
                               and risk.mint_authority is False and risk.freeze_authority is False)
        if needs_concentration:
            try:
                largest = await self.rpc("getTokenLargestAccounts", [token, {"commitment": "confirmed"}])
                holder_slot = (largest.get("context") or {}).get("slot")
                if (not isinstance(holder_slot, int) or isinstance(holder_slot, bool) or holder_slot < 0
                        or abs(holder_slot - slot) > 150):
                    raise DataUnavailable("Inconsistent concentration context slot")
                rows = largest.get("value")
                if not isinstance(rows, list) or not 1 <= len(rows) <= 20:
                    raise DataUnavailable("Missing largest-account amounts")
                amounts, addresses = [], set()
                for row in rows:
                    amount, address = row.get("amount"), row.get("address")
                    if (not isinstance(amount, str) or not amount.isascii() or not amount.isdigit()
                            or len(amount) > 20 or int(amount) > 2**64 - 1 or not isinstance(address, str)
                            or not address or address in addresses):
                        raise DataUnavailable("Invalid largest-account amounts")
                    addresses.add(address)
                    amounts.append(Decimal(amount))
                supply = Decimal(risk.raw_supply)
                if supply <= 0 or sum(amounts) > supply:
                    raise DataUnavailable("Inconsistent supply and account amounts")
                risk.top10_account_fraction = sum(sorted(amounts, reverse=True)[:10]) / supply
                risk.concentration_checked_at = utcnow()
                risk.concentration_slot = holder_slot
                risk.concentration_rpc_host = self._last_host
                if pair:
                    from collectors.holders import verify_holders
                    risk.holder_risk, current_mint = await verify_holders(self, token, pair,
                        [row["address"] for row in rows], holder_slot)
                    if current_mint is not None:
                        for field, value in current_mint.items():
                            setattr(risk, field, value)
                        risk.mint_slot = risk.holder_risk.slot
                        risk.mint_checked_at = risk.holder_risk.checked_at
                        risk.mint_rpc_host = risk.holder_risk.rpc_host
            except (DataUnavailable, TypeError, ValueError, AttributeError) as exc:
                risk.data_errors.append(str(exc) if isinstance(exc, DataUnavailable) else "Malformed concentration response")
        risk.checked_at = utcnow()
        if not risk.data_errors or self.cache_partial:
            if len(self._cache) >= 512:
                self._cache.pop(next(iter(self._cache)))
            self._cache[cache_key] = risk.model_copy(deep=True)
        return risk
