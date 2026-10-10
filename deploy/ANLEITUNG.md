# Installation auf dem Debian-13-VPS

> Historischer Ablauf. R2 ist bereits eingerichtet und sammelt. Nicht erneut installieren oder starten; siehe [aktueller Projektstand](../docs/PROJEKTSTAND.md).

Dieses Paket enthält den lokalen Bot-Quellstand und das vorbereitete
Phase-6-Protokoll. Es enthält **keinen API-Schlüssel**, keine Wallet-Schlüssel,
keine virtuelle Python-Umgebung und keine laufende Cloud-Datenbank.
Die Daten aus der Cloud bleiben dort erhalten. Der VPS beginnt eine eigene
Sammlung; die Ergebnisse können später gemeinsam ausgewertet werden.

## 1. Paket auf den Server kopieren

Das bereitgestellte `memecoin-vps-20261007.tar.gz` herunterladen. Mit einem
SFTP-Programm wie WinSCP über denselben Serverzugang wie für SSH nach `/root/`
hochladen. Die Datei muss dort `/root/memecoin-vps-20261007.tar.gz` heißen.
Passwörter und private Schlüssel nicht in den Chat schreiben.

Alternativ in der lokalen Windows-PowerShell (SERVER-IP ersetzen):

```powershell
scp "$HOME\Downloads\memecoin-vps-20261007.tar.gz" root@SERVER-IP:/root/
```

## 2. In der root-SSH-Konsole installieren

```bash
apt-get update
apt-get install -y python3-venv
mkdir /root/memecoin-install-20261007
tar -xzf /root/memecoin-vps-20261007.tar.gz -C /root/memecoin-install-20261007 --no-same-owner
bash /root/memecoin-install-20261007/deploy/install.sh
```

Wenn ein Befehl fehlschlägt, dort stoppen und die Fehlermeldung prüfen.
Eine bestehende Installation wird nicht überschrieben. Der Installer prüft
Datei-Hashes, Abhängigkeiten, die Tests und das unveränderte Phase-6-Protokoll.
Neue Pakete legen ihre Testdateien im eigenen Installationsverzeichnis unter
`/opt` ab. Beim ursprünglichen Paket vom 7. Oktober konnten vier Tests auf
Debian mit kleinem `/tmp`-RAM-Dateisystem mit `disk_space_low` abbrechen, obwohl
auf der eigentlichen Festplatte genug Platz frei war. Zusätzlich wurde ein
sporadischer Testfehler bei der Prüfung des letzten Neustartgrunds behoben.
Für beide Korrekturen das Paket `memecoin-vps-20261007-v2.tar.gz` in ein neues
Verzeichnis entpacken und dessen Installer ausführen. Bereits installierte
Debian-Pakete müssen nicht erneut installiert werden. Die tatsächliche
2-GiB-Speichergrenze des Sammlers bleibt unverändert. Die ersten Vorprüfungen
des Installers verhindern, dass eine bereits bestehende Installation überschrieben
wird. Nicht die Tests überspringen oder den Speicherplatzschutz abschalten.

Er benötigt Zugriff auf die Debian-Paketquellen und den konfigurierten
Python-Paketindex. Falls eine festgeschriebene Paketversion dort nicht verfügbar
ist, ab diesem Fehler stoppen; keine Versionsnummer eigenständig ändern.

Bei der Aufforderung die **vollständige Helius-Mainnet-RPC-URL** einfügen und
Enter drücken. Die Eingabe wird nicht angezeigt. Sie wird lokal als
`/etc/memecoin-collector/collector.env` mit Dateimodus 0600 gespeichert.
systemd lädt sie für den Dienst. Keine Wallet oder Echtgeldfreigabe erforderlich.

Erst nach bestandenen Vorprüfungen werden der neue Benutzer und der Dienst
angelegt. Bei Fehlern während dieser letzten Installationsschritte mögliche
Teilinstallation prüfen, nicht blind Verzeichnisse löschen oder erneut starten.
Der Installer verändert keine Velincoin-Dateien, Dienste, Ports oder Firewall.
Er richtet folgende eigene Pfade ein:

