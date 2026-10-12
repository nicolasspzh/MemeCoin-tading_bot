"""Same-slot account-owner bounds and explicitly verified AMM vault exclusions.

Largest accounts are only a sample. Unobserved supply is conservatively assigned
to the ten largest observed owners to bound concentration from above. Account
owners are signing authorities, not identified persons or proven wallet clusters.
"""
import base64
import binascii
import hashlib
import json
import struct
from collections import defaultdict
from decimal import Decimal

from collectors.http import DataUnavailable
from collectors.mint import TOKEN_PROGRAM, TOKEN_2022_PROGRAM, address_bytes, decode_mint
from collectors.pools import PROGRAM as CPMM_PROGRAM, QUOTE_MINTS
from data.models import HolderAccount, HolderRisk, utcnow

PUMP_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
PUMP_CONFIG = "ADyA8hdefvWN2dbGGWFotbzWxrAvLW83WG6QCVXvJKqw"
TOKEN_PROGRAMS = {TOKEN_PROGRAM, TOKEN_2022_PROGRAM}


def encode58(raw: bytes) -> str:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number, result = int.from_bytes(raw, "big"), ""
    while number:
        number, digit = divmod(number, 58)
        result = alphabet[digit] + result
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + result


def account_bytes(account):
    try:
        value = account["data"]
        if account.get("executable", False) or not isinstance(value, list) or len(value) != 2 or value[1] != "base64":
            raise ValueError
        return base64.b64decode(value[0], validate=True)
    except (KeyError, ValueError, TypeError, binascii.Error, AttributeError):
        raise DataUnavailable("Malformed account bytes") from None


def context_slot(result):
    try:
        slot = result["context"]["slot"]
        if type(slot) is not int or slot < 0:
            raise ValueError
        return slot
    except (KeyError, TypeError, ValueError):
        raise DataUnavailable("Missing account context slot") from None


def pool_state(account, pair):
    program = account.get("owner") if isinstance(account, dict) else None
    if program not in {CPMM_PROGRAM, PUMP_PROGRAM}:
        return None
    raw = account_bytes(account)
    key = lambda offset: encode58(raw[offset:offset + 32])
    reasons = []
    if program == CPMM_PROGRAM:
        if len(raw) != 637 or raw[:8] != hashlib.sha256(b"account:PoolState").digest()[:8]:
            raise DataUnavailable("Unsupported Raydium pool layout")
        authority = encode58(hashlib.sha256(b"vault_and_lp_mint_auth_seed" + bytes([raw[328]])
                                           + address_bytes(program) + b"ProgramDerivedAddress").digest())
        if raw[329] & 4:
            reasons.append("pool_swaps_disabled")
        if raw[329] & ~7 or raw[389] not in (0, 1, 2) or raw[390] not in (0, 1) or any(raw[391:397]) or any(raw[413:]):
            reasons.append("unsupported_pool_fields")
        return {"program": program, "pair": pair, "config": key(8), "creator": key(40),
                "vaults": [key(72), key(104)], "lp_mint": key(136), "mints": [key(168), key(200)],
                "token_programs": [key(232), key(264)], "authority": authority,
                "tracked_lp_supply": struct.unpack_from("<Q", raw, 333)[0],
                "accrued_vault_fees": [sum(struct.unpack_from("<Q", raw, offset)[0] for offset in offsets)
                                       for offsets in ((341, 357, 397), (349, 365, 405))],
                "open_time": struct.unpack_from("<Q", raw, 373)[0],
                "creator_fee_enabled": bool(raw[390]), "reasons": reasons}
    if len(raw) < 243 or raw[:8] != hashlib.sha256(b"account:Pool").digest()[:8]:
        raise DataUnavailable("Unsupported PumpSwap pool layout")
    # Official Pump docs specify absent trailing fields as zero. Truncated fields
    # and unknown nonzero tails never authorize entry.
    for start, end in ((245, 261), (261, 269)):
        if start < len(raw) < end:
            raise DataUnavailable("Truncated PumpSwap pool field")
    padded = raw + bytes(max(0, 271 - len(raw)))
    if any(padded[i] not in (0, 1) for i in (243, 244, 269, 270)):
        raise DataUnavailable("Invalid PumpSwap pool flags")
    if padded[243] or padded[244] or padded[269] or padded[270]:
        reasons.append("unsupported_pumpswap_mode")
    if int.from_bytes(padded[245:261], "little", signed=True) != 0:
        reasons.append("unsupported_virtual_quote_reserves")
    if any(padded[261:269]) or any(raw[271:]):
        reasons.append("unsupported_pool_fields")
    expected = hashlib.sha256(b"pool" + raw[9:11] + raw[11:43] + raw[43:75] + raw[75:107]
                              + raw[8:9] + address_bytes(program) + b"ProgramDerivedAddress").digest()
    if encode58(expected) != pair:
        raise DataUnavailable("PumpSwap pool address does not match seeds")
    return {"program": program, "pair": pair, "config": PUMP_CONFIG, "creator": key(11),
            "protocol_coin_creator": key(211), "vaults": [key(139), key(171)], "lp_mint": key(107),
            "mints": [key(43), key(75)], "authority": pair,
            "tracked_lp_supply": struct.unpack_from("<Q", raw, 203)[0],
            "open_time": 0, "reasons": reasons}


