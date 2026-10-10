from datetime import datetime

from config.settings import Settings
from collectors.mint import TOKEN_2022_PROGRAM
from data.models import Snapshot


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
                elif holders.top10_owner_fraction_upper is None or holders.top10_owner_fraction_lower is None:
                    reasons.append("unknown_owner_concentration")
                elif holders.top10_owner_fraction_upper > settings.max_top10_owner_fraction:
                    reasons.append("high_top10_owner_concentration" if holders.top10_owner_fraction_lower > settings.max_top10_owner_fraction
                                   else "uncertain_top10_owner_concentration")
                if holders.status == "complete":
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
        if snapshot.volume_5m_usd is None or snapshot.volume_5m_usd < settings.min_volume_5m_usd:
            reasons.append("insufficient_or_unknown_volume")
        if snapshot.buys_5m is None or snapshot.sells_5m is None:
            reasons.append("missing_trade_counts")
    return reasons
