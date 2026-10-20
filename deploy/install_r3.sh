#!/usr/bin/env bash
# Stage E: install the R3 test collection next to R2 and the stage D probes.
# Reuses the R2 service user and RPC configuration read-only; changes no R2 file,
# probe, service or data. The unit resumes after a reboot and ends at its deadline.
set -euo pipefail
umask 022
bundle_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
app_dir=/opt/memecoin-collector-r3
campaign_dir=/var/lib/memecoin-collector-r3/campaign-r3
env_file=/etc/memecoin-collector/collector.env
unit_name=memecoin-collector-r3.service
unit_path=/etc/systemd/system/$unit_name

if [[ $(id -u) -ne 0 ]]; then
  echo 'Bitte in der root-SSH-Konsole ausführen.' >&2
  exit 1
fi
if [[ $(cat /proc/1/comm) != systemd ]]; then
  echo 'Abbruch: systemd ist nicht als Systemdienst aktiv.' >&2
  exit 1
fi
for destination in "$app_dir" "$campaign_dir" "$unit_path"; do
  if [[ -e "$destination" || -L "$destination" ]]; then
    echo "Abbruch: $destination existiert bereits. Nichts wurde verändert." >&2
    exit 1
  fi
done
if [[ ! -f "$env_file" ]]; then
  echo "Abbruch: $env_file fehlt. Ohne den RPC-Zugang aus R2 ist kein Test möglich." >&2
  exit 1
fi
if ! getent passwd memecoin-collector >/dev/null; then
  echo 'Abbruch: Der Dienstbenutzer memecoin-collector aus R2 fehlt.' >&2
  exit 1
fi
if systemctl is-active --quiet memecoin-collector.service; then
  echo 'Abbruch: Der R2-Sammler ist noch aktiv. Bitte zuerst klären.' >&2
  exit 1
fi
# Probes and the test share the state directory and its provisioning lock.
if [[ -n "$(systemctl list-units 'memecoin-collector-r3*' --state=active --no-legend --plain)" ]]; then
  echo 'Abbruch: Ein R3-Probelauf ist noch aktiv. Bitte zuerst beenden lassen.' >&2
  exit 1
fi
python3 -c 'import sys; assert sys.version_info >= (3, 12), "Python >=3.12 erforderlich"'
cd "$bundle_dir"
sha256sum --check --quiet SHA256SUMS
python3 -c 'import shutil; assert min(shutil.disk_usage(p).free for p in ("/opt", "/var/lib")) > 5*1024**3, "Mindestens 5 GiB frei erforderlich"'

# Stage privately, so failed dependencies, tests or protocol checks leave no installation.
stage_dir="$(mktemp -d /opt/.memecoin-r3.XXXXXX)"
cleanup() { if [[ -n "$stage_dir" && -d "$stage_dir" ]]; then rm -rf -- "$stage_dir"; fi; }
trap cleanup EXIT
cp -a "$bundle_dir/." "$stage_dir/"
find "$stage_dir" -type d -exec chmod 0755 {} +
find "$stage_dir" -type f -exec chmod 0644 {} +
python3 -m venv "$stage_dir/.venv"
"$stage_dir/.venv/bin/python" -m pip install --disable-pip-version-check -r "$stage_dir/requirements.txt"
"$stage_dir/.venv/bin/python" -m pip check
cd "$stage_dir"
"$stage_dir/.venv/bin/python" -m pytest -q --basetemp "$stage_dir/.install-tests"
rm -rf -- "$stage_dir/.install-tests"
# Frozen protocol, code fingerprint, future window and unit deadline must all agree.
"$stage_dir/.venv/bin/python" -m deploy.release_check
systemd-analyze verify "$stage_dir/deploy/$unit_name"
cd /opt
mv -- "$stage_dir" "$app_dir"
stage_dir=""
# Recreate console entry points at their final location; venv scripts embed paths.
python3 -m venv "$app_dir/.venv"

install -m 0644 "$app_dir/deploy/$unit_name" "$unit_path"
systemctl daemon-reload
systemctl enable --now "$unit_name"
sleep 10
systemctl --no-pager --full status "$unit_name" || true
echo
echo "R3-Test gestartet. Vorlauf bis 21.10. 02:00 Uhr, Testfenster bis 28.10. 02:00 Uhr Schweizer Zeit."
echo "Status:  cd $app_dir && .venv/bin/python -m deploy.status --directory $campaign_dir"
echo "Bericht: cd $app_dir && .venv/bin/python -m deploy.probe_report --directory $campaign_dir"