def token_account(account, expected_mint, *, vault=False):
    raw = account_bytes(account)
    program = account.get("owner")
    if program not in TOKEN_PROGRAMS or len(raw) < 165 or raw[:32] != address_bytes(expected_mint):
        raise DataUnavailable("Token account mint/program mismatch")
    if (program == TOKEN_PROGRAM and len(raw) != 165) or (len(raw) > 165 and raw[165] != 2):
        raise DataUnavailable("Invalid token account layout")
    if raw[108] not in (1, 2):
        raise DataUnavailable("Uninitialized token account")
    for offset in (72, 109, 129):
        if struct.unpack_from("<I", raw, offset)[0] not in (0, 1):
            raise DataUnavailable("Invalid token account option")
    if vault:
        if raw[108] != 1 or any(raw[72:76]) or any(raw[129:133]):
            raise DataUnavailable("Frozen or externally controlled pool vault")
        offset, seen = 166, set()
        while offset < len(raw):
            if not any(raw[offset:]):
                break
            if offset + 4 > len(raw):
                raise DataUnavailable("Truncated vault extension")
            kind, size = struct.unpack_from("<HH", raw, offset)
            offset += 4
            if kind != 7 or size != 0 or kind in seen:
                raise DataUnavailable(f"Unsupported vault extension:{kind}")
            seen.add(kind)
    return {"owner": encode58(raw[32:64]), "amount": struct.unpack_from("<Q", raw, 64)[0], "program": program}


def owner_bounds(supply: int, excluded: int, accounts: list[HolderAccount], creators=()):
    if supply <= 0 or not 0 <= excluded < supply:
        raise DataUnavailable("No measurable non-pool supply")
    owners = defaultdict(int)
    for account in accounts:
        amount = int(account.raw_amount)
        if amount < 0:
            raise DataUnavailable("Invalid owner amount")
        owners[account.owner] += amount
    remaining = supply - excluded
    unseen = remaining - sum(owners.values())
    if unseen < 0:
        raise DataUnavailable("Account amounts exceed same-slot supply")
    top10 = sum(sorted(owners.values(), reverse=True)[:10])
    return {"raw_supply": str(supply), "raw_excluded_supply": str(excluded),
            "raw_non_pool_supply": str(remaining), "raw_unobserved_supply": str(unseen),
            "observed_owners": len(owners),
            "top10_owner_fraction_lower": Decimal(top10) / remaining,
            "top10_owner_fraction_upper": Decimal(min(remaining, top10 + unseen)) / remaining,
            "creator_observed_fraction": Decimal(sum(owners.get(c, 0) for c in set(creators))) / remaining}


