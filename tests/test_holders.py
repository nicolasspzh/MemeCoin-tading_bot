import base64
import copy
import hashlib
import json
import struct
from decimal import Decimal
from pathlib import Path

import pytest

from collectors.holders import (CPMM_PROGRAM, PUMP_PROGRAM, assess_bundle, encode58,
                                owner_bounds, pool_state, token_account)
from collectors.http import DataUnavailable
from collectors.mint import TOKEN_PROGRAM, address_bytes
from collectors.solana import Solana
from config.settings import Settings
from data.models import HolderAccount, MintRisk, utcnow
from trading.risk import risk_reasons, unobserved_account_bound

SOL = "So11111111111111111111111111111111111111112"


def key(number):
    return encode58(bytes([number]) * 32)


def account(program, raw):
    return {"owner": program, "executable": False, "data": [base64.b64encode(raw).decode(), "base64"]}


def mint(supply, authority=None):
    raw = bytearray(82)
    if authority:
        struct.pack_into("<I", raw, 0, 1); raw[4:36] = address_bytes(authority)
    struct.pack_into("<Q", raw, 36, supply)
    raw[44:46] = bytes([6, 1])
    return account(TOKEN_PROGRAM, raw)


def token_acc(token, owner, amount):
    raw = bytearray(165)
    raw[:32], raw[32:64] = address_bytes(token), address_bytes(owner)
    struct.pack_into("<Q", raw, 64, amount); raw[108] = 1
    return account(TOKEN_PROGRAM, raw)


@pytest.fixture
def bundle():
    token, pair, config, creator, vault0, vault1, lp = [key(n) for n in (4, 3, 2, 9, 10, 11, 12)]
    raw = bytearray(637); raw[:8] = hashlib.sha256(b"account:PoolState").digest()[:8]
    fields = [config, creator, vault0, vault1, lp, token, SOL, TOKEN_PROGRAM, TOKEN_PROGRAM, key(13)]
    for index, value in enumerate(fields): raw[8 + index*32:40 + index*32] = address_bytes(value)
    raw[328] = 255
    struct.pack_into("<Q", raw, 333, 1000)
    pool_account = account(CPMM_PROGRAM, raw)
    expected = pool_state(pool_account, pair)
    authority = expected["authority"]
    raw_config = bytearray(236); raw_config[:8] = hashlib.sha256(b"account:AmmConfig").digest()[:8]
    struct.pack_into("<Q", raw_config, 12, 2500)  # 25 bps
    accounts = {token: mint(1000), pair: pool_account, config: account(CPMM_PROGRAM, raw_config),
                vault0: token_acc(token, authority, 800), vault1: token_acc(SOL, authority, 1000), lp: mint(50, authority)}
    sample = [vault0]
    for n in range(19):
        address = key(40+n); accounts[address] = token_acc(token, key(80+n), 10); sample.append(address)
    keys = list(accounts)
    return {"token": token, "pair": pair, "accounts": accounts, "sample": sample,
            "expected": expected, "keys": keys}


def assess(b):
    return assess_bundle(b["token"], b["pair"], b["keys"],
        {"context": {"slot": 100}, "value": [b["accounts"][k] for k in b["keys"]]},
        b["expected"], b["sample"], "rpc.example")[0]


def risk_snapshot(quote, b, holders):
    now = holders.checked_at
    s = quote().model_copy(update={"token": b["token"], "pair": b["pair"], "received_at": now})
    # 1000 lamports quote reserve priced so that verified two-sided liquidity is USD 20'000.
    s.raw = {"quoteToken": {"address": SOL}, "priceUsd": "1", "priceNative": "0.0000000001"}
    from datetime import timedelta
    s.pair_created_at = now - timedelta(minutes=10)
    s.mint_risk = MintRisk(checked_at=now, supported_program=True, mint_authority=False, freeze_authority=False,
                           top10_account_fraction=Decimal(".89"), risk_version=3, holder_risk=holders)
    return s


def test_verified_vault_is_excluded_with_conservative_unseen_supply(bundle, quote):
    h = assess(bundle)
    assert h.raw_excluded_supply == "800" and h.raw_non_pool_supply == "200"
    assert h.raw_unobserved_supply == "10" and h.observed_owners == 19
    assert h.top10_owner_fraction_lower == Decimal(".5") and h.top10_owner_fraction_upper == Decimal(".55")
    assert h.lp_nonredeemable_fraction == Decimal(".95")
    s = risk_snapshot(quote, bundle, h)
    assert risk_reasons(s, h.checked_at, Settings()) == []  # raw .89 is retained for audit, not used as owner concentration