- `/opt/memecoin-collector`: Programm und eigene Python-Umgebung, root gehört der Code.
- `/var/lib/memecoin-collector`: Daten, Sicherungen und Logs, eigener Dienstbenutzer.
- `/etc/memecoin-collector/collector.env`: RPC-Konfiguration, nur root kann die Datei lesen.
- `/etc/systemd/system/memecoin-collector.service`: eigener systemd-Dienst.

Der Dienst startet bei Installation und nach Serverneustarts. Die Sammlung ist
bis **15. Oktober 2026, 03:00 Uhr Schweizer Zeit** begrenzt. Danach startet sie
nicht erneut. Bei API-Ausfällen oder fehlenden Daten können Lücken entstehen.
Ein erneuter Neustart repariert vergangene Lücken nicht. Das Paket ist für
dieses Zeitfenster vorbereitet; bei späterer Installation einen neuen Plan erstellen.

Der Dienst darf höchstens 512 MiB RAM und 50 % eines CPU-Kerns beanspruchen
(auf dem VPS mit zwei Kernen etwa ein Viertel der gesamten CPU-Kapazität).
384 MiB ist die weichere RAM-Schwelle. Die tatsächliche Last wird geprüft,
sobald der Dienst Daten liefert. Ohne zusätzliche Plattenpartition gilt keine
harte Speicherplatzquote; der Sammler stoppt unter 2 GiB freiem Platz. Logs
rotieren und zwei lokale Sicherungen wechseln stündlich. Bei weniger als
5 GiB freiem Platz beginnt der Installer nicht.

## 3. Nach etwa einer Minute den Datenfluss prüfen

```bash
systemctl --no-pager --full status memecoin-collector
cd /opt/memecoin-collector
.venv/bin/python -m operations.campaign status --directory /var/lib/memecoin-collector/campaign
```

Die Statusausgabe enthält keine RPC-URL. Erwartet werden
`supervisor_running: true`, ein aktueller `last_quote_at`, steigende
`priced_snapshots`/`cycles` und null Orders/Fills. `active (running)` alleine
beweist noch keine funktionierende Datenversorgung. Die Ausgabe im Chat teilen,
damit der Umzug geprüft und erst dann die Cloud-Sammlung gestoppt werden kann.

Bei Fehlern:

```bash
journalctl -u memecoin-collector -n 50 --no-pager
```

## Steuerung und Daten

Vorübergehend stoppen (startet bei nächstem Boot wieder):

```bash
systemctl stop memecoin-collector
```

Dauerhaft stoppen und den Boot-Start deaktivieren:

```bash
systemctl disable --now memecoin-collector
```

Innerhalb des unveränderten Sammelfensters wieder aktivieren:

```bash
systemctl enable --now memecoin-collector
```

`operations.campaign stop` legt zusätzlich `stop.request` an. Diese ausdrückliche
Stop-Anforderung wird auch bei Dienst-/Serverneustart respektiert. Für den
normalen VPS-Betrieb die systemctl-Befehle oben nutzen und keinen zweiten
Hintergrundprozess mit `operations.campaign start` starten. Ein alter
`stop.request` benötigt eine bewusste Aufhebung; nicht automatisch löschen.

Originaldaten: `/var/lib/memecoin-collector/campaign/observations.sqlite3`.
Während des Betriebs die SQLite-Backup-API verwenden; nicht nur die Hauptdatei
kopieren, weil neuere Daten noch im WAL liegen können. Für einen Export den
Dienst geordnet stoppen oder eine konsistente Backup-Datei verwenden. Die
Backups liegen auf demselben VPS und ersetzen kein externes Backup.

Die Anwendung bleibt Beobachtungssammler ohne Orders. Die spätere
Strategieauswertung ist bis zum Ende des protokollierten Fensters gesperrt.
Neue Anforderungen/Quellcodeänderungen während der Sammlung erst planen;
eingefrorene Hashes nicht überschreiben und Risiko-Regeln nicht lockern.
