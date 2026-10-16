"""PumpSwap layout, fees and liquidity as documented in docs/R3-STUFE-A-PUMPSWAP.md."""
import base64
import copy
import json
import struct
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from collectors.holders import (PUMP_FEE_CONFIG, PUMP_FEE_PROGRAM, PUMP_PROGRAM, USDC_MINT, WSOL_MINT,
                                assess_bundle, fee_config, on_curve, pool_state, program_address, pump_fee,
                                verify_holders)
from collectors.http import DataUnavailable
from collectors.mint import address_bytes
from config.settings import Settings
from data.models import MintRisk
from trading.risk import onchain_liquidity_usd, risk_reasons

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def fixture():
    v = copy.deepcopy(load("pumpswap_risk_accounts.json"))
    fee = load("pumpswap_fee_config_20260908.json")
    keys, values = v["keys"], v["result"]["value"]
    return {"token": keys[0], "pair": keys[1], "keys": keys + [PUMP_FEE_CONFIG],
            "result": {"context": v["result"]["context"], "value": values + [fee["account"]]},
            "accounts": dict(zip(keys + [PUMP_FEE_CONFIG], values + [fee["account"]]))}


def raw_pool(fx):
    return bytearray(base64.b64decode(fx["accounts"][fx["pair"]]["data"][0]))


def with_pool(fx, raw):
    fx = copy.deepcopy(fx)
    account = fx["accounts"][fx["pair"]]
    account["data"] = [base64.b64encode(bytes(raw)).decode(), "base64"]
    fx["result"]["value"][1] = account
    return fx


def assess(fx):
    pool = pool_state(fx["accounts"][fx["pair"]], fx["pair"])
    base_vault = pool["vaults"][0]
    return assess_bundle(fx["token"], fx["pair"], fx["keys"], fx["result"], pool, [base_vault], "fixture")[0]


def test_program_addresses_match_solana_reference():
    # Vectors generated with solders 0.26.0 Pubkey.find_program_address, including bump 254.
    for vector in load("pda_vectors_solders_0_26.json"):
        seeds = [bytes.fromhex(seed) for seed in vector["seeds_hex"]]
        assert program_address(seeds, vector["program"]) == (vector["address"], vector["bump"])
    assert program_address([b"fee_config", address_bytes(PUMP_PROGRAM)], PUMP_FEE_PROGRAM)[0] == PUMP_FEE_CONFIG
    assert on_curve(address_bytes(PUMP_PROGRAM)) is True  # program ids are ordinary keys


def test_fee_config_snapshot_decodes_documented_tiers():
    config = fee_config(load("pumpswap_fee_config_20260908.json")["account"])
    assert config["flat"] == (25, 5, 0) and config["exotic"] == (0, 0, 0)
    assert len(config["tiers"]) == len(config["stable"]) == 25
    assert config["tiers"][0] == (0, (2, 93, 30)) and config["tiers"][1] == (420 * 10**9, (20, 5, 95))
    assert config["tiers"][-1] == (98240 * 10**9, (20, 5, 5))
    assert config["stable"][1] == (59000 * 10**6, (20, 5, 95))


@pytest.mark.parametrize("mutation", ["owner", "discriminator", "truncated", "unsorted"])
def test_malformed_fee_config_is_rejected(mutation):
    account = copy.deepcopy(load("pumpswap_fee_config_20260908.json")["account"])
    raw = bytearray(base64.b64decode(account["data"][0]))
    if mutation == "owner":
        account["owner"] = PUMP_PROGRAM
    elif mutation == "discriminator":
        raw[0] ^= 1
    elif mutation == "truncated":
        raw = raw[:100]
    else:
        struct.pack_into("<Q", raw, 8 + 1 + 32 + 24 + 4 + 40, 0)  # second tier threshold below first
        struct.pack_into("<Q", raw, 8 + 1 + 32 + 24 + 4, 10**12)
    account["data"] = [base64.b64encode(bytes(raw)).decode(), "base64"]
    with pytest.raises(DataUnavailable):
        fee_config(account)


