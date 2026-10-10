import base64
import json
import struct

import pytest

from collectors.http import DataUnavailable
from collectors.mint import TOKEN_PROGRAM
from collectors.rpc_check import DEFAULT_TOKEN, check_rpc, main
from config.settings import Settings


class ProbeHttp:
    def __init__(self, *, primary_down=False, holders_down=False, slots=None, authorities=False):
        self.calls = []
        self.primary_down, self.holders_down = primary_down, holders_down
        self.slots, self.authorities = slots, authorities
        self.mint_calls, self.current_slot = 0, 100

    async def request(self, method, url, **kwargs):
        rpc_method = kwargs["json"]["method"]
        self.calls.append((url, rpc_method))
        assert method == "POST" and kwargs["attempts"] == 1
        if self.primary_down and "primary.example" in url:
            raise DataUnavailable("HTTP 429", status=429, retry_after=90)
        if rpc_method == "getAccountInfo":
            self.current_slot = self.slots[self.mint_calls] if self.slots else 100 + self.mint_calls
            self.mint_calls += 1
            mint = bytearray(82)
            struct.pack_into("<I", mint, 0, int(self.authorities))
            struct.pack_into("<Q", mint, 36, 1000)
            mint[45] = 1
            value = {"owner": TOKEN_PROGRAM, "data": [base64.b64encode(mint).decode(), "base64"]}
        elif rpc_method == "getTokenLargestAccounts":
            if self.holders_down:
                raise DataUnavailable("HTTP 403", status=403)
            value = [{"address": "A", "amount": "700"}]
        else:
            pytest.fail("Unexpected RPC method")
        return {"result": {"context": {"slot": self.current_slot}, "value": value}}


@pytest.fixture
def settings():
    return Settings(solana_rpc_url="https://primary.example/secret-path?key=secret-primary",
                    solana_rpc_fallback_urls=["https://backup.example/secret-path?key=secret-backup"])


async def test_repeated_probe_fetches_fresh_data_and_does_not_approve_trading(settings):
    http = ProbeHttp()
    report = await check_rpc(http, settings, [DEFAULT_TOKEN], rounds=3, interval=0)
    assert report["ready_for_sample"] is True
    assert len(http.calls) == 6 and report["rpc_totals"].get("cache_hits", 0) == 0
    assert [row["mint_slot"] for row in report["checks"]] == [100, 101, 102]
    # A complete concentration measurement can still exceed the trading limit.
    assert report["checks"][0]["top10_account_fraction"] == "0.7"
    assert report["endpoints"][1]["methods"]["getAccountInfo"]["state"] == "not_exercised"
    serialized = json.dumps(report)
    assert "secret" not in serialized and "https://" not in serialized


async def test_probe_exercises_fallback_and_reports_cooldowns(settings):
    http = ProbeHttp(primary_down=True)
    report = await check_rpc(http, settings, [DEFAULT_TOKEN], rounds=3, interval=0)
    assert report["ready_for_sample"] is True
    assert report["rpc_totals"]["fallback_successes"] == 6
    assert sum("primary.example" in url for url, _ in http.calls) == 2
    primary = report["endpoints"][0]["methods"]["getAccountInfo"]
    assert primary["http_status"] == 429 and primary["cooldown_remaining_seconds"] > 80
    assert report["checks"][0]["mint_host"] == "backup.example"


async def test_missing_holders_fails_probe_and_does_not_retry_during_cooldown(settings):
    http = ProbeHttp(holders_down=True)
    report = await check_rpc(http, settings, [DEFAULT_TOKEN], rounds=3, interval=0)
    assert report["ready_for_sample"] is False
    assert all(row["state"] == "incomplete_data" for row in report["checks"])
    assert sum(method == "getTokenLargestAccounts" for _, method in http.calls) == 2
    assert report["rpc_totals"]["cooldown_skips"] == 4