def test_split_accounts_of_same_owner_are_aggregated(bundle, quote):
    for address in bundle["sample"][1:]:
        bundle["accounts"][address] = token_acc(bundle["token"], key(99), 10)
    h = assess(bundle)
    assert h.observed_owners == 1 and h.top10_owner_fraction_lower == Decimal(".95")
    assert "high_top10_owner_concentration" in risk_reasons(risk_snapshot(quote, bundle, h), h.checked_at, Settings())


def test_unobserved_supply_is_bounded_by_smallest_sampled_account(bundle, quote):
    # 181 unseen tokens, but no unseen account can exceed the smallest sampled one (1 = 0.5 %).
    for address in bundle["sample"][1:]:
        bundle["accounts"][address] = token_acc(bundle["token"], key(80 + bundle["sample"].index(address)), 1)
    h = assess(bundle)
    assert h.top10_owner_fraction_lower == Decimal(".05") and h.top10_owner_fraction_upper == Decimal(".955")
    assert unobserved_account_bound(h) == Decimal(".005")
    reasons = risk_reasons(risk_snapshot(quote, bundle, h), h.checked_at, Settings())
    assert not {"coarse_holder_sample", "high_top10_owner_concentration"} & set(reasons)


def test_coarse_sample_keeps_unproven_concentration_blocked(bundle, quote):
    # Smallest sampled account holds 2.5 %, so an unseen account could too: no proof of dispersion.
    for address in bundle["sample"][1:]:
        bundle["accounts"][address] = token_acc(bundle["token"], key(80 + bundle["sample"].index(address)), 5)
    h = assess(bundle)
    assert h.top10_owner_fraction_lower == Decimal(".25") and h.top10_owner_fraction_upper == Decimal(".775")
    assert unobserved_account_bound(h) == Decimal(".025")
    assert "coarse_holder_sample" in risk_reasons(risk_snapshot(quote, bundle, h), h.checked_at, Settings())
    looser = Settings(max_unobserved_account_fraction=Decimal(".03"))
    assert "coarse_holder_sample" not in risk_reasons(risk_snapshot(quote, bundle, h), h.checked_at, looser)


def test_sample_below_rpc_limit_observed_every_account(bundle, quote):
    h = assess(bundle).model_copy(deep=True)
    h.sampled_accounts = h.sampled_accounts[:5]
    h.raw_unobserved_supply = "140"
    assert unobserved_account_bound(h) == 0
    h.raw_non_pool_supply = "0"
    assert unobserved_account_bound(h) is None
    h.raw_non_pool_supply = "200"
    h.top10_owner_fraction_upper = None
    reasons = risk_reasons(risk_snapshot(quote, bundle, h), h.checked_at, Settings())
    assert not {"coarse_holder_sample", "unknown_unobserved_account_size"} & set(reasons)


def test_creator_balance_is_observed_lower_bound_not_developer_identity(bundle, quote):
    for address in bundle["sample"][1:5]:
        bundle["accounts"][address] = token_acc(bundle["token"], bundle["expected"]["creator"], 10)
    h = assess(bundle)
    assert h.creator_observed_fraction == Decimal(".2")
    assert "high_creator_observed_balance" in risk_reasons(risk_snapshot(quote, bundle, h), h.checked_at, Settings())


@pytest.mark.parametrize("fault", ["wrong_vault_owner", "wrong_mint", "delegate", "freeze", "close_authority", "bad_lp_authority", "lp_over_supply", "negative_remaining", "missing_account"])
def test_unverified_or_inconsistent_accounts_never_get_excluded(bundle, fault):
    pool, token = bundle["expected"], bundle["token"]
    vault = pool["vaults"][0]
    if fault == "wrong_vault_owner": bundle["accounts"][vault] = token_acc(token, key(1), 800)
    elif fault == "wrong_mint": bundle["accounts"][vault] = token_acc(key(1), pool["authority"], 800)
    elif fault in ("delegate", "freeze", "close_authority"):
        acc = bundle["accounts"][vault]; raw = bytearray(base64.b64decode(acc["data"][0]))
        raw[{"delegate": 72, "freeze": 108, "close_authority": 129}[fault]] = 2 if fault == "freeze" else 1
        bundle["accounts"][vault] = account(TOKEN_PROGRAM, raw)
    elif fault == "bad_lp_authority": bundle["accounts"][pool["lp_mint"]] = mint(50, key(1))
    elif fault == "lp_over_supply": bundle["accounts"][pool["lp_mint"]] = mint(1001, pool["authority"])
    elif fault == "negative_remaining": bundle["accounts"][token] = mint(850)
    elif fault == "missing_account": bundle["accounts"][bundle["sample"][1]] = None
    with pytest.raises(DataUnavailable): assess(bundle)


