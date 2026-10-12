from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class Model(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")


class HolderAccount(Model):
    address: str
    owner: str
    raw_amount: str


class HolderRisk(Model):
    version: Literal[1] = 1
    token: str
    pair: str
    status: Literal["complete", "unsupported_pool"]
    checked_at: AwareDatetime
    slot: int = Field(ge=0)
    rpc_host: str | None = None
    pool_program: str
    sampled_accounts: list[HolderAccount] = Field(default_factory=list)
    excluded_vault_accounts: list[str] = Field(default_factory=list)
    raw_supply: str | None = None
    raw_excluded_supply: str | None = None
    raw_non_pool_supply: str | None = None
    raw_unobserved_supply: str | None = None
    observed_owners: int = Field(default=0, ge=0)
    top10_owner_fraction_lower: Decimal | None = Field(default=None, ge=0, le=1)
    top10_owner_fraction_upper: Decimal | None = Field(default=None, ge=0, le=1)
    creator_observed_fraction: Decimal | None = Field(default=None, ge=0, le=1)
    lp_nonredeemable_fraction: Decimal | None = Field(default=None, ge=0, le=1)
    pool_details: dict = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    evidence_sha256: str | None = Field(default=None, exclude_if=lambda v: v is None)
    # Transient transport to Engine; persist once by hash, not per snapshot.
    evidence_payload: dict | None = Field(default=None, exclude=True)


class MintRisk(Model):
    checked_at: AwareDatetime
    supported_program: bool
    mint_authority: bool | None = None
    freeze_authority: bool | None = None
    top10_account_fraction: Decimal | None = Field(default=None, ge=0, le=1)
    # Omit absent new fields to preserve historical snapshot serialization/hashes.
    program_id: str | None = Field(default=None, exclude_if=lambda v: v is None)
    raw_supply: str | None = Field(default=None, exclude_if=lambda v: v is None)
    extension_names: list[str] | None = Field(default=None, exclude_if=lambda v: v is None)
    extension_checks_passed: bool | None = Field(default=None, exclude_if=lambda v: v is None)
    extension_reasons: list[str] = Field(default_factory=list, exclude_if=lambda v: not v)
    metadata_mutable: bool | None = Field(default=None, exclude_if=lambda v: v is None)
    mint_slot: int | None = Field(default=None, ge=0, exclude_if=lambda v: v is None)
    concentration_slot: int | None = Field(default=None, ge=0, exclude_if=lambda v: v is None)
    mint_checked_at: AwareDatetime | None = Field(default=None, exclude_if=lambda v: v is None)
    concentration_checked_at: AwareDatetime | None = Field(default=None, exclude_if=lambda v: v is None)
    mint_rpc_host: str | None = Field(default=None, exclude_if=lambda v: v is None)
    concentration_rpc_host: str | None = Field(default=None, exclude_if=lambda v: v is None)
    data_errors: list[str] = Field(default_factory=list, exclude_if=lambda v: not v)
    risk_version: int | None = Field(default=None, exclude_if=lambda v: v is None)
    holder_risk: HolderRisk | None = Field(default=None, exclude_if=lambda v: v is None)


class Snapshot(Model):
    token: str
    pair: str
    symbol: str = "?"
    source: Literal["dexscreener", "demo"]
    received_at: AwareDatetime
    observation_phase: Literal["primary", "followup"] | None = Field(default=None, exclude_if=lambda v: v is None)
    pair_created_at: AwareDatetime | None = None
    price_usd: Decimal | None = Field(default=None, gt=0)
    liquidity_usd: Decimal | None = Field(default=None, ge=0)
    market_cap_usd: Decimal | None = Field(default=None, ge=0)
    volume_5m_usd: Decimal | None = Field(default=None, ge=0)
    buys_5m: int | None = Field(default=None, ge=0)
    sells_5m: int | None = Field(default=None, ge=0)
    change_5m_pct: Decimal | None = None
    mint_risk: MintRisk | None = None
    raw: dict = Field(default_factory=dict)


class Position(Model):
    token: str
    pair: str
    quantity: Decimal = Field(gt=0)
    entry_cost: Decimal = Field(gt=0)
    entry_price: Decimal = Field(gt=0)
    opened_at: AwareDatetime
    entry_snapshot_id: int
    peak_price: Decimal = Field(gt=0)
    last_price: Decimal = Field(gt=0)
    failed_exit_fees: Decimal = Field(default=Decimal(0), ge=0, exclude_if=lambda v: v == 0)


class Wallet(Model):
    cash: Decimal = Field(default=Decimal("50"), ge=0)
    news_reserve: Decimal = Field(default=Decimal("0"), ge=0)
    owner_profit: Decimal = Field(default=Decimal("0"), ge=0)
    realized_pnl: Decimal = Decimal("0")
    positions: dict[str, Position] = Field(default_factory=dict)
    dead: bool = False


class Decision(Model):
    action: Literal["BUY", "HOLD", "SELL", "SKIP"]
    reasons: list[str]


class Fill(Model):
    side: Literal["BUY", "SELL"]
    token: str
    pair: str
    snapshot_id: int
    quantity: Decimal
    price: Decimal
    fee: Decimal
    cash_flow: Decimal
    realized_pnl: Decimal = Decimal("0")
    signal_at: AwareDatetime
    simulated_at: AwareDatetime
    entry_snapshot_id: int
    order_id: int | None = Field(default=None, exclude_if=lambda v: v is None)
    signal_snapshot_id: int | None = Field(default=None, exclude_if=lambda v: v is None)
    net_trade_pnl: Decimal | None = Field(default=None, exclude_if=lambda v: v is None)
    impact_bps: Decimal | None = Field(default=None, exclude_if=lambda v: v is None)
    priority_fee_usd: Decimal | None = Field(default=None, exclude_if=lambda v: v is None)