async def test_recovery_does_not_erase_earlier_failed_round(settings, monkeypatch):
    import collectors.solana
    clock = [100.0]
    monkeypatch.setattr(collectors.solana.time, "monotonic", lambda: clock[0])
    http = ProbeHttp(holders_down=True)
    async def recover(_):
        clock[0] += 301
        http.holders_down = False
    monkeypatch.setattr("collectors.rpc_check.asyncio.sleep", recover)
    report = await check_rpc(http, settings, [DEFAULT_TOKEN], rounds=2, interval=10)
    assert [row["state"] for row in report["checks"]] == ["incomplete_data", "complete"]
    assert report["ready_for_sample"] is False
    assert report["checks"][0]["endpoints"][0]["methods"]["getTokenLargestAccounts"]["state"] == "unavailable"
    assert report["endpoints"][0]["methods"]["getTokenLargestAccounts"]["state"] == "response_received"


@pytest.mark.parametrize("slots,state", [([100, 100], "stalled_slots"), ([100, 90], "regressing_slots")])
async def test_repeated_old_or_regressing_slots_do_not_pass(settings, monkeypatch, slots, state):
    async def no_wait(_):
        pass
    monkeypatch.setattr("collectors.rpc_check.asyncio.sleep", no_wait)
    report = await check_rpc(ProbeHttp(slots=slots), settings, [DEFAULT_TOKEN], rounds=2, interval=10)
    assert report["checks"][1]["state"] == state and not report["ready_for_sample"]


async def test_risk_blocked_probe_does_not_claim_holder_access(settings):
    http = ProbeHttp(authorities=True)
    report = await check_rpc(http, settings, [DEFAULT_TOKEN], rounds=1)
    assert report["checks"][0]["state"] == "probe_token_rejected"
    assert not report["ready_for_sample"] and len(http.calls) == 1


async def test_rpc_error_code_is_numeric_and_error_body_is_never_logged(settings):
    class RpcError:
        async def request(self, *args, **kwargs):
            return {"error": {"code": -32005, "message": "secret-provider-response"}}
    report = await check_rpc(RpcError(), settings, [DEFAULT_TOKEN], rounds=1)
    method = report["endpoints"][0]["methods"]["getAccountInfo"]
    assert method["rpc_code"] == -32005 and method["http_status"] is None
    assert not report["ready_for_sample"] and "secret" not in json.dumps(report)
    class MalformedError:
        async def request(self, *args, **kwargs):
            return {"error": {"code": {"secret": "provider-response"}}}
    report = await check_rpc(MalformedError(), settings, [DEFAULT_TOKEN], rounds=1)
    assert "secret" not in json.dumps(report)


@pytest.mark.parametrize("ready,exit_code", [(True, 0), (False, 2)])
def test_cli_saves_new_report_without_opening_wallet(tmp_path, monkeypatch, capsys, ready, exit_code):
    monkeypatch.chdir(tmp_path)
    async def fake_run(settings, args):
        return {"ready_for_sample": ready}
    monkeypatch.setattr("collectors.rpc_check.run", fake_run)
    output = tmp_path / "reports" / "probe.json"
    assert main(["--out", str(output)]) == exit_code
    assert json.loads(output.read_text()) == {"ready_for_sample": ready}
    assert list(tmp_path.rglob("*.sqlite3")) == []
    assert main(["--out", str(output)]) == 2
    assert json.loads(output.read_text()) == {"ready_for_sample": ready}


def test_cli_invalid_credentials_never_appear_in_output(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SOLANA_RPC_URL", "http://bad.example/secret-path?key=secret-value")
    assert main(["--rounds", "1"]) == 2
    captured = capsys.readouterr()
    assert "secret" not in captured.out + captured.err


@pytest.mark.parametrize("args", [["--rounds", "0"], ["--interval", "nan"], ["--token", "invalid"]])
def test_invalid_probe_arguments_do_not_start_network(args, monkeypatch):
    async def forbidden(*_):
        pytest.fail("Network must not start")
    monkeypatch.setattr("collectors.rpc_check.run", forbidden)
    assert main(args) == 2