def test_outstanding_lp_is_not_assumed_locked(bundle, quote):
    pool = bundle["expected"]
    bundle["accounts"][pool["lp_mint"]] = mint(1000, pool["authority"])
    h = assess(bundle)
    assert h.lp_nonredeemable_fraction == 0
    assert "insufficient_verified_lp_nonredeemable_fraction" in risk_reasons(risk_snapshot(quote, bundle, h), h.checked_at, Settings())


def test_disabled_swap_and_excess_fees_block_entry(bundle, quote):
    acc = bundle["accounts"][bundle["pair"]]; raw = bytearray(base64.b64decode(acc["data"][0]));raw[329] = 4
    bundle["accounts"][bundle["pair"]] = account(CPMM_PROGRAM, raw)
    config = bundle["expected"]["config"]; raw = bytearray(base64.b64decode(bundle["accounts"][config]["data"][0]))
    struct.pack_into("<Q", raw, 12, 30000);bundle["accounts"][config] = account(CPMM_PROGRAM, raw)  # 3 %
    h = assess(bundle)
    reasons = risk_reasons(risk_snapshot(quote, bundle, h), h.checked_at, Settings())
    assert "pool_swaps_disabled" in reasons and "pool_fee_above_limit" in reasons


def test_measured_pool_fee_is_charged_instead_of_fixed_assumption(bundle, quote):
    from trading.execution import Execution, attempt
    from data.models import Wallet
    config = bundle["expected"]["config"]; raw = bytearray(base64.b64decode(bundle["accounts"][config]["data"][0]))
    struct.pack_into("<Q", raw, 12, 10000);bundle["accounts"][config] = account(CPMM_PROGRAM, raw)  # 1 %
    h = assess(bundle)
    s = risk_snapshot(quote, bundle, h)
    assert h.pool_details["known_fee_bps"] == "100"
    assert not {"pool_fee_above_limit", "unknown_pool_fees"} & set(risk_reasons(s, h.checked_at, Settings()))
    order = {"id": 1, "token": s.token, "action": "BUY", "budget_usd": "2", "signal_price_usd": str(s.price_usd),
             "signal_at": s.received_at.isoformat(), "signal_snapshot_id": 1}
    outcome = attempt(Wallet(), order, s, 1, s.received_at, Settings(), Execution(failure_probability=0), Decimal(1))
    fixed = Decimal("0.02") + Decimal("0.005")
    assert outcome.status == "filled" and outcome.fill.fee == Decimal(2) - (Decimal(2) - fixed) / Decimal("1.01")
    assert outcome.wallet.positions[s.token].exit_fee_bps == Decimal(100)


def open_position(bundle, quote):
    from trading.execution import Execution, attempt
    from data.models import Wallet
    s = risk_snapshot(quote, bundle, assess(bundle))
    order = {"id": 1, "token": s.token, "action": "BUY", "budget_usd": "2", "signal_price_usd": str(s.price_usd),
             "signal_at": s.received_at.isoformat(), "signal_snapshot_id": 1}
    outcome = attempt(Wallet(), order, s, 1, s.received_at, Settings(), Execution(failure_probability=0), Decimal(1))
    assert outcome.status == "filled" and outcome.wallet.positions[s.token].exit_check == s.mint_risk
    return outcome.wallet, s


def sell_later(wallet, s, seconds, risk):
    from datetime import timedelta
    from trading.execution import Execution, attempt
    later = s.model_copy(update={"received_at": s.received_at + timedelta(seconds=seconds), "mint_risk": risk})
    order = {"id": 2, "token": s.token, "action": "SELL", "budget_usd": "0", "signal_price_usd": str(s.price_usd),
             "signal_at": later.received_at.isoformat(), "signal_snapshot_id": 2}
    return attempt(wallet, order, later, 2, later.received_at, Settings(), Execution(failure_probability=0), Decimal(1))


def failed_check(s, seconds):
    from datetime import timedelta
    return MintRisk(checked_at=s.received_at + timedelta(seconds=seconds), supported_program=True,
                    mint_authority=False, freeze_authority=False, risk_version=3, data_errors=["holder check failed"])


