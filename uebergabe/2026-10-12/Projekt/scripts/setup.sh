#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
bot_venv="${BOT_VENV:-/workspace/.venvs/memecoin}"
python3 -m venv "$bot_venv"
"$bot_venv/bin/python" -m pip install --disable-pip-version-check --no-cache-dir -r requirements.txt
"$bot_venv/bin/python" -m pip --no-cache-dir check
"$bot_venv/bin/python" -m pytest -q
