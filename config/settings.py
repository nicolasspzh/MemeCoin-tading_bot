"""Small, validated configuration surface. No live execution mode exists."""
import os
import re
import shlex
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ADDRESS = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}\Z")


class Settings(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    mode: Literal["PAPER"] = "PAPER"
    db_path: Path = Path("runtime/paper.sqlite3")
    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"
    solana_rpc_fallback_urls: list[str] = Field(default_factory=lambda: ["https://solana-rpc.publicnode.com"])
    rpc_cache_seconds: float = Field(default=60, ge=0, le=60)
    dex_base_url: str = "https://api.dexscreener.com"
    poll_seconds: float = Field(default=20, ge=10)
    max_watch_tokens: int = Field(default=30, ge=1, le=100)
    watch_tokens: list[str] = Field(default_factory=list)
    observation_cohorts: bool = False
    observation_primary_seconds: int = Field(default=1800, ge=300, le=7200)
    observation_admission_seconds: int = Field(default=0, ge=0, le=3600)
    # Admit only coins whose DEX quote shows a supported pool, quote asset and liquidity.
    admission_prefilter: bool = False
    rpc_daily_request_limit: int = Field(default=70000, ge=1)
    rpc_total_request_limit: int = Field(default=600000, ge=1)
    pool_discovery_enabled: bool = True
    discovery_poll_seconds: float = Field(default=20, ge=10, le=300)
    discovery_page_size: int = Field(default=20, ge=1, le=100)
    discovery_pages_per_poll: int = Field(default=2, ge=1, le=5)
    discovery_transactions_per_poll: int = Field(default=10, ge=1, le=50)
    min_liquidity_usd: Decimal = Field(default=Decimal("10000"), gt=0)
    min_volume_5m_usd: Decimal = Field(default=Decimal("1000"), ge=0)
    max_top10_account_fraction: Decimal = Field(default=Decimal("0.60"), gt=0, le=1)
    require_verified_holder_risk: bool = True
    max_top10_owner_fraction: Decimal = Field(default=Decimal("0.60"), gt=0, le=1)
    max_unobserved_account_fraction: Decimal = Field(default=Decimal("0.01"), gt=0, le=1)
    max_creator_observed_fraction: Decimal = Field(default=Decimal("0.10"), gt=0, le=1)
    min_lp_nonredeemable_fraction: Decimal = Field(default=Decimal("0.90"), ge=0, le=1)
    fee_bps: Decimal = Field(default=Decimal("30"), ge=0, le=1000)
    # Verified pools charge their measured fee; fee_bps applies to unverified data only.
    max_pool_fee_bps: Decimal = Field(default=Decimal("200"), ge=0, le=1000)
    slippage_bps: Decimal = Field(default=Decimal("100"), ge=0, lt=10000)
    fixed_fee_usd: Decimal = Field(default=Decimal("0.02"), ge=0)
    paper_latency_seconds: float = Field(default=1, ge=0, le=300)
    paper_order_ttl_seconds: float = Field(default=120, gt=0, le=3600)
    paper_priority_fee_usd: Decimal = Field(default=Decimal("0.005"), ge=0)
    paper_failure_probability: float = Field(default=0.02, ge=0, le=1)
    paper_max_adverse_move_bps: Decimal = Field(default=Decimal("300"), ge=0, le=10000)
    paper_seed: int = 7
    position_fraction: Decimal = Field(default=Decimal("0.05"), gt=0, le=Decimal("0.10"))
    max_positions: int = Field(default=3, ge=1, le=10)
    max_quote_age_seconds: int = Field(default=120, ge=1)
    min_age_seconds: int = Field(default=60, ge=0)
    min_pumpswap_age_seconds: int = Field(default=600, ge=0)
    max_age_seconds: int = Field(default=86400, ge=60)
    max_position_seconds: int = Field(default=900, ge=30)
    stop_loss_fraction: Decimal = Field(default=Decimal("0.12"), gt=0, lt=1)
    take_profit_fraction: Decimal = Field(default=Decimal("0.25"), gt=0)
    trailing_stop_fraction: Decimal = Field(default=Decimal("0.10"), gt=0, lt=1)
    min_momentum_fraction: Decimal = Field(default=Decimal("0.01"), gt=0)
    max_pool_fraction: Decimal = Field(default=Decimal("0.001"), gt=0, le=Decimal("0.01"))

    @field_validator("solana_rpc_url", "dex_base_url")
    @classmethod
    def https_only(cls, value: str) -> str:
        from urllib.parse import urlsplit
        url = urlsplit(value)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("A public HTTPS endpoint without user info is required")
        return value.rstrip("/")

    @field_validator("watch_tokens")
    @classmethod
    def valid_addresses(cls, values: list[str]) -> list[str]:
        if any(not ADDRESS.fullmatch(v) for v in values):
            raise ValueError("WATCH_TOKENS must contain Solana mint addresses")
        return list(dict.fromkeys(values))

    @field_validator("solana_rpc_fallback_urls")
    @classmethod
    def valid_fallbacks(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(cls.https_only(value) for value in values))


def load_settings(path: Path = Path(".env")) -> Settings:
    """Support single-line KEY=value with quotes/comments; no shell expansion."""
    values = {}
    if path.exists():
        for number, line in enumerate(path.read_text().splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, value = line.partition("=")
            if not sep:
                raise ValueError(f"Invalid .env assignment on line {number}")
            parts = shlex.split(value, comments=True)
            if len(parts) > 1:
                raise ValueError(f"Quote values containing spaces on line {number}")
            values[key.strip()] = parts[0] if parts else ""
    config = {}
    for name in Settings.model_fields:
        key = name.upper()
        value = os.environ.get(key, values.get(key))
        if value is not None:
            config[name] = ([v.strip() for v in value.split(",") if v.strip()]
                            if name in ("watch_tokens", "solana_rpc_fallback_urls") else value)
    return Settings.model_validate(config)
