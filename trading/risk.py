from datetime import datetime
from decimal import Decimal

from config.settings import Settings
from collectors.holders import PUMP_PROGRAM, USDC_MINT, WSOL_MINT
from collectors.mint import TOKEN_2022_PROGRAM
from data.models import HolderRisk, Snapshot


LARGEST_ACCOUNTS_LIMIT = 20


def unobserved_account_bound(holders: HolderRisk) -> Decimal | None:
    """Upper bound for any single account outside the sample, as a non-pool supply fraction.

    The sample holds the largest token accounts, so no unseen account exceeds the
    smallest sampled one. A sample below the RPC limit (vault included) saw every
    account. Owners spreading tokens over many small accounts remain undetected.
    """
    try:
        supply = int(holders.raw_non_pool_supply or 0)
        unobserved = int(holders.raw_unobserved_supply or 0)
        amounts = [int(a.raw_amount) for a in holders.sampled_accounts]
    except ValueError:
        return None
    if supply <= 0:
        return None
    if unobserved == 0 or len(amounts) < LARGEST_ACCOUNTS_LIMIT - 1:
        return Decimal(0)
    return Decimal(min(min(amounts), unobserved)) / supply


QUOTE_DECIMALS = {WSOL_MINT: 9, USDC_MINT: 6}


def onchain_liquidity_usd(snapshot: Snapshot, holders: HolderRisk) -> Decimal | None:
    """Two-sided USD value of the verified quote reserve after waiting fees.

    DEX Screener overstated real PumpSwap liquidity in R2 (median 1.5x), so the
    entry floor uses the same-slot vault balance. Quote price: priceUsd/priceNative.
    """
    details = holders.pool_details
    try:
        mints, reserves = details["mints"], details["raw_vault_reserves_after_fees"]
        quote_index = 1 - mints.index(snapshot.token)
        quote_mint = mints[quote_index]
        raw = snapshot.raw
        if (raw.get("quoteToken") or {}).get("address") != quote_mint or quote_mint not in QUOTE_DECIMALS:
            return None
        quote_usd = Decimal(str(raw["priceUsd"])) / Decimal(str(raw["priceNative"]))
        value = 2 * Decimal(int(reserves[quote_index])) / 10 ** QUOTE_DECIMALS[quote_mint] * quote_usd
    except (KeyError, ValueError, TypeError, IndexError, ArithmeticError):
        return None
    return value if value.is_finite() and value >= 0 else None