def test_fee_selection_follows_sdk_rules():
    config = fee_config(load("pumpswap_fee_config_20260908.json")["account"])
    sol = lambda cap: pump_fee(config, canonical=True, quote_mint=WSOL_MINT, market_cap=cap)
    assert sol(0) == ((2, 93, 30), "tiers")
    assert sol(420 * 10**9 - 1) == ((2, 93, 30), "tiers")
    assert sol(420 * 10**9) == ((20, 5, 95), "tiers")
    assert sol(10**20) == ((20, 5, 5), "tiers")
    assert pump_fee(config, canonical=True, quote_mint=USDC_MINT, market_cap=300000 * 10**6) == ((20, 5, 90), "stable_tiers")
    assert pump_fee(config, canonical=False, quote_mint=WSOL_MINT, market_cap=0) == ((25, 5, 0), "flat")
    assert pump_fee(config, canonical=True, quote_mint="Other1111111111111111111111111111111111111", market_cap=0) == ((25, 5, 0), "flat")


def test_real_boosted_pool_gets_tier_fee_from_market_cap(fixture):
    h = assess(fixture)
    pool, raw = h.pool_details, raw_pool(fixture)
    assert h.status == "complete" and "pumpswap_dynamic_fees_unverified" not in h.reasons
    assert pool["canonical"] is True and pool["fee_schedule"] == "tiers"
    # Independent recomputation from raw bytes: effective quote = vault + signed virtual reserves.
    vault = lambda address: struct.unpack_from("<Q", base64.b64decode(fixture["accounts"][address]["data"][0]), 64)[0]
    virtual = int.from_bytes(raw[245:261], "little", signed=True)
    supply = struct.unpack_from("<Q", base64.b64decode(fixture["accounts"][fixture["token"]]["data"][0]), 36)[0]
    cap = (vault(pool["vaults"][1]) + virtual) * supply // vault(pool["vaults"][0])
    assert pool["market_cap_quote_raw"] == str(cap)
    expected = sum(pump_fee(fee_config(fixture["accounts"][PUMP_FEE_CONFIG]), canonical=True,
                            quote_mint=WSOL_MINT, market_cap=cap)[0])
    # About 56,600 SOL market cap: tier from 54,030 SOL, 0.53 % per trade.
    assert 54030 * 10**9 <= cap < 58940 * 10**9
    assert pool["known_fee_bps"] == str(expected) == "53"
    # Waiting fees stay in the quote vault but are not liquidity.
    protocol_fees, creator_fees = struct.unpack_from("<QQ", raw, 271)
    assert pool["raw_vault_reserves_after_fees"][1] == str(vault(pool["vaults"][1]) - protocol_fees - creator_fees)


@pytest.mark.parametrize("offset,value,reason", [
    (243, 1, "unsupported_pumpswap_mode"),   # mayhem
    (244, 1, "unsupported_pumpswap_mode"),   # cashback
    (269, 1, "unsupported_pumpswap_mode"),   # reserved editable creator fee
    (261, 100, "custom_pool_creator_fee"),
    (295, 7, "unsupported_pool_fields"),     # nonzero bytes beyond the documented layout
])
def test_special_pool_modes_stay_blocked(fixture, offset, value, reason):
    raw = raw_pool(fixture); raw[offset] = value
    assert reason in pool_state(with_pool(fixture, raw)["accounts"][fixture["pair"]], fixture["pair"])["reasons"]


def test_holder_reward_pools_and_negative_virtual_reserves_are_allowed(fixture):
    raw = raw_pool(fixture); raw[270] = 1
    raw[245:261] = (-1000).to_bytes(16, "little", signed=True)
    pool = pool_state(with_pool(fixture, raw)["accounts"][fixture["pair"]], fixture["pair"])
    assert pool["reasons"] == [] and pool["holder_reward"] is True and pool["virtual_quote_reserves"] == "-1000"


def test_truncated_new_fields_are_rejected(fixture):
    raw = raw_pool(fixture)[:275]
    with pytest.raises(DataUnavailable, match="Truncated"):
        pool_state(with_pool(fixture, raw)["accounts"][fixture["pair"]], fixture["pair"])


def snapshot_for(quote, fx, holders, *, age_minutes=30, quote_mint=WSOL_MINT, price_native="0.00000003"):
    now = holders.checked_at
    s = quote(source="dexscreener").model_copy(update={"token": fx["token"], "pair": fx["pair"], "received_at": now})
    s.pair_created_at = now - timedelta(minutes=age_minutes)
    s.raw = {"quoteToken": {"address": quote_mint}, "priceUsd": "0.000006", "priceNative": price_native}
    s.mint_risk = MintRisk(checked_at=now, supported_program=True, mint_authority=False, freeze_authority=False,
                           risk_version=3, holder_risk=holders)
    return s