def test_exit_uses_last_complete_pool_check_when_current_check_failed(bundle, quote):
    wallet, s = open_position(bundle, quote)
    outcome = sell_later(wallet, s, 300, failed_check(s, 300))
    assert outcome.status == "filled"
    fee_bps = Decimal(s.mint_risk.holder_risk.pool_details["known_fee_bps"])
    gross = outcome.fill.quantity * outcome.fill.price
    assert outcome.fill.fee == gross * fee_bps / 10000 + Settings().fixed_fee_usd + Decimal("0.005")
    wallet.positions[s.token].exit_check = None
    assert sell_later(wallet, s, 300, failed_check(s, 300)).reason == \
        "execution_risk:incomplete_onchain_checks,missing_verified_holder_risk"


def test_exit_fallback_check_has_an_age_limit(bundle, quote):
    wallet, s = open_position(bundle, quote)
    outcome = sell_later(wallet, s, Settings().max_exit_check_age_seconds + 1,
                         failed_check(s, Settings().max_exit_check_age_seconds + 1))
    assert outcome.status == "rejected" and "stale_or_future_onchain_checks" in outcome.reason


def test_completed_check_with_a_finding_is_never_replaced(bundle, quote):
    wallet, s = open_position(bundle, quote)
    from datetime import timedelta
    holders = s.mint_risk.holder_risk.model_copy(update={"checked_at": s.received_at + timedelta(seconds=60)})
    found = s.mint_risk.model_copy(update={"checked_at": holders.checked_at, "freeze_authority": True,
                                           "holder_risk": holders})
    outcome = sell_later(wallet, s, 60, found)
    assert outcome.status == "rejected" and "freeze_authority_active_or_unknown" in outcome.reason


def test_position_keeps_only_complete_checks_of_its_own_pool(bundle, quote):
    from trading.paper_wallet import note_check
    wallet, s = open_position(bundle, quote)
    first = wallet.positions[s.token].exit_check
    note_check(wallet, s.model_copy(update={"mint_risk": failed_check(s, 30)}), Settings())
    assert wallet.positions[s.token].exit_check == first
    other = s.model_copy(update={"pair": key(111)})
    note_check(wallet, other, Settings())
    assert wallet.positions[s.token].exit_check == first
    from datetime import timedelta
    newer = s.mint_risk.model_copy(update={"checked_at": s.received_at + timedelta(seconds=60)})
    note_check(wallet, s.model_copy(update={"mint_risk": newer}), Settings())
    assert wallet.positions[s.token].exit_check == newer


def test_fees_cannot_be_mistaken_for_spendable_pool_reserves(bundle):
    raw = bytearray(base64.b64decode(bundle["accounts"][bundle["pair"]]["data"][0]))
    struct.pack_into("<Q", raw, 341, 800)
    bundle["accounts"][bundle["pair"]] = account(CPMM_PROGRAM, raw)
    assert "empty_pool_reserves_after_fees" in assess(bundle).reasons


def test_holder_evidence_is_bound_to_pair_and_original_time(bundle, quote):
    from datetime import timedelta
    h = assess(bundle); s = risk_snapshot(quote, bundle, h)
    s.pair = key(111)
    assert "holder_risk_token_or_pool_mismatch" in risk_reasons(s, h.checked_at, Settings())
    s.pair = bundle["pair"]
    s.mint_risk.holder_risk.checked_at -= timedelta(minutes=10)
    assert "stale_or_future_onchain_checks" in risk_reasons(s, s.received_at, Settings())


@pytest.mark.parametrize("file,program", [("raydium_cpmm_risk_accounts.json", CPMM_PROGRAM), ("pumpswap_risk_accounts.json", PUMP_PROGRAM)])
def test_real_pool_vault_and_lp_account_fixtures(file, program):
    v = json.loads((Path(__file__).parent / "fixtures" / file).read_text())
    token, pair = v["keys"][:2]
    pool = pool_state(v["result"]["value"][1], pair)
    base_vault = pool["vaults"][pool["mints"].index(token)]
    h, _ = assess_bundle(token, pair, v["keys"], v["result"], pool, [base_vault], "fixture")
    assert h.pool_program == program and h.status == "complete"
    assert h.lp_nonredeemable_fraction == 1
    if program == PUMP_PROGRAM:
        # Fixture of 7 October: boosted canonical pool, fee account not part of that batch.
        assert h.pool_details["canonical"] is True and int(h.pool_details["boost_reserves"]) > 0
        assert "unsupported_virtual_quote_reserves" not in h.reasons
        assert "pumpswap_dynamic_fees_unverified" in h.reasons


