#!/usr/bin/env bash
# Recovery for the verified v3 installation whose two-minute readiness check rolled back.
set -euo pipefail
umask 077
script_path="$(readlink -f "${BASH_SOURCE[0]}")"
if [[ $(id -u) -ne 0 ]]; then echo 'Bitte in der root-SSH-Konsole ausführen.' >&2; exit 1; fi
if [[ ${1:-} != --worker ]]; then
  systemd-run --unit=memecoin-r2-retry --property=Type=exec --property=RuntimeMaxSec=55min --property=TimeoutStopSec=90s /usr/bin/bash "$script_path" --worker
  echo 'Prüfung läuft unabhängig von der SSH-Verbindung. Maximal etwa 40 Minuten Datenprüfung.'
  echo 'Fortschritt: journalctl -u memecoin-r2-retry -n 25 --no-pager'
  exit 0
fi
exec 9>/run/lock/memecoin-r2-retry.lock
flock -n 9 || { echo 'Ein Wiederholungsversuch läuft bereits.' >&2; exit 1; }
old_app=/opt/memecoin-collector
new_app=/opt/memecoin-collector-r2
base=/var/lib/memecoin-collector
old_data="$base/campaign"
new_data="$base/campaign-r2"
unit=/etc/systemd/system/memecoin-collector.service
python="$new_app/.venv/bin/python"
for needed in "$old_app/.venv/bin/python" "$python" "$new_app/SHA256SUMS" "$new_data/manifest.json" "$old_data/observations.sqlite3" "$unit" "$base/upgrade-r2/service.before"; do
  [[ -f "$needed" ]] || { echo "Fehlt: $needed. Abbruch vor Umschaltung." >&2; exit 1; }
done
cd "$new_app"
sha256sum --check --quiet SHA256SUMS
"$python" -m deploy.release_check
systemd-analyze verify "$new_app/deploy/memecoin-collector-r2.service"
systemctl is-active --quiet memecoin-collector
"$python" - "$unit" "$base" "$new_data" <<'PY'
import hashlib,json,shutil,sys
from datetime import timedelta
from pathlib import Path
from backtesting.evaluation import utc
from data.models import utcnow
from operations.campaign import load_manifest,locked
from operations.service import service_digest
unit,base,new=map(Path,sys.argv[1:])
release=json.loads(Path('deploy/release.json').read_text())
assert hashlib.sha256(unit.read_bytes()).hexdigest()==release['previous_unit_sha256'], 'Aktiver Dienst ist nicht die erwartete alte Version'
assert unit.read_bytes()==(base/'upgrade-r2/service.before').read_bytes(), 'Gesicherte Dienstkonfiguration weicht ab'
assert shutil.disk_usage(base).free>5*1024**3, 'Mindestens 5 GiB frei erforderlich'
assert utc(release['test_start_utc'])-utcnow()>timedelta(minutes=45), 'Zu spät für einen vollständigen Startversuch vor Testbeginn'
assert not locked(new), 'R2 läuft bereits'
assert not (new/'stop.request').exists(), 'Manueller R2-Stopp muss zuerst geklärt werden'
manifest=load_manifest(new)
assert manifest['service_sha256']==service_digest(), 'R2-Dienstcode geändert'
assert utc(manifest['until'])==utc(release['until']), 'R2-Frist stimmt nicht überein'
assert manifest['settings']['observation_admission_seconds']==720, 'Unerwarteter Aufnahmeabstand'
PY
attempt_dir="$(mktemp -d "$base/upgrade-r2-retry-XXXXXXXX")"
install -m 0600 "$unit" "$attempt_dir/service.before"
cutover=0
success=0
cleanup() {
  result=$?
  trap - EXIT INT TERM HUP
  if [[ $cutover -eq 1 && $success -eq 0 ]]; then
    echo 'Keine erfolgreiche Übernahme. Stelle die alte Dienstkonfiguration wieder her.'
    systemctl stop memecoin-collector || true
    if install -m 0644 "$attempt_dir/service.before" "$unit" && systemctl daemon-reload && systemctl start memecoin-collector; then
      echo 'Alte Dienstkonfiguration wiederhergestellt; Startbefehl erfolgreich. Datenfluss separat prüfen.'
    else
      echo 'ACHTUNG: Wiederherstellung/Start fehlgeschlagen. Dienststatus prüfen.' >&2
    fi
    date -u +%FT%TZ > "$attempt_dir/rollback-at"
  fi
  echo "Diagnose und Sicherungen: $attempt_dir"
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP
cutover=1
systemctl stop memecoin-collector
"$python" - "$old_data" "$new_data" "$attempt_dir" <<'PY'
import json,sqlite3,sys
from pathlib import Path
from operations.campaign import locked
old,new,dest=map(Path,sys.argv[1:])
assert not locked(old) and not locked(new), 'Ein Sammler läuft noch'
for name,source in [('r1',old),('r2',new)]:
    path=source/'observations.sqlite3'
    if not path.exists(): continue
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as src:
        with sqlite3.connect(dest/f'{name}.before.sqlite3') as dst:
            src.backup(dst)
            assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            print(f'{name}: Sicherung geprüft; '+str(dst.execute('SELECT count(*) FROM snapshots').fetchone()[0])+' Beobachtungen',flush=True)
    for filename in ('manifest.json','state.json'):
        p=source/filename
        if p.exists(): (dest/f'{name}.{filename}').write_bytes(p.read_bytes())
PY
"$python" -m deploy.release_check
date -u +%FT%TZ > "$attempt_dir/attempt-started"
install -m 0644 "$new_app/deploy/memecoin-collector-r2.service" "$unit"
systemctl daemon-reload
systemctl start memecoin-collector
echo 'R2 gestartet. Bestehende Sammlung wird fortgesetzt; kein Parameter wurde geändert.'
echo 'Warte auf zwei neue, zeitlich verschiedene Kurse. Weitere Coins werden alle zwölf Minuten aufgenommen.'
deadline=$((SECONDS+2400))
for check in $(seq 1 240); do
  if (( SECONDS >= deadline )); then break; fi
  if timeout 15s "$python" -m deploy.check_ready "$new_data" > "$attempt_dir/candidate.json" 2>/dev/null; then
    if "$python" - "$attempt_dir" <<'PY'
import json,sys
from datetime import datetime
from pathlib import Path
folder=Path(sys.argv[1])
value=json.loads((folder/'candidate.json').read_text())
quote=datetime.fromisoformat(value['data']['last_quote_at'])
started=datetime.fromisoformat((folder/'attempt-started').read_text().strip())
if quote<=started: raise SystemExit(1)
previous=folder/'first-fresh-quote'
if not previous.exists():
    previous.write_text(quote.isoformat())
    print('Erster neuer Kurs bestätigt. Warte auf einen weiteren.',flush=True)
    raise SystemExit(1)
if quote<=datetime.fromisoformat(previous.read_text()): raise SystemExit(1)
(folder/'readiness.json').write_text(json.dumps(value,indent=2))
PY
    then
      success=1
      date -u +%FT%TZ > "$attempt_dir/completed-at"
      echo 'ERFOLGREICH: R2 läuft und liefert neue Kurse. Beide bisherigen Datenbestände bleiben erhalten.'
      "$python" -m deploy.status
      exit 0
    fi
  fi
  if (( check % 6 == 0 )); then echo "Prüfung läuft: ungefähr $((check/6)) Minuten; noch keine zwei neuen Kurse bestätigt."; fi
  sleep 10
done
echo 'Innerhalb der begrenzten Prüfzeit keine zwei neuen Kurse bestätigt. Automatische Rückkehr zu R1.' >&2
exit 1
