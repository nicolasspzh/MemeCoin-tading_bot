import os
from datetime import timedelta
from pathlib import Path

import pytest

from config.settings import Settings
from data.models import utcnow
from deploy.write_env import write_env
from operations import campaign, service


@pytest.mark.parametrize("result,expected", [("completed_scheduled_window", 0), ("stopped_by_request", 0),
                                         ("repeated_start_failure", 1), ("disk_space_low", 1)])
def test_foreground_service_keeps_lock_and_reports_failures(tmp_path, monkeypatch, result, expected):
    directory = tmp_path / "campaign"
    until = (utcnow() + timedelta(days=7)).isoformat()
    monkeypatch.setattr(service, "load_settings", lambda: Settings())
    calls = []
    def supervise(path, fd):
        try:
            assert campaign.locked(path)
            calls.append(path)
            campaign.atomic_json(path / "state.json", {"status": result})
        finally:
            os.close(fd)
    monkeypatch.setattr(service, "supervise", supervise)
    assert service.run(directory, until) == expected
    assert calls == [directory]
    assert not campaign.locked(directory)
    manifest = campaign.load_manifest(directory)
    assert manifest["service_sha256"] == service.service_digest()
    assert manifest["settings"]["max_watch_tokens"] == 8
    assert "systemd" in manifest["hosting"]
    original = (directory / "manifest.json").read_bytes()
    assert service.run(directory, until) == expected
    assert (directory / "manifest.json").read_bytes() == original


def test_expired_service_never_creates_new_campaign(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "supervise", lambda *a: pytest.fail("expired collection"))
    directory = tmp_path / "campaign"
    assert service.run(directory, (utcnow() - timedelta(seconds=1)).isoformat()) == 0
    assert not directory.exists()


def test_manual_stop_survives_service_restart(tmp_path, monkeypatch):
    directory = tmp_path / "campaign"
    until = (utcnow() + timedelta(days=7)).isoformat()
    def supervise(path, fd):
        os.close(fd)
        (path / "stop.request").touch()
        campaign.atomic_json(path / "state.json", {"status": "stopped_by_request"})
    monkeypatch.setattr(service, "load_settings", lambda: Settings())
    monkeypatch.setattr(service, "supervise", supervise)
    assert service.run(directory, until) == 0
    monkeypatch.setattr(service, "supervise", lambda *a: pytest.fail("manual stop ignored"))
    assert service.run(directory, until) == 0
    assert (directory / "stop.request").exists()


def test_service_refuses_existing_foreign_campaign(tmp_path):
    directory = tmp_path / "campaign"
    until = (utcnow() + timedelta(days=7)).isoformat()
    campaign.initialize(directory, until, Settings())
    with pytest.raises(ValueError, match="not provisioned"):
        service.run(directory, until)


def test_service_refuses_deadline_or_software_changes(tmp_path, monkeypatch):
    directory = tmp_path / "campaign"
    until = (utcnow() + timedelta(days=7)).isoformat()
    def supervise(path, fd):
        os.close(fd)
        campaign.atomic_json(path / "state.json", {"status": "stopped_by_request"})
    monkeypatch.setattr(service, "load_settings", lambda: Settings())
    monkeypatch.setattr(service, "supervise", supervise)
    service.run(directory, until)
    with pytest.raises(ValueError, match="deadline differs"):
        service.run(directory, (utcnow() + timedelta(days=8)).isoformat())
    monkeypatch.setattr(service, "service_digest", lambda: "modified-service")
    with pytest.raises(ValueError, match="software changed"):
        service.run(directory, until)


def test_env_file_private_and_never_overwrites_existing_secret(tmp_path):
    path = tmp_path / "collector.env"
    write_env(path, "https://mainnet.helius-rpc.com/?api-key=test-key")
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.read_text() == "MODE=PAPER\nSOLANA_RPC_URL=https://mainnet.helius-rpc.com/?api-key=test-key\n"
    with pytest.raises(FileExistsError):
        write_env(path, "https://mainnet.helius-rpc.com/?api-key=replacement")
    assert "replacement" not in path.read_text()


@pytest.mark.parametrize("value", ["https://mainnet.helius-rpc.com/?api-key=***", "https://example.com/?api-key=x",
                                  "https://mainnet.helius-rpc.com/", "https://mainnet.helius-rpc.com/?api-key=x\nMODE=LIVE",
                                  "https://user:password@mainnet.helius-rpc.com/?api-key=x"])
def test_bad_or_multiline_secrets_never_write_a_file(tmp_path, value):
    path = tmp_path / "collector.env"
    with pytest.raises(ValueError):
        write_env(path, value)
    assert not path.exists()