def risk_reasons(snapshot: Snapshot, now: datetime, settings: Settings, *, entry: bool = True) -> list[str]:
    reasons = []
    age = (now - snapshot.received_at).total_seconds()
    if age < 0 or age > settings.max_quote_age_seconds:
        reasons.append("stale_or_future_quote")
    if snapshot.price_usd is None:
        reasons.append("missing_price")
    if snapshot.liquidity_usd is None or snapshot.liquidity_usd < settings.min_liquidity_usd:
        reasons.append("insufficient_or_unknown_liquidity")
    risk = snapshot.mint_risk
    if risk is None:
        reasons.append("missing_onchain_checks")
    else:
        check_times = [risk.checked_at, *[t for t in (risk.mint_checked_at, risk.concentration_checked_at) if t is not None]]
        if risk.holder_risk is not None:
            check_times.append(risk.holder_risk.checked_at)
        if any(not 0 <= (now - t).total_seconds() <= settings.max_quote_age_seconds for t in check_times):
            reasons.append("stale_or_future_onchain_checks")
        if not risk.supported_program:
            reasons.append("unsupported_token_program")
        if risk.extension_reasons:
            reasons.extend(risk.extension_reasons)
        if risk.program_id == TOKEN_2022_PROGRAM and risk.extension_checks_passed is not True:
            reasons.append("token2022_extensions_unverified_or_unsafe")
        if risk.data_errors:
            reasons.append("incomplete_onchain_checks")
        if risk.mint_authority is not False:
            reasons.append("mint_authority_active_or_unknown")
        if risk.freeze_authority is not False:
            reasons.append("freeze_authority_active_or_unknown")
        use_holders = risk.risk_version == 3 or (settings.require_verified_holder_risk and snapshot.source == "dexscreener")
        if use_holders:
            holders = risk.holder_risk
            if holders is None:
                reasons.append("missing_verified_holder_risk")
            elif holders.token != snapshot.token or holders.pair != snapshot.pair:
                reasons.append("holder_risk_token_or_pool_mismatch")
            else:
                reasons.extend(holders.reasons)
                if holders.status != "complete":
                    reasons.append("unverified_pool_and_holders")
                elif holders.top10_owner_fraction_lower is None:
                    reasons.append("unknown_owner_concentration")
                elif holders.top10_owner_fraction_lower > settings.max_top10_owner_fraction:
                    reasons.append("high_top10_owner_concentration")
                elif (holders.top10_owner_fraction_upper is None
                      or holders.top10_owner_fraction_upper > settings.max_top10_owner_fraction):
                    # The conservative upper bound failed: accept the observed share only
                    # when every unseen account is provably small.
                    unobserved = unobserved_account_bound(holders)
                    if unobserved is None:
                        reasons.append("unknown_unobserved_account_size")
                    elif unobserved > settings.max_unobserved_account_fraction:
                        reasons.append("coarse_holder_sample")
                if holders.status == "complete":
                    liquidity = onchain_liquidity_usd(snapshot, holders)
                    if liquidity is None:
                        reasons.append("unknown_onchain_liquidity")
                    elif liquidity < settings.min_liquidity_usd:
                        reasons.append("insufficient_onchain_liquidity")
                    if holders.lp_nonredeemable_fraction is None or holders.lp_nonredeemable_fraction < settings.min_lp_nonredeemable_fraction:
                        reasons.append("insufficient_verified_lp_nonredeemable_fraction")
                    if holders.creator_observed_fraction is None:
                        reasons.append("unknown_creator_observed_balance")
                    elif holders.creator_observed_fraction > settings.max_creator_observed_fraction:
                        reasons.append("high_creator_observed_balance")
                    from decimal import Decimal, InvalidOperation
                    fee = holders.pool_details.get("known_fee_bps")
                    if fee is not None:
                        try:
                            measured_fee = Decimal(fee)
                            if not measured_fee.is_finite() or measured_fee < 0 or measured_fee > settings.fee_bps:
                                reasons.append("pool_fees_exceed_execution_assumption")
                        except (InvalidOperation, ValueError, TypeError):
                            reasons.append("unknown_pool_fees")
        elif risk.top10_account_fraction is None:
            reasons.append("unknown_account_concentration")
        elif risk.top10_account_fraction > settings.max_top10_account_fraction:
            reasons.append("high_top10_account_concentration")
    if entry:
        if snapshot.observation_phase == "followup":
            reasons.append("followup_only_no_new_entry")
        if snapshot.pair_created_at is None:
            reasons.append("unknown_pair_age")
        elif not settings.min_age_seconds <= (now - snapshot.pair_created_at).total_seconds() <= settings.max_age_seconds:
            reasons.append("pair_age_outside_entry_window")
        elif (risk is not None and risk.holder_risk is not None and risk.holder_risk.pool_program == PUMP_PROGRAM
              and (now - snapshot.pair_created_at).total_seconds() < settings.min_pumpswap_age_seconds):
            # Post-migration boost buybacks create buy pressure that is not market demand.
            reasons.append("pumpswap_boost_window")
        if snapshot.volume_5m_usd is None or snapshot.volume_5m_usd < settings.min_volume_5m_usd:
            reasons.append("insufficient_or_unknown_volume")
        if snapshot.buys_5m is None or snapshot.sells_5m is None:
            reasons.append("missing_trade_counts")
    return reasons
