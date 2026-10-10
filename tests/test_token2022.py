import base64
import struct
from datetime import timedelta
from decimal import Decimal

import pytest

from collectors.http import DataUnavailable
from collectors.mint import TOKEN_PROGRAM, TOKEN_2022_PROGRAM, address_bytes, decode_mint
from collectors.solana import Solana
from config.settings import Settings
from data.models import MintRisk, utcnow
from trading.risk import risk_reasons

TOKEN = "So11111111111111111111111111111111111111112"


def mint_account(extensions=(), *, owner=TOKEN_2022_PROGRAM, mint_auth=False, freeze_auth=False):
    mint = bytearray(82)
    struct.pack_into("<I", mint, 0, int(mint_auth))
    struct.pack_into("<Q", mint, 36, 1000)
    mint[44], mint[45] = 6, 1
    struct.pack_into("<I", mint, 46, int(freeze_auth))
    if extensions:
        mint.extend(bytes(83) + b"\1")
        for kind, value in extensions:
            mint.extend(struct.pack("<HH", kind, len(value)) + value)
    return {"owner": owner, "data": [base64.b64encode(mint).decode(), "base64"]}


def metadata(mutable=False):
    fields = ["Example", "EX", "https://example.invalid/never-fetched"]
    return (bytes([int(mutable)]) + bytes(31) + address_bytes(TOKEN)
            + b"".join(struct.pack("<I", len(v)) + v.encode() for v in fields) + struct.pack("<I", 0))


def test_metadata_only_token2022_passes_extension_gate(quote):
    account = mint_account([(18, bytes(32) + address_bytes(TOKEN)), (19, metadata())])
    values = decode_mint(account, TOKEN)
    assert values["extension_names"] == ["metadataPointer", "tokenMetadata"]
    assert values["extension_checks_passed"] is True
    assert values["raw_supply"] == "1000" and values["metadata_mutable"] is False
    snapshot = quote()
    snapshot.mint_risk = MintRisk(checked_at=snapshot.received_at, top10_account_fraction=Decimal(".25"), **values)
    assert risk_reasons(snapshot, snapshot.received_at, Settings()) == []


def test_mutable_metadata_is_disclosed_and_not_fetched():
    values = decode_mint(mint_account([(19, metadata(mutable=True))]), TOKEN)
    assert values["metadata_mutable"] is True
    assert values["extension_checks_passed"] is True


@pytest.mark.parametrize("kind,name", [(1, "transferFeeConfig"), (12, "permanentDelegate"),
    (14, "transferHook"), (6, "defaultAccountState"), (9, "nonTransferable"),
    (26, "pausable"), (60000, "unknown_60000")])
def test_unsafe_and_unknown_extensions_fail_closed(quote, kind, name):
    values = decode_mint(mint_account([(kind, bytes(64))]), TOKEN)
    assert values["extension_checks_passed"] is False
    snapshot = quote()
    snapshot.mint_risk = MintRisk(checked_at=snapshot.received_at, top10_account_fraction=Decimal(".2"), **values)
    reasons = risk_reasons(snapshot, snapshot.received_at, Settings())
    assert f"unsupported_extension:{name}" in reasons
    assert "token2022_extensions_unverified_or_unsafe" in reasons


@pytest.mark.parametrize("extension", [(18, b"short"), (19, b"short")])
def test_malformed_allowed_extensions_rejected(extension):
    with pytest.raises(DataUnavailable, match="Malformed"):
        decode_mint(mint_account([extension]), TOKEN)


@pytest.mark.parametrize("fault", ["duplicate", "truncated", "wrong_account_type", "nonzero_padding", "invalid_option"])
def test_invalid_binary_layouts_rejected(fault):
    extensions = [(18, bytes(64))] * (2 if fault == "duplicate" else 1)
    account = mint_account(extensions)
    raw = bytearray(base64.b64decode(account["data"][0]))
    if fault == "truncated":
        raw = raw[:-1]
    elif fault == "wrong_account_type":
        raw[165] = 2
    elif fault == "nonzero_padding":
        raw[100] = 1
    elif fault == "invalid_option":
        raw[0] = 2
    account["data"][0] = base64.b64encode(raw).decode()
    with pytest.raises(DataUnavailable):
        decode_mint(account, TOKEN)


@pytest.mark.parametrize("owner", [TOKEN_PROGRAM, TOKEN_2022_PROGRAM])
def test_plain_mints_and_authorities(owner):
    value = decode_mint(mint_account(owner=owner, mint_auth=True, freeze_auth=True), TOKEN)
    assert value["mint_authority"] is True and value["freeze_authority"] is True
    assert value["extension_names"] == [] and value["extension_checks_passed"] is True


class FakeHttp:
    def __init__(self, *, fail_primary=False, fail_largest=False, account=None, holder_slot=100):
        self.calls = []
        self.fail_primary, self.fail_largest = fail_primary, fail_largest
        self.account = account or mint_account([(18, bytes(64))])
        self.holder_slot = holder_slot

    async def request(self, method, url, **kwargs):
        rpc_method = kwargs["json"]["method"]
        self.calls.append((url, rpc_method))
        if self.fail_primary and "primary" in url:
            raise DataUnavailable("HTTP 429", status=429, retry_after=90)
        if rpc_method == "getTokenLargestAccounts":
            if self.fail_largest:
                raise DataUnavailable("HTTP 403", status=403)
            value = [{"address": "A", "amount": "100"}, {"address": "B", "amount": "50"}]
            return {"result": {"context": {"slot": self.holder_slot}, "value": value}}
        return {"result": {"context": {"slot": 100}, "value": self.account}}


