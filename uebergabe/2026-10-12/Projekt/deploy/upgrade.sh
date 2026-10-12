#!/usr/bin/env bash
# Install R2 beside R1; leave R1 running until dependencies/tests pass.
set -euo pipefail
umask 022
bundle_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
old_app=/opt/memecoin-collector
new_app=/opt/memecoin-collector-r2
old_data=/var/lib/memecoin-collector/campaign
new_data=/var/lib/memecoin-collector/campaign-r2
backup_dir=/var/lib/memecoin-collector/upgrade-r2
unit=/etc/systemd/system/memecoin-collector.service
if [[ $(id -u) -ne 0 ]]; then echo 'Bitte als root über SSH ausführen.' >&2; exit 1; fi
for needed in "$old_app/.venv/bin/python" "$old_data/manifest.json" "$old_data/observations.sqlite3" "$unit" /etc/memecoin-collector/collector.env; do
  if [[ ! -f "$needed" ]]; then echo "Fehlt: $needed. Bestehende Installation zuerst prüfen." >&2; exit 1; fi
done
for target in "$new_app" "$new_data" "$backup_dir"; do
  if [[ -e "$target" || -L "$target" ]]; then echo "Abbruch: $target existiert bereits. Keine Daten überschrieben." >&2; exit 1; fi
done
if [[ $(cat /proc/1/comm) != systemd ]]; then echo 'systemd erforderlich.' >&2; exit 1; fi
getent passwd memecoin-collector >/dev/null
cd "$bundle_dir"
sha256sum --check --quiet SHA256SUMS
python3 - "$unit" <<'PY'
import hashlib,json,shutil,sys
from pathlib import Path
config=json.loads(Path('deploy/release.json').read_text())
assert hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest()==config['previous_unit_sha256'], 'Dienstkonfiguration wurde verändert; erst prüfen'
assert shutil.disk_usage('/opt').free > 5*1024**3, 'Mindestens 5 GiB frei unter /opt erforderlich'
assert shutil.disk_usage('/var/lib/memecoin-collector').free > 5*1024**3, 'Mindestens 5 GiB frei im Datenverzeichnis erforderlich'
PY
old_active=0
if systemctl is-active --quiet memecoin-collector; then old_active=1; fi
cutover=0
success=0
cleanup() {
  result=$?
  if [[ $success -eq 0 && $cutover -eq 1 ]]; then
    echo 'Update nicht erfolgreich. Vorherige Dienstkonfiguration wird wiederhergestellt.' >&2
    systemctl stop memecoin-collector || true
    if install -m 0644 "$backup_dir/service.before" "$unit" && systemctl daemon-reload; then
      if [[ $old_active -eq 1 ]]; then
        if ! systemctl start memecoin-collector; then echo 'Wiederstart des alten Dienstes fehlgeschlagen; Status prüfen.' >&2; fi
      fi
    else
      echo 'Wiederherstellung fehlgeschlagen; gespeicherte service.before und Dienststatus prüfen.' >&2
    fi
  elif [[ $success -eq 0 ]]; then
    echo 'Update vor der Umschaltung abgebrochen. Die bestehende Installation wurde nicht umgeschaltet.' >&2
  fi
  exit "$result"
}
trap cleanup EXIT
install -d -m 0755 "$new_app"
cp -a "$bundle_dir/." "$new_app/"
find "$new_app" -type d -exec chmod 0755 {} +
find "$new_app" -type f -exec chmod 0644 {} +
python3 -m venv "$new_app/.venv"
"$new_app/.venv/bin/python" -m pip install --disable-pip-version-check -r "$new_app/requirements.txt"
"$new_app/.venv/bin/python" -m pip check
cd "$new_app"
"$new_app/.venv/bin/python" -m pytest -q --basetemp "$new_app/.install-tests"
rm -rf -- "$new_app/.install-tests"
"$new_app/.venv/bin/python" -m deploy.release_check
systemd-analyze verify "$new_app/deploy/memecoin-collector-r2.service"
install -d -m 0700 "$backup_dir"
install -m 0644 "$unit" "$backup_dir/service.before"
printf '%s\n' "$old_active" > "$backup_dir/previously-active"
cutover=1
systemctl stop memecoin-collector
"$new_app/.venv/bin/python" - "$old_data" "$backup_dir" <<'PY'
import json,shutil,sqlite3,sys
from pathlib import Path
from operations.campaign import locked
source,target=map(Path,sys.argv[1:])
assert not locked(source), 'Alter Sammler läuft noch'
with sqlite3.connect((source/'observations.sqlite3').as_uri()+'?mode=ro',uri=True) as src:
    with sqlite3.connect(target/'observations.before.sqlite3') as dst:
        src.backup(dst)
        assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        rows=dst.execute('SELECT count(*) FROM snapshots').fetchone()[0]
for name in ('manifest.json','state.json'):
    if (source/name).exists(): shutil.copy2(source/name,target/name)
(target/'backup-check.json').write_text(json.dumps({'snapshots':rows,'integrity':'ok'}))
print(f'Bisherige Daten gesichert: {rows} Beobachtungen; Integrität ok.')
PY
# Recheck future boundary after tests/backup, before switching the unit.
"$new_app/.venv/bin/python" -m deploy.release_check
install -m 0644 "$new_app/deploy/memecoin-collector-r2.service" "$unit"
systemctl daemon-reload
systemctl start memecoin-collector
for check in $(seq 1 60); do
  if "$new_app/.venv/bin/python" -m deploy.check_ready "$new_data" > "$backup_dir/readiness.json" 2>/dev/null; then
    success=1
    date -u +%FT%TZ > "$backup_dir/completed-at"
    echo 'Update erfolgreich: neue Kurse gespeichert. Alte Installation und Daten bleiben erhalten.'
    cat "$backup_dir/readiness.json"
    exit 0
  fi
  sleep 2
done
echo 'Noch kein bestätigter Datenfluss nach zwei Minuten. Update wird zurückgenommen; neue Dateien bleiben zur Diagnose erhalten.' >&2
exit 1