def assess_bundle(token, pair, addresses, result, expected_pool, sampled_addresses, rpc_host):
    """Every amount, mint supply and pool parameter comes from one bank slot."""
    slot = context_slot(result)
    values = result.get("value")
    if not isinstance(values, list) or len(values) != len(addresses):
        raise DataUnavailable("Incomplete account batch")
    accounts = dict(zip(addresses, values))
    if any(not isinstance(v, dict) for v in values):
        raise DataUnavailable("Missing account in risk batch")
    pool = pool_state(accounts[pair], pair)
    immutable = ("program", "config", "creator", "vaults", "lp_mint", "mints", "authority")
    if pool is None or any(pool[k] != expected_pool[k] for k in immutable) or token not in pool["mints"]:
        raise DataUnavailable("Pool identities changed during verification")
    if len(set(pool["vaults"] + pool["mints"] + [pair, pool["lp_mint"], pool["config"]])) != 7:
        raise DataUnavailable("Aliased pool accounts")
    mint = decode_mint(accounts[token], token)
    if (not mint.get("supported_program") or not mint.get("extension_checks_passed")
            or mint.get("mint_authority") is not False or mint.get("freeze_authority") is not False):
        raise DataUnavailable("Mint risk changed during holder verification")
    vaults = [token_account(accounts[address], mint_address, vault=True)
              for address, mint_address in zip(pool["vaults"], pool["mints"])]
    if any(v["owner"] != pool["authority"] for v in vaults):
        raise DataUnavailable("Vault authority does not match verified pool")
    if "token_programs" in pool and [v["program"] for v in vaults] != pool["token_programs"]:
        raise DataUnavailable("Vault token program mismatch")
    token_index = pool["mints"].index(token)
    if vaults[token_index]["program"] != accounts[token]["owner"]:
        raise DataUnavailable("Mint and vault token programs differ")
    reasons = list(pool["reasons"])
    if pool["mints"][1-token_index] not in QUOTE_MINTS:
        reasons.append("unsupported_quote_mint")
    if not all(v["amount"] > 0 for v in vaults):
        reasons.append("empty_pool_vault")
    accrued = pool.get("accrued_vault_fees", [0, 0])
    reserves = [v["amount"] - fee for v, fee in zip(vaults, accrued)]
    if any(amount < 0 for amount in reserves):
        raise DataUnavailable("Accrued fees exceed vault balance")
    if any(amount == 0 for amount in reserves):
        reasons.append("empty_pool_reserves_after_fees")
    if pool["open_time"] > utcnow().timestamp():
        reasons.append("pool_not_open_yet")
    config = accounts[pool["config"]]
    raw_config = account_bytes(config)
    if config.get("owner") != pool["program"]:
        raise DataUnavailable("Pool configuration owner mismatch")
    if pool["program"] == CPMM_PROGRAM:
        if len(raw_config) != 236 or raw_config[:8] != hashlib.sha256(b"account:AmmConfig").digest()[:8]:
            raise DataUnavailable("Unsupported Raydium config layout")
        fee_rate = struct.unpack_from("<Q", raw_config, 12)[0]
        if pool["creator_fee_enabled"]:
            fee_rate += struct.unpack_from("<Q", raw_config, 108)[0]
        pool["known_fee_bps"] = str(Decimal(fee_rate) / 100)
        if fee_rate >= 1_000_000 or any(raw_config[124:]):
            reasons.append("unsupported_pool_fee_configuration")
    else:
        if len(raw_config) < 321 or raw_config[:8] != hashlib.sha256(b"account:GlobalConfig").digest()[:8]:
            raise DataUnavailable("Unsupported PumpSwap config layout")
        if raw_config[56] & 24:
            reasons.append("pool_swaps_disabled")
        # PumpSwap also has dynamic fee configuration; fixed execution costs do
        # not yet model it. Pool recognition must not silently authorize a swap.
        reasons.append("pumpswap_dynamic_fees_unverified")
    lp = accounts[pool["lp_mint"]]
    lp_raw = account_bytes(lp)
    lp_values = decode_mint(lp, pool["lp_mint"])
    if (not lp_values.get("supported_program") or not lp_values.get("extension_checks_passed")
            or lp_values.get("freeze_authority") is not False or lp_values.get("mint_authority") is not True
            or lp_raw[4:36] != address_bytes(pool["authority"])):
        raise DataUnavailable("Unverified LP mint authorities")
    tracked, minted = pool["tracked_lp_supply"], int(lp_values["raw_supply"])
    if not 0 <= minted <= tracked or tracked == 0:
        raise DataUnavailable("Inconsistent LP supply")
    nonredeemable = Decimal(tracked - minted) / tracked
    # Includes protocol minimum liquidity and externally burnt LP tokens;
    # outstanding LP held by a locker is not assumed permanently locked.
    excluded_address = pool["vaults"][token_index]
    samples = []
    for address in sampled_addresses:
        if address == excluded_address:
            continue
        info = token_account(accounts[address], token)
        if info["program"] != accounts[token]["owner"]:
            raise DataUnavailable("Holder token program mismatch")
        samples.append(HolderAccount(address=address, owner=info["owner"], raw_amount=str(info["amount"])))
    creators = [pool["creator"]]
    if pool.get("protocol_coin_creator") not in (None, "11111111111111111111111111111111"):
        creators.append(pool["protocol_coin_creator"])
    bounds = owner_bounds(int(mint["raw_supply"]), vaults[token_index]["amount"], samples, creators)
    pool.update(raw_lp_mint_supply=str(minted), raw_vault_amounts=[str(v["amount"]) for v in vaults],
                raw_vault_reserves_after_fees=[str(amount) for amount in reserves])
    evidence = {"token": token, "pair": pair, "slot": slot, "rpc_host": rpc_host,
                "accounts": accounts, "sampled_addresses": sampled_addresses}
    evidence_hash = hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return HolderRisk(token=token, pair=pair, status="complete", checked_at=utcnow(), slot=slot,
                      rpc_host=rpc_host, pool_program=pool["program"], sampled_accounts=samples,
                      excluded_vault_accounts=[excluded_address], lp_nonredeemable_fraction=nonredeemable,
                      pool_details=pool, reasons=list(dict.fromkeys(reasons)), evidence_sha256=evidence_hash,
                      evidence_payload=evidence, **bounds), mint