async def test_rate_limited_rpc_falls_back_and_cools_down(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("collectors.solana.time.monotonic", lambda: clock[0])
    http = FakeHttp(fail_primary=True)
    rpc = Solana(http, "https://primary.example/?key=hidden", ["https://backup.example/?key=hidden"], cache_seconds=0)
    first = await rpc.mint_risk(TOKEN)
    assert first.top10_account_fraction == Decimal(".15")
    assert first.mint_rpc_host == first.concentration_rpc_host == "backup.example"
    assert "hidden" not in first.model_dump_json()
    primary_count = sum("primary" in url for url, _ in http.calls)
    await rpc.mint_risk(TOKEN)
    assert sum("primary" in url for url, _ in http.calls) == primary_count
    assert rpc._cooldown[(0, "getAccountInfo")] == 1090


async def test_partial_risk_preserves_core_and_never_fabricates_concentration(quote):
    http = FakeHttp(fail_largest=True)
    rpc = Solana(http, "https://primary.example")
    risk = await rpc.mint_risk(TOKEN)
    assert risk.supported_program and risk.extension_checks_passed
    assert risk.mint_authority is False and risk.freeze_authority is False
    assert risk.top10_account_fraction is None and risk.data_errors
    snapshot = quote(received_at=risk.checked_at)
    snapshot.mint_risk = risk
    assert "incomplete_onchain_checks" in risk_reasons(snapshot, risk.checked_at, Settings())
    count = len(http.calls)
    await rpc.mint_risk(TOKEN)
    assert len(http.calls) == count + 1  # mint still fetched, holder endpoint cooling down


async def test_cache_retains_observation_time_and_does_not_mask_expired_failure(monkeypatch):
    now = utcnow()
    clock = [now]
    monkeypatch.setattr("collectors.solana.utcnow", lambda: clock[0])
    http = FakeHttp()
    rpc = Solana(http, "https://primary.example", cache_seconds=30)
    first = await rpc.mint_risk(TOKEN)
    clock[0] += timedelta(seconds=20)
    cached = await rpc.mint_risk(TOKEN)
    assert cached.checked_at == first.checked_at and len(http.calls) == 2
    cached.extension_names.append("modified")
    assert "modified" not in (await rpc.mint_risk(TOKEN)).extension_names
    clock[0] += timedelta(seconds=20)
    http.fail_largest = True
    failed = await rpc.mint_risk(TOKEN)
    assert failed.top10_account_fraction is None and failed.data_errors


async def test_rejected_extensions_skip_expensive_holder_request():
    http = FakeHttp(account=mint_account([(14, bytes(64))]))
    risk = await Solana(http, "https://primary.example").mint_risk(TOKEN)
    assert risk.extension_checks_passed is False and not risk.data_errors
    assert len(http.calls) == 1


async def test_provider_slot_mismatch_invalidates_concentration():
    risk = await Solana(FakeHttp(holder_slot=1000), "https://primary.example").mint_risk(TOKEN)
    assert risk.top10_account_fraction is None
    assert risk.data_errors == ["Inconsistent concentration context slot"]


def test_old_snapshot_serialization_remains_compatible():
    value = {"checked_at": "2026-01-01T00:00:00Z", "supported_program": True,
             "mint_authority": False, "freeze_authority": False, "top10_account_fraction": "0.25"}
    assert MintRisk.model_validate(value).model_dump(mode="json") == value


def test_old_component_timestamp_cannot_be_hidden_by_new_overall_check(quote):
    snapshot = quote()
    snapshot.mint_risk.mint_checked_at = snapshot.received_at - timedelta(minutes=10)
    assert "stale_or_future_onchain_checks" in risk_reasons(snapshot, snapshot.received_at, Settings())


def test_new_token2022_record_requires_explicit_extension_verdict(quote):
    snapshot = quote()
    snapshot.mint_risk.program_id = TOKEN_2022_PROGRAM
    assert "token2022_extensions_unverified_or_unsafe" in risk_reasons(snapshot, snapshot.received_at, Settings())


def test_backtest_profile_distinguishes_unsafe_extensions_from_missing_data(quote):
    from backtesting.replay import Observation, quality_profile
    snapshot = quote()
    snapshot.mint_risk.extension_checks_passed = False
    snapshot.mint_risk.top10_account_fraction = None
    assert quality_profile([Observation(1, snapshot)])["risk_data_status"] == {"blocked_extensions": 1}


async def test_duplicate_holder_accounts_are_not_counted_twice():
    class Duplicated(FakeHttp):
        async def request(self, method, url, **kwargs):
            result = await super().request(method, url, **kwargs)
            if kwargs["json"]["method"] == "getTokenLargestAccounts":
                result["result"]["value"][1]["address"] = "A"
            return result
    risk = await Solana(Duplicated(), "https://primary.example").mint_risk(TOKEN)
    assert risk.top10_account_fraction is None and risk.data_errors


def test_sensitive_rpc_urls_are_excluded_from_stored_run_config(tmp_path):
    from data.database import Database
    from trading.engine import Engine
    settings = Settings(solana_rpc_url="https://primary.example/?api-key=private-value",
                        solana_rpc_fallback_urls=["https://backup.example/?api-key=another-private-value"])
    db = Database(tmp_path / "privacy.sqlite3", "demo")
    try:
        Engine(db, settings)
        saved = db.conn.execute("SELECT settings FROM runs").fetchone()[0]
        assert "private-value" not in saved and "solana_rpc_fallback_urls" not in saved
    finally:
        db.close()
