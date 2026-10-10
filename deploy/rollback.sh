#!/usr/bin/env bash
# Explicit recovery only; no deletion of either dataset or installation.
set -euo pipefail
if [[ $(id -u) -ne 0 ]]; then echo 'Bitte als root ausführen.' >&2; exit 1; fi
backup_dir=/var/lib/memecoin-collector/upgrade-r2
unit=/etc/systemd/system/memecoin-collector.service
test -f "$backup_dir/service.before"
cmp --silent "$unit" /opt/memecoin-collector-r2/deploy/memecoin-collector-r2.service
systemctl stop memecoin-collector
install -m 0644 "$backup_dir/service.before" "$unit"
systemctl daemon-reload
systemctl start memecoin-collector
systemctl --no-pager --full status memecoin-collector
echo 'Vorheriger Dienst wiederhergestellt. Beide Datenbestände bleiben erhalten.'
