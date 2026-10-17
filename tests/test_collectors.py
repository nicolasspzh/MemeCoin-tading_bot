from datetime import UTC, datetime
from decimal import Decimal

import aiohttp
import base64
import struct
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from collectors.dexscreener import DexScreener, parse_pair
from collectors.http import DataUnavailable, JsonClient
from collectors.solana import Solana, TOKEN_PROGRAM

TOKEN = "So11111111111111111111111111111111111111112"


def pair():
    return {"chainId": "solana", "baseToken": {"address": TOKEN, "symbol": "SAMPLE"},
            "pairAddress": "POOL", "priceUsd": "0.0034", "liquidity": {"usd": 25000},
            "marketCap": 100000, "volume": {"m5": 9000},
            "txns": {"m5": {"buys": 55, "sells": 20}}, "priceChange": {"m5": -1.2},
            "pairCreatedAt": 1767225300000}


def test_parser_preserves_unknown_metrics_and_rejects_nan():
    value = pair()
    value.pop("marketCap")
    value["priceUsd"] = "NaN"
    snapshot = parse_pair(value, datetime.now(UTC))
    assert snapshot.price_usd is None and snapshot.market_cap_usd is None
    assert snapshot.change_5m_pct == Decimal("-1.2")
    assert snapshot.raw == value


async def test_http_dex_and_solana_contracts():
    calls = []
    async def profiles(request):
        return web.json_response([{"chainId": "solana", "tokenAddress": TOKEN},
                                  {"chainId": "ethereum", "tokenAddress": "0xBAD"}])
    async def pairs(request):
        return web.json_response([pair()])
    async def rpc(request):
        payload = await request.json()
        calls.append(payload["method"])
        if payload["method"] == "getAccountInfo":
            mint = bytearray(82)
            struct.pack_into("<Q", mint, 36, 1000)
            mint[45] = 1
            result = {"context": {"slot": 100}, "value": {"owner": TOKEN_PROGRAM,
                      "data": [base64.b64encode(mint).decode(), "base64"]}}
        else:
            result = {"context": {"slot": 100}, "value": [{"address": "A", "amount": "100"}, {"address": "B", "amount": "50"}]}
        return web.json_response({"jsonrpc": "2.0", "id": 1, "result": result})
    app = web.Application()
    app.router.add_get("/token-profiles/latest/v1", profiles)
    app.router.add_get("/token-pairs/v1/solana/{token}", pairs)
    app.router.add_post("/rpc", rpc)
    async with TestServer(app) as server, aiohttp.ClientSession() as session:
        http = JsonClient(session, interval=0)
        dex = DexScreener(http, str(server.make_url("")))
        assert await dex.discover() == [TOKEN]
        snapshot = await dex.snapshot(TOKEN)
        assert snapshot.price_usd == Decimal(".0034")
        assert await dex.snapshot(TOKEN, "MISSING") is None
        solana = Solana(http, str(server.make_url("/rpc")))
        risk = await solana.mint_risk(TOKEN)
        assert risk.mint_authority is False and risk.freeze_authority is False
        assert risk.top10_account_fraction == Decimal(".15")
        assert calls == ["getAccountInfo", "getTokenLargestAccounts"]
        with pytest.raises(ValueError, match="read-only"):
            await solana.rpc("sendTransaction", [])


OTHER = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


async def test_candidate_feeds_keep_first_source_and_tolerate_one_failed_list():
    async def profiles(request):
        return web.json_response([{"chainId": "solana", "tokenAddress": TOKEN}])
    async def boosts(request):
        return web.json_response([{"chainId": "solana", "tokenAddress": TOKEN, "amount": 10},
                                  {"chainId": "solana", "tokenAddress": OTHER},
                                  {"chainId": "solana", "tokenAddress": "not-an-address"}])
    app = web.Application()
    app.router.add_get("/token-profiles/latest/v1", profiles)
    app.router.add_get("/token-boosts/latest/v1", boosts)
    async with TestServer(app) as server, aiohttp.ClientSession() as session:
        dex = DexScreener(JsonClient(session, interval=0), str(server.make_url("")))
        found, failed = await dex.discover_feeds(["token-profiles", "token-boosts", "community-takeovers"])
        assert found == {TOKEN: "dexscreener-profile", OTHER: "dexscreener-boost"}
        assert failed == ["community-takeovers"]
        with pytest.raises(DataUnavailable, match="All candidate lists"):
            await dex.discover_feeds(["community-takeovers", "ads"])