def test_onchain_liquidity_uses_real_quote_reserve(fixture, quote):
    h = assess(fixture)
    s = snapshot_for(quote, fixture, h)
    real_quote = Decimal(h.pool_details["raw_vault_reserves_after_fees"][1]) / 10**9
    assert onchain_liquidity_usd(s, h) == 2 * real_quote * Decimal("0.000006") / Decimal("0.00000003")
    assert onchain_liquidity_usd(snapshot_for(quote, fixture, h, quote_mint=USDC_MINT), h) is None
    tiny = snapshot_for(quote, fixture, h, price_native="1")
    assert "insufficient_onchain_liquidity" in risk_reasons(tiny, h.checked_at, Settings())
    s.raw = {}
    assert "unknown_onchain_liquidity" in risk_reasons(s, h.checked_at, Settings())


def test_pumpswap_entry_waits_for_boost_window(fixture, quote):
    h = assess(fixture)
    early = snapshot_for(quote, fixture, h, age_minutes=5)
    late = snapshot_for(quote, fixture, h, age_minutes=11)
    assert "pumpswap_boost_window" in risk_reasons(early, h.checked_at, Settings())
    assert "pumpswap_boost_window" not in risk_reasons(late, h.checked_at, Settings())
    assert "pumpswap_boost_window" not in risk_reasons(early, h.checked_at, Settings(), entry=False)


async def test_verification_reads_fee_account_in_same_batch(fixture):
    class RPC:
        _last_host = "fixture"

        def __init__(self):
            self.calls = []

        async def rpc(self, method, params):
            self.calls.append((method, params))
            slot = fixture["result"]["context"]["slot"]
            if method == "getAccountInfo":
                return {"context": {"slot": slot}, "value": fixture["accounts"][params[0]]}
            return {"context": {"slot": slot}, "value": [fixture["accounts"][k] for k in params[0]]}

    rpc = RPC()
    pool = pool_state(fixture["accounts"][fixture["pair"]], fixture["pair"])
    h, _ = await verify_holders(rpc, fixture["token"], fixture["pair"], [pool["vaults"][0]],
                                fixture["result"]["context"]["slot"])
    assert [m for m, _ in rpc.calls] == ["getAccountInfo", "getMultipleAccounts"]
    assert PUMP_FEE_CONFIG in rpc.calls[1][1][0] and "known_fee_bps" in h.pool_details


def test_measured_pumpswap_fee_replaces_fixed_assumption(fixture, quote):
    from trading.risk import pool_fee_bps
    h = assess(fixture)
    s = snapshot_for(quote, fixture, h)
    assert pool_fee_bps(s, Settings()) == Decimal(53)
    reasons = risk_reasons(s, h.checked_at, Settings())
    assert not {"pool_fee_above_limit", "unknown_pool_fees", "pumpswap_dynamic_fees_unverified"} & set(reasons)
    assert "pool_fee_above_limit" in risk_reasons(s, h.checked_at, Settings(max_pool_fee_bps=Decimal(50)))
    # Without the fee account the fee is unknown and never falls back to the fixed 0.3 %.
    fx = copy.deepcopy(fixture); fx["keys"] = fx["keys"][:-1]; fx["result"]["value"] = fx["result"]["value"][:-1]
    unknown = snapshot_for(quote, fx, assess(fx))
    assert pool_fee_bps(unknown, Settings()) is None
    assert "unknown_pool_fees" in risk_reasons(unknown, unknown.received_at, Settings())


def test_trade_liquidity_is_the_lower_of_dex_and_onchain(fixture, quote):
    from trading.risk import trade_liquidity_usd
    h = assess(fixture)
    s = snapshot_for(quote, fixture, h)
    onchain = onchain_liquidity_usd(s, h)
    s.liquidity_usd = onchain * 3
    assert trade_liquidity_usd(s) == onchain
    s.liquidity_usd = onchain / 2
    assert trade_liquidity_usd(s) == onchain / 2


def test_adverse_move_limit_is_three_percent(quote):
    from data.models import Wallet
    from trading.execution import Execution, attempt
    assert Execution().max_adverse_move_bps == Settings().paper_max_adverse_move_bps == Decimal(300)
    s = quote()
    order = {"id": 1, "token": s.token, "action": "BUY", "budget_usd": "2", "signal_at": s.received_at.isoformat(),
             "signal_snapshot_id": 1}
    run = lambda signal: attempt(Wallet(), {**order, "signal_price_usd": signal}, s, 2, s.received_at, Settings(),
                                 Execution(failure_probability=0), Decimal(1))
    assert run("0.98").status == "filled"        # +2.0 % since the signal
    late = run("0.96")                            # +4.2 % since the signal
    assert late.status == "failed" and late.reason == "price_moved_beyond_limit"