class RiskHTTP:
    def __init__(self, b):
        self.b = b; self.calls = [];self.slot = 100;self.fail_batch = False
    async def request(self, method, url, **kwargs):
        method, params = kwargs["json"]["method"], kwargs["json"]["params"]
        self.calls.append((method, params))
        b = self.b
        if method == "getAccountInfo":
            value = b["accounts"].get(params[0], {"owner": key(1)})
        elif method == "getTokenLargestAccounts":
            value = [{"address": a, "amount": "800" if a == b["sample"][0] else "10"} for a in b["sample"]]
        elif method == "getMultipleAccounts":
            if self.fail_batch: raise DataUnavailable("HTTP 403", status=403)
            value = [b["accounts"][a] for a in params[0]]
            return {"result": {"context": {"slot": self.slot}, "value": value}}
        else: pytest.fail("Unexpected request")
        return {"result": {"context": {"slot": 100}, "value": value}}


async def test_rpc_risk_cache_is_bound_to_token_and_pool(bundle):
    http = RiskHTTP(bundle); rpc = Solana(http, "https://rpc.example/?key=private", cache_seconds=60)
    first = await rpc.mint_risk(bundle["token"], bundle["pair"])
    assert first.holder_risk.top10_owner_fraction_upper == Decimal(".55")
    again = await rpc.mint_risk(bundle["token"], bundle["pair"])
    assert again.holder_risk.checked_at == first.holder_risk.checked_at and len(http.calls) == 4
    other = await rpc.mint_risk(bundle["token"], key(111))
    assert other.holder_risk.status == "unsupported_pool" and len(http.calls) == 7
    assert "private" not in first.model_dump_json()


async def test_expired_holder_evidence_is_not_reused_after_refresh_failure(bundle, monkeypatch):
    from datetime import timedelta
    clock = [utcnow()]
    monkeypatch.setattr("collectors.solana.utcnow", lambda: clock[0])
    http = RiskHTTP(bundle);rpc = Solana(http, "https://rpc.example", cache_seconds=60)
    first = await rpc.mint_risk(bundle["token"], bundle["pair"])
    assert first.holder_risk is not None
    clock[0] += timedelta(seconds=61)
    http.fail_batch = True
    second = await rpc.mint_risk(bundle["token"], bundle["pair"])
    assert second.holder_risk is None and second.data_errors


@pytest.mark.parametrize("extension", [15, 27, 65535])
def test_vault_hooks_pausability_and_unknown_extensions_are_rejected(bundle, extension):
    from collectors.mint import TOKEN_2022_PROGRAM
    token, pool = bundle["token"], bundle["expected"]
    raw = bytearray(base64.b64decode(token_acc(token, pool["authority"], 800)["data"][0]))
    raw.extend(b"\2" + struct.pack("<HH", extension, 0))
    with pytest.raises(DataUnavailable, match="Unsupported vault extension"):
        token_account(account(TOKEN_2022_PROGRAM, raw), token, vault=True)


@pytest.mark.parametrize("failure", ["batch_failure", "stale_slot"])
async def test_failed_verification_preserves_raw_data_but_cannot_pass(bundle, quote, failure):
    http = RiskHTTP(bundle)
    if failure == "batch_failure": http.fail_batch = True
    else: http.slot = 99
    risk = await Solana(http, "https://rpc.example").mint_risk(bundle["token"], bundle["pair"])
    assert risk.top10_account_fraction is not None and risk.holder_risk is None and risk.data_errors
    s = quote().model_copy(update={"token": bundle["token"], "pair": bundle["pair"], "mint_risk": risk})
    assert "missing_verified_holder_risk" in risk_reasons(s, risk.checked_at, Settings())


def test_legacy_market_data_is_not_silently_upgraded_to_verified_holders(quote):
    s = quote().model_copy(update={"source": "dexscreener"})
    assert "missing_verified_holder_risk" in risk_reasons(s, s.received_at, Settings())
    assert "missing_verified_holder_risk" not in risk_reasons(s, s.received_at, Settings(require_verified_holder_risk=False))


