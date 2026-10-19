#!/usr/bin/env bash
# Stage D: install a finite R3 probe next to the finished R2 collection.
# Usage: bash probe_r3.sh <probe id, e.g. d2> <hours, 1 to 72>
# Reuses the R2 service user and RPC configuration read-only; changes no R2 file,
# service or data, and no earlier probe. The probe resumes after a reboot until its end time.
set -euo pipefail
umask 022
probe="${1:-}"
hours="${2:-}"
if [[ ! $probe =~ ^d[0-9]+$ || ! $hours =~ ^[0-9]+$ ]] || (( hours < 1 || hours > 72 )); then
  echo 'Aufruf: bash probe_r3.sh <Nummer wie d2> <Stunden 1 bis 72>' >&2
  exit 2
fi
bundle_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
app_dir=/opt/memecoin-collector-r3-probe-$probe
state_dir=/var/lib/memecoin-collector-r3
campaign_dir=$state_dir/probe-$probe
env_file=/etc/memecoin-collector/collector.env
unit_name=memecoin-collector-r3-probe-$probe.service
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
  echo "Abbruch: $env_file fehlt. Ohne den RPC-Zugang aus R2 ist kein Probelauf möglich." >&2
  exit 1
fi
if ! getent passwd memecoin-collector >/dev/null; then
  echo 'Abbruch: Der Dienstbenutzer memecoin-collector aus R2 fehlt.' >&2
  exit 1
fi
if systemctl is-active --quiet memecoin-collector.service; then
  echo 'Abbruch: Der R2-Sammler ist noch aktiv. Er sollte seit dem 16.10. beendet sein. Bitte zuerst klären.' >&2
  exit 1
fi
# Probes share the state directory and its provisioning lock: one at a time.
if [[ -n "$(systemctl list-units 'memecoin-collector-r3-probe*' --state=active --no-legend --plain)" ]]; then
  echo 'Abbruch: Ein anderer R3-Probelauf ist noch aktiv. Bitte zuerst beenden lassen.' >&2
  exit 1
fi
python3 -c 'import sys; assert sys.version_info >= (3, 12), "Python >=3.12 erforderlich"'
cd "$bundle_dir"
sha256sum --check --quiet SHA256SUMS
python3 -c 'import shutil; assert min(shutil.disk_usage(p).free for p in ("/opt", "/var/lib")) > 5*1024**3, "Mindestens 5 GiB frei erforderlich"'

# Stage privately, so failed dependencies or tests leave no installation.
stage_dir="$(mktemp -d /opt/.memecoin-r3-probe.XXXXXX)"
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
cd /opt
mv -- "$stage_dir" "$app_dir"
stage_dir=""
# Recreate console entry points at their final location; venv scripts embed paths.
python3 -m venv "$app_dir/.venv"

until_utc="$(date -u -d "+$hours hours" +%Y-%m-%dT%H:%M:%S+00:00)"
sed -e "s|@UNTIL@|$until_utc|g" -e "s|@ID@|$probe|g" "$app_dir/deploy/memecoin-collector-r3-probe.service" > "$unit_path"
chmod 0644 "$unit_path"
systemd-analyze verify "$unit_path"
systemctl daemon-reload
systemctl enable --now "$unit_name"
sleep 10
systemctl --no-pager --full status "$unit_name" || true
echo
echo "Probelauf gestartet. Ende (UTC): $until_utc. Neue Coins werden bis etwa 66 Minuten vor dem Ende aufgenommen."
echo "Status:  cd $app_dir && .venv/bin/python -m deploy.status --directory $campaign_dir"
echo "Bericht: cd $app_dir && .venv/bin/python -m deploy.probe_report --directory $campaign_dir"
echo "Vorzeitig beenden: systemctl stop $unit_name"