async def verify_holders(rpc, token, pair, sampled_addresses, sample_slot):
    for address in [token, pair, *sampled_addresses]:
        address_bytes(address)
    if len(set(sampled_addresses)) != len(sampled_addresses):
        raise DataUnavailable("Duplicate sampled account")
    result = await rpc.rpc("getAccountInfo", [pair, {"encoding": "base64", "commitment": "confirmed",
                                                    "minContextSlot": sample_slot}])
    pool_slot = context_slot(result)
    account = result.get("value")
    if not isinstance(account, dict):
        raise DataUnavailable("Pool account missing")
    pool = pool_state(account, pair)
    if pool is None:
        return HolderRisk(token=token, pair=pair, status="unsupported_pool", checked_at=utcnow(), slot=pool_slot,
                          rpc_host=rpc._last_host, pool_program=account.get("owner", "unknown"),
                          reasons=["unsupported_pool_program"]), None
    if token not in pool["mints"]:
        raise DataUnavailable("Pool does not contain requested mint")
    keys = list(dict.fromkeys([token, pair, *sampled_addresses, *pool["vaults"], pool["lp_mint"], pool["config"]]))
    result = await rpc.rpc("getMultipleAccounts", [keys, {"encoding": "base64", "commitment": "confirmed",
                                                         "minContextSlot": max(pool_slot, sample_slot)}])
    if not max(pool_slot, sample_slot) <= context_slot(result) <= sample_slot + 150:
        raise DataUnavailable("Inconsistent holder verification slot")
    return assess_bundle(token, pair, keys, result, pool, sampled_addresses, rpc._last_host)