def test_unseen_supply_bound_covers_owners_outside_sample():
    samples = [HolderAccount(address=str(n), owner=str(n), raw_amount="10") for n in range(20)]
    bounds = owner_bounds(1000, 700, samples)
    # Entire unseen remainder assigned to a previously unseen owner: true top10
    # is 100 + 9*10 = 190, and the computed conservative bound still covers it.
    assert bounds["top10_owner_fraction_lower"] <= Decimal(190) / 300 <= bounds["top10_owner_fraction_upper"]


def test_raw_evidence_is_deduplicated_and_linked_to_snapshots(bundle, quote, engine):
    from datetime import timedelta
    h = assess(bundle); s = risk_snapshot(quote, bundle, h)
    engine.process(s, s.received_at)
    later = s.model_copy(update={"received_at": s.received_at + timedelta(seconds=20)})
    engine.process(later, later.received_at)
    rows = engine.db.conn.execute("SELECT sha256,payload FROM risk_evidence").fetchall()
    assert len(rows) == 1
    assert hashlib.sha256(rows[0][1].encode()).hexdigest() == h.evidence_sha256
    stored = engine.db.conn.execute("SELECT payload FROM snapshots").fetchone()[0]
    assert "evidence_payload" not in stored and h.evidence_sha256 in stored
    proof = json.loads(rows[0][1])
    rebuilt, _ = assess_bundle(proof["token"], proof["pair"], list(proof["accounts"]),
        {"context": {"slot": proof["slot"]}, "value": list(proof["accounts"].values())},
        bundle["expected"], proof["sampled_addresses"], proof["rpc_host"])
    assert rebuilt.top10_owner_fraction_upper == h.top10_owner_fraction_upper


def test_tampered_evidence_rolls_back_observation(bundle, quote, engine):
    h = assess(bundle); s = risk_snapshot(quote, bundle, h)
    h.evidence_payload["slot"] += 1
    with pytest.raises(ValueError, match="fingerprint"):
        engine.process(s, s.received_at)
    assert engine.db.counts()["snapshots"] == 0


def test_replay_freezes_referenced_evidence_and_preserves_snapshot_hash(bundle, quote, engine, tmp_path):
    from backtesting.__main__ import freeze_input
    from backtesting.replay import read_observations
    import sqlite3
    holder = assess(bundle)
    snapshot = risk_snapshot(quote, bundle, holder)
    engine.process(snapshot, snapshot.received_at)
    records, original = read_observations(tmp_path / "test.sqlite3", allow_demo=True)
    target = tmp_path / "frozen.sqlite3"
    freeze_input(target, records, "demo")
    loaded, frozen = read_observations(target, allow_demo=True)
    assert frozen["snapshots_sha256"] == original["snapshots_sha256"]
    assert loaded[0].snapshot.mint_risk.holder_risk.evidence_payload == holder.evidence_payload
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT count(*) FROM risk_evidence").fetchone()[0] == 1


@pytest.mark.parametrize("damage", ["missing", "changed", "missing_table"])
def test_replay_rejects_dangling_or_damaged_risk_proof(bundle, quote, engine, tmp_path, damage):
    from backtesting.replay import read_observations
    holder = assess(bundle)
    snapshot = risk_snapshot(quote, bundle, holder)
    engine.process(snapshot, snapshot.received_at)
    with engine.db.conn:
        if damage == "missing":
            engine.db.conn.execute("DELETE FROM risk_evidence")
        elif damage == "missing_table":
            engine.db.conn.execute("DROP TABLE risk_evidence")
        else:
            engine.db.conn.execute("UPDATE risk_evidence SET payload='{}'")
    with pytest.raises(ValueError, match="risk evidence"):
        read_observations(tmp_path / "test.sqlite3", allow_demo=True)


async def test_foreign_quote_pool_is_blocked_before_reading_vaults(bundle):
    from collectors.holders import verify_holders
    raw = bytearray(base64.b64decode(bundle["accounts"][bundle["pair"]]["data"][0]))
    raw[200:232] = address_bytes(key(77))  # quote mint is not wSOL/USDC
    bundle["accounts"][bundle["pair"]] = account(CPMM_PROGRAM, raw)
    http = RiskHTTP(bundle)
    h, current = await verify_holders(Solana(http, "https://rpc.example"), bundle["token"], bundle["pair"],
                                      bundle["sample"], 100)
    assert h.status == "unsupported_pool" and h.reasons == ["unsupported_quote_mint"] and current is None
    assert [method for method, _ in http.calls] == ["getAccountInfo"]  # batch request saved
