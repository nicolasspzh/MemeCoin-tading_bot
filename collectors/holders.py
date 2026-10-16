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
# Source: pump-fun/pump-public-docs (commit 639b87f) and pump-swap-sdk 2.1.0, see
# docs/R3-STUFE-A-PUMPSWAP.md. The fee config is PDA ["fee_config", PUMP_PROGRAM].
PUMP_FUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMP_FEE_PROGRAM = "pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ"
PUMP_FEE_CONFIG = "5PHirr8joyTMp9JMm6nW7hNDVyEYdkzDqazxPD7RaTjx"
PUMP_POOL_SIZE = 287
WSOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
TOKEN_PROGRAMS = {TOKEN_PROGRAM, TOKEN_2022_PROGRAM}

_P = 2**255 - 19
_D = -121665 * pow(121666, _P - 2, _P) % _P


def on_curve(raw: bytes) -> bool:
    """Whether 32 bytes decompress to an ed25519 point; PDAs must not."""
    y = int.from_bytes(raw, "little") & ((1 << 255) - 1)
    if y >= _P:
        return False
    y2 = y * y % _P
    u, v = (y2 - 1) % _P, (_D * y2 + 1) % _P
    x = pow(u * pow(v, _P - 2, _P) % _P, (_P + 3) // 8, _P)
    return (v * x * x - u) % _P == 0 or (v * x * x + u) % _P == 0


def program_address(seeds: list[bytes], program: str) -> tuple[str, int]:
    """Solana find_program_address: highest bump whose hash is off the curve."""
    for bump in range(255, -1, -1):
        digest = hashlib.sha256(b"".join(seeds) + bytes([bump]) + address_bytes(program)
                                + b"ProgramDerivedAddress").digest()
        if not on_curve(digest):
            return encode58(digest), bump
    raise DataUnavailable("No program address")


def fee_config(account) -> dict:
    """Decode pump-fees FeeConfig: flat fees, SOL tiers, stable tiers, exotic flat fees."""
    if not isinstance(account, dict) or account.get("owner") != PUMP_FEE_PROGRAM:
        raise DataUnavailable("PumpSwap fee configuration owner mismatch")
    raw = account_bytes(account)
    if raw[:8] != bytes([143, 52, 146, 187, 219, 123, 76, 155]):
        raise DataUnavailable("Unsupported PumpSwap fee configuration layout")
    offset = 8 + 1 + 32
    try:
        def fees():
            nonlocal offset
            values = struct.unpack_from("<QQQ", raw, offset)
            offset += 24
            if sum(values) > 10000:
                raise ValueError
            return values

        def tiers():
            nonlocal offset
            count = struct.unpack_from("<I", raw, offset)[0]
            offset += 4
            if count > 64:
                raise ValueError
            result = []
            for _ in range(count):
                low, high = struct.unpack_from("<QQ", raw, offset)
                offset += 16
                result.append(((high << 64) | low, fees()))
            if any(a[0] >= b[0] for a, b in zip(result, result[1:])):
                raise ValueError
            return result

        flat, sol = fees(), tiers()
        # Fields appended later decode as empty/zero on older accounts.
        stable = tiers() if len(raw) - offset >= 4 else []
        exotic = fees() if len(raw) - offset >= 24 else (0, 0, 0)
    except (struct.error, ValueError):
        raise DataUnavailable("Malformed PumpSwap fee configuration") from None
    if not sol:
        raise DataUnavailable("PumpSwap fee tiers missing")
    return {"flat": flat, "tiers": sol, "stable": stable, "exotic": exotic}


def pump_fee(config: dict, *, canonical: bool, quote_mint: str, market_cap: int) -> tuple[tuple, str]:
    """pump-fees FeeConfig::fees_for_quote_mint() and calculate_fee_tier()."""
    if not canonical:
        return config["flat"], "flat"
    if quote_mint == WSOL_MINT:
        tiers, schedule = config["tiers"], "tiers"
    elif quote_mint == USDC_MINT:
        tiers, schedule = config["stable"] or config["tiers"], "stable_tiers"
    else:
        return (config["flat"], "flat") if not any(config["exotic"]) else (config["exotic"], "exotic_flat")
    if market_cap < tiers[0][0]:
        return tiers[0][1], schedule
    return next(fees for threshold, fees in reversed(tiers) if market_cap >= threshold), schedule


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
    for start, end in ((245, 261), (261, 269), (271, 279), (279, 287)):
        if start < len(raw) < end:
            raise DataUnavailable("Truncated PumpSwap pool field")
    padded = raw + bytes(max(0, PUMP_POOL_SIZE - len(raw)))
    if any(padded[i] not in (0, 1) for i in (243, 244, 269, 270)):
        raise DataUnavailable("Invalid PumpSwap pool flags")
    # Mayhem fees are undocumented, cashback is deprecated, the editable creator fee
    # flag is reserved. Holder rewards only redirect the creator fee: trading unchanged.
    if padded[243] or padded[244] or padded[269]:
        reasons.append("unsupported_pumpswap_mode")
    creator_fee_bps = struct.unpack_from("<Q", padded, 261)[0]
    if creator_fee_bps:
        reasons.append("custom_pool_creator_fee")  # documented for non SOL/USDC pairs only
    if any(raw[PUMP_POOL_SIZE:]):
        reasons.append("unsupported_pool_fields")
    expected = hashlib.sha256(b"pool" + raw[9:11] + raw[11:43] + raw[43:75] + raw[75:107]
                              + raw[8:9] + address_bytes(program) + b"ProgramDerivedAddress").digest()
    if encode58(expected) != pair:
        raise DataUnavailable("PumpSwap pool address does not match seeds")
    # Signed i128: waiting fees are subtracted, boost reserves added. Price uses
    # vault + virtual reserves; only vault - waiting fees is liquidity.
    virtual = int.from_bytes(padded[245:261], "little", signed=True)
    protocol_fees, creator_fees = struct.unpack_from("<QQ", padded, 271)
    canonical = program_address([b"pool-authority", raw[43:75]], PUMP_FUN_PROGRAM)[0] == key(11)
    return {"program": program, "pair": pair, "config": PUMP_CONFIG, "creator": key(11),
            "protocol_coin_creator": key(211), "vaults": [key(139), key(171)], "lp_mint": key(107),
            "mints": [key(43), key(75)], "authority": pair,
            "tracked_lp_supply": struct.unpack_from("<Q", raw, 203)[0],
            "accrued_vault_fees": [0, protocol_fees + creator_fees],
            "virtual_quote_reserves": str(virtual), "boost_reserves": str(virtual + protocol_fees + creator_fees),
            "canonical": canonical, "holder_reward": bool(padded[270]), "creator_fee_bps": creator_fee_bps,
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
        # Fees come from pump-fees FeeConfig by market cap on effective quote reserves.
        # Without a decodable fee account, recognition must not authorize a swap.
        try:
            if token_index != 0:
                raise DataUnavailable("Token is not the PumpSwap base mint")
            config_fees = fee_config(accounts.get(PUMP_FEE_CONFIG))
            effective_quote = vaults[1]["amount"] + int(pool["virtual_quote_reserves"])
            if vaults[0]["amount"] <= 0 or effective_quote < 0:
                raise DataUnavailable("Empty PumpSwap reserves")
            market_cap = effective_quote * int(mint["raw_supply"]) // vaults[0]["amount"]
            fees, schedule = pump_fee(config_fees, canonical=pool["canonical"],
                                      quote_mint=pool["mints"][1], market_cap=market_cap)
            pool.update(known_fee_bps=str(sum(fees)), fee_schedule=schedule,
                        fee_bps_parts={"lp": fees[0], "protocol": fees[1], "creator": fees[2]},
                        market_cap_quote_raw=str(market_cap))
        except DataUnavailable:
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
    if pool["mints"][1 - pool["mints"].index(token)] not in QUOTE_MINTS:
        # Clear block before reading vaults: a foreign quote asset (for example a
        # tokenized stock with transfer hooks) is never tradable here. Saves the batch.
        return HolderRisk(token=token, pair=pair, status="unsupported_pool", checked_at=utcnow(), slot=pool_slot,
                          rpc_host=rpc._last_host, pool_program=pool["program"],
                          reasons=["unsupported_quote_mint"]), None
    extra =[PUMP_FEE_CONFIG] if pool["program"] == PUMP_PROGRAM else []
    keys = list(dict.fromkeys([token, pair, *sampled_addresses, *pool["vaults"], pool["lp_mint"], pool["config"], *extra]))
    result = await rpc.rpc("getMultipleAccounts", [keys, {"encoding": "base64", "commitment": "confirmed",
                                                         "minContextSlot": max(pool_slot, sample_slot)}])
    if not max(pool_slot, sample_slot) <= context_slot(result) <= sample_slot + 150:
        raise DataUnavailable("Inconsistent holder verification slot")
    return assess_bundle(token, pair, keys, result, pool, sampled_addresses, rpc._last_host)
