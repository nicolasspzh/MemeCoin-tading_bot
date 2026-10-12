#!/usr/bin/env bash
# First installation only. Does not modify existing services, firewall or ports.
set -euo pipefail
umask 022
bundle_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$bundle_dir/deploy/release.json" ]]; then
  echo 'Dieses Paket aktualisiert die vorhandene Installation. Bitte deploy/upgrade.sh verwenden.' >&2
  exit 2
fi
app_dir=/opt/memecoin-collector
state_dir=/var/lib/memecoin-collector
config_dir=/etc/memecoin-collector
unit_path=/etc/systemd/system/memecoin-collector.service

if [[ $(id -u) -ne 0 ]]; then
  echo 'Bitte in der root-SSH-Konsole ausführen.' >&2
  exit 1
fi
for destination in "$app_dir" "$state_dir" "$config_dir" "$unit_path"; do
  if [[ -e "$destination" || -L "$destination" ]]; then
    echo "Abbruch: $destination existiert bereits. Bestehende Installation zuerst prüfen." >&2
    exit 1
  fi
done
if getent passwd memecoin-collector >/dev/null || getent group memecoin-collector >/dev/null; then
  echo 'Abbruch: Benutzer oder Gruppe memecoin-collector existiert bereits.' >&2
  exit 1
fi
python3 -c 'import sys; assert sys.version_info >= (3, 12), "Python >=3.12 erforderlich"'
python3 -c 'from datetime import datetime, timezone; assert datetime.now(timezone.utc) < datetime(2026,10,15,1,tzinfo=timezone.utc), "Sammelfenster bereits beendet"'
if [[ $(cat /proc/1/comm) != systemd ]]; then
  echo 'Abbruch: systemd ist nicht als Systemdienst aktiv.' >&2
  exit 1
fi
cd "$bundle_dir"
sha256sum --check --quiet SHA256SUMS
python3 -c 'import shutil; assert shutil.disk_usage("/opt").free > 5*1024**3, "Mindestens 5 GiB freier Platz erforderlich"'

# Stage privately, so failed dependency/tests/credential entry leave no install.
stage_dir="$(mktemp -d /opt/.memecoin-install.XXXXXX)"
cleanup() { if [[ -n "$stage_dir" && -d "$stage_dir" ]]; then rm -rf -- "$stage_dir"; fi; }
trap cleanup EXIT
cp -a "$bundle_dir/." "$stage_dir/"
find "$stage_dir" -type d -exec chmod 0755 {} +
find "$stage_dir" -type f -exec chmod 0644 {} +
python3 -m venv "$stage_dir/.venv"
"$stage_dir/.venv/bin/python" -m pip install --disable-pip-version-check -r "$stage_dir/requirements.txt"
"$stage_dir/.venv/bin/python" -m pip check
cd "$stage_dir"
# Debian 13 may mount /tmp as a small RAM filesystem. Use the already checked
# /opt filesystem for test artifacts; clean up only this private staging path.
"$stage_dir/.venv/bin/python" -m pytest -q --basetemp "$stage_dir/.install-tests"
rm -rf -- "$stage_dir/.install-tests"
"$stage_dir/.venv/bin/python" -c 'from pathlib import Path; from backtesting.evaluation import load_protocol; load_protocol(Path("runtime/backtests/phase6-protocol-20261007/protocol.json")); print("Phase-6-Protokoll unverändert gültig.")'
"$stage_dir/.venv/bin/python" deploy/write_env.py "$stage_dir/collector.env"

useradd --system --user-group --home-dir "$state_dir" --shell /usr/sbin/nologin memecoin-collector
install -d -m 0750 -o memecoin-collector -g memecoin-collector "$state_dir"
install -d -m 0700 "$config_dir"
install -m 0600 "$stage_dir/collector.env" "$config_dir/collector.env"
rm -- "$stage_dir/collector.env"
cd /opt
mv -- "$stage_dir" "$app_dir"
stage_dir=""
# Recreate console entry points at their final location; venv scripts embed paths.
python3 -m venv "$app_dir/.venv"
install -m 0644 "$app_dir/deploy/memecoin-collector.service" "$unit_path"
systemctl daemon-reload
systemctl enable --now memecoin-collector.service
systemctl --no-pager --full status memecoin-collector.service
echo 'Installiert. Erste Daten brauchen ungefähr eine Minute.'
echo 'Status: cd /opt/memecoin-collector && .venv/bin/python -m operations.campaign status --directory /var/lib/memecoin-collector/campaign'
