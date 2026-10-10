import json
import subprocess
import sys

import pytest
from pydantic import ValidationError

from config.settings import load_settings
from main import single_writer


def test_config_file_and_environment_precedence(tmp_path, monkeypatch):
    config = tmp_path / ".env"
    config.write_text('MODE=PAPER\nPOLL_SECONDS=30 # seconds\nDB_PATH="a path/db.sqlite3"\n')
    monkeypatch.setenv("POLL_SECONDS", "40")
    settings = load_settings(config)
    assert settings.poll_seconds == 40
    assert str(settings.db_path) == "a path/db.sqlite3"


def test_live_trading_cannot_be_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("MODE", "LIVE")
    with pytest.raises(ValidationError):
        load_settings(tmp_path / "absent")


def test_rpc_fallback_settings_validate_and_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("SOLANA_RPC_FALLBACK_URLS", "https://one.example,https://two.example")
    assert load_settings(tmp_path / "absent").solana_rpc_fallback_urls == ["https://one.example", "https://two.example"]
    monkeypatch.setenv("SOLANA_RPC_FALLBACK_URLS", "")
    assert load_settings(tmp_path / "absent").solana_rpc_fallback_urls == []
    monkeypatch.setenv("SOLANA_RPC_FALLBACK_URLS", "http://insecure.example")
    with pytest.raises(ValidationError):
        load_settings(tmp_path / "absent")


def test_only_one_writer(tmp_path):
    path = tmp_path / "bot.sqlite3"
    with single_writer(path):
        with pytest.raises(ValueError, match="already uses"):
            with single_writer(path):
                pass


def test_cli_demo_is_repeatable_and_persists(tmp_path):
    command = [sys.executable, "main.py", "demo", "--db", str(tmp_path / "demo.sqlite3")]
    first = subprocess.run(command, capture_output=True, text=True, check=True)
    data = json.loads(first.stdout)
    assert data["data"] == "SYNTHETIC_DEMO"
    assert data["snapshots"] == 18 and data["fills"] == 2
    assert data["open_positions"] == 0 and data["mode"] == "PAPER"
    second = subprocess.run(command, capture_output=True, text=True, check=True)
    assert json.loads(second.stdout) == data
    import sqlite3
    path = tmp_path / "demo.sqlite3"
    with sqlite3.connect(path) as db:
        before = db.execute("SELECT count(*) FROM runs").fetchone()[0]
        wallet = db.execute("SELECT payload FROM wallet").fetchone()[0]
    status = subprocess.run([sys.executable, "main.py", "status", "--source", "demo", "--db", str(path)],
                            capture_output=True, text=True, check=True)
    assert json.loads(status.stdout)["collection"]["quote_attempts"] == 0
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM runs").fetchone()[0] == before
        assert db.execute("SELECT payload FROM wallet").fetchone()[0] == wallet