async def test_rate_limit_retried_and_auth_failure_not_retried():
    calls = {"retry": 0, "denied": 0}
    async def retry(request):
        calls["retry"] += 1
        return web.json_response({"ok": True}, status=429 if calls["retry"] == 1 else 200,
                                 headers={"Retry-After": "1"})
    async def denied(request):
        calls["denied"] += 1
        return web.json_response({}, status=403)
    app = web.Application()
    app.router.add_get("/retry", retry)
    app.router.add_get("/denied", denied)
    async with TestServer(app) as server, aiohttp.ClientSession() as session:
        http = JsonClient(session, interval=0)
        assert await http.request("GET", str(server.make_url("/retry"))) == {"ok": True}
        with pytest.raises(DataUnavailable, match="HTTP 403"):
            await http.request("GET", str(server.make_url("/denied")))
    assert calls == {"retry": 2, "denied": 1}


async def test_rpc_errors_do_not_become_safe_risk():
    class FakeHttp:
        async def request(self, *args, **kwargs):
            return {"error": {"code": -32005, "message": "unavailable"}}
    with pytest.raises(DataUnavailable, match="RPC getAccountInfo: no endpoint available"):
        await Solana(FakeHttp(), "https://rpc.example").mint_risk(TOKEN)


async def test_nonexistent_mint_is_a_data_error():
    class FakeHttp:
        async def request(self, *args, **kwargs):
            return {"result": {"value": None}}
    with pytest.raises(DataUnavailable, match="not found"):
        await Solana(FakeHttp(), "https://rpc.example").mint_risk(TOKEN)


async def test_unknown_token_program_is_explicitly_unsupported():
    class FakeHttp:
        async def request(self, *args, **kwargs):
            return {"result": {"context": {"slot": 100}, "value": {"owner": "UnknownProgram"}}}
    risk = await Solana(FakeHttp(), "https://rpc.example").mint_risk(TOKEN)
    assert risk.supported_program is False
    assert risk.top10_account_fraction is None


async def test_batch_quotes_preserve_requested_pool_and_missing_tokens():
    class FakeHttp:
        def __init__(self):
            self.calls = []
        async def request(self, method, url):
            self.calls.append(url)
            other = pair(); other["pairAddress"] = "OTHER"; other["liquidity"]["usd"] = 900000
            return [other, pair()]
    http = FakeHttp()
    result = await DexScreener(http, "https://dex.example").snapshots([TOKEN, "MISSING"], {TOKEN: "POOL"})
    assert result[TOKEN].pair == "POOL" and result["MISSING"] is None
    assert len(http.calls) == 1 and "/tokens/v1/solana/" in http.calls[0]


async def test_batch_quotes_split_at_api_limit_and_share_receive_time():
    class FakeHttp:
        def __init__(self):
            self.batches = []
        async def request(self, method, url):
            tokens = url.rsplit("/", 1)[1].split(","); self.batches.append(tokens)
            values = []
            for token in tokens:
                p = pair(); p["baseToken"]["address"] = token; values.append(p)
            return values
    http = FakeHttp()
    tokens = [str(i) for i in range(31)]
    results = await DexScreener(http, "https://dex.example").snapshots(tokens, {})
    assert [len(b) for b in http.batches] == [30, 1]
    assert len({results[t].received_at for t in tokens[:30]}) == 1
    assert set(results) == set(tokens)


@pytest.mark.parametrize("field,value", [("txns", {"m5": "malformed"}), ("liquidity", "malformed")])
async def test_malformed_quote_does_not_discard_other_tokens_in_batch(field, value):
    class FakeHttp:
        async def request(self, *args):
            bad = pair(); bad["baseToken"]["address"] = "BAD"; bad[field] = value
            return [bad, pair()]
    results = await DexScreener(FakeHttp(), "https://dex.example").snapshots([TOKEN, "BAD"], {})
    assert results[TOKEN] is not None and results["BAD"] is None
