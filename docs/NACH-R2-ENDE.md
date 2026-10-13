# Nach dem R2-Ende: Sicherung und Auswertung

Stand: 13. Oktober 2026, ergänzt um die Cloud-Variante. Diese Anleitung gilt **erst nach dem 16. Oktober 2026,
03:06 Uhr Schweizer Zeit**. Vorher keinen dieser Schritte ausführen, ausser
dem freiwilligen Schritt 0.

Sie ändert nichts am Sammler, an seinen Regeln oder an den Originaldaten.
Alle Befehle lesen die Sammlung nur oder schreiben in **neue** Ordner.

## Überblick

| Schritt | Wo | Was |
| --- | --- | --- |
| 0 | SSH-Konsole des VPS | Freiwillig, schon vorher: Grösse der Datenbank melden |
| 1 | SSH-Konsole des VPS | Prüfen, dass der Sammler regulär beendet ist |
| 2 | SSH-Konsole des VPS | Geprüfte finale Kopie in einen neuen Ordner schreiben |
| 3 | Windows-PowerShell | Kopie auf den PC holen und Prüfsumme vergleichen |
| 4 | Windows, NAS | Zweite Kopie ausserhalb von PC und VPS ablegen |
| 5A | Browser und Claude Code (empfohlen) | Datei über Google Drive an Claude geben, Claude wertet in der Cloud aus |
| 5B | Ubuntu (WSL) auf dem PC (Alternative) | Auswertung selbst auf dem PC |
| 6 | Browser auf dem PC | Bericht öffnen und gemeinsam prüfen |

Für 5A muss auf dem PC nichts installiert werden. 5B braucht eine einmalige
Einrichtung von Ubuntu unter Windows. Beide Wege verwenden denselben
eingefrorenen Code und dasselbe Protokoll.

"SSH-Konsole" heisst: in Windows-PowerShell zuerst `ssh root@159.195.4.228`
eingeben, Passwort eintippen (es bleibt unsichtbar), danach die Befehle eingeben.

## Schritt 0: Grösse der Datenbank (freiwillig, jederzeit)

**SSH-Konsole:**

```bash
ls -lh /var/lib/memecoin-collector/campaign-r2/observations.sqlite3
```

Der Befehl liest nur. Die Grösse hilft, den Speicherbedarf der Auswertung in
Schritt 5 besser abzuschätzen.

## Schritt 1: Ende des Sammlers prüfen

Um 03:06 Uhr beendet sich der Sammler selbst. Er erstellt dabei noch eine
letzte Sicherung. Der Telegram-Monitor schickt einmal die Meldung
"Geplante Sammelzeit ist abgelaufen". Danach kommen keine Tagesberichte mehr.
Das ist so vorgesehen.

**SSH-Konsole:**

```bash
cd /opt/memecoin-collector-r2
.venv/bin/python -m deploy.status
systemctl is-active memecoin-collector
```

Erwartet wird:

- `Sammler-Prozess: beendet; Sammelzeit abgelaufen`
- `Orders: 0; Ausführungen: 0`
- `Letzte Sicherung` mit `Integritätsprüfung: ok`, kurz nach 03:06 Uhr
- `systemctl` meldet `inactive`

Steht dort noch `aktiv` oder `active`, etwa 15 Minuten warten und erneut
prüfen. Bleibt es so, **nichts stoppen oder löschen**, sondern die Ausgabe an
Claude schicken.

## Schritt 2: Finale Kopie erstellen

Das folgende Programm prüft zuerst, dass der Sammler wirklich beendet ist und
der Status `completed_scheduled_window` lautet. Erst dann erstellt es mit der
SQLite-Sicherungsfunktion eine Kopie, prüft deren Integrität und berechnet
eine Prüfsumme. Der Zielordner darf noch nicht existieren. Bei jeder
Abweichung bricht es mit `ABBRUCH` ab, ohne etwas zu verändern.

**SSH-Konsole:** den ganzen Block auf einmal einfügen, von `cd` bis `PY`.

```bash
cd /opt/memecoin-collector-r2
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
import hashlib, json, shutil, sqlite3
from datetime import UTC, datetime
from pathlib import Path
from operations.campaign import locked

SRC = Path('/var/lib/memecoin-collector/campaign-r2')
OUT = Path('/var/lib/memecoin-collector/r2-final-20261016')
APP = Path('/opt/memecoin-collector-r2')

state = json.loads((SRC / 'state.json').read_text())
if locked(SRC):
    raise SystemExit('ABBRUCH: Der Sammler läuft noch. Nichts kopiert.')
if state.get('status') != 'completed_scheduled_window':
    raise SystemExit(f"ABBRUCH: Unerwarteter Status {state.get('status')!r}. Nichts kopiert.")
source = SRC / 'observations.sqlite3'
if shutil.disk_usage(SRC.parent).free < 2 * source.stat().st_size + 2 * 1024**3:
    raise SystemExit('ABBRUCH: Zu wenig freier Speicher. Nichts kopiert.')
if OUT.exists():
    raise SystemExit(f'ABBRUCH: {OUT} existiert schon. Nichts überschrieben.')
OUT.mkdir(mode=0o700)
target = OUT / 'observations-final.sqlite3'
src = sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)
dst = sqlite3.connect(target)
try:
    src.backup(dst)
    integrity = dst.execute('PRAGMA integrity_check').fetchone()[0]
    rows, first, last = dst.execute('SELECT count(*), min(received_at), max(received_at) FROM snapshots').fetchone()
    orders = dst.execute('SELECT count(*) FROM paper_orders').fetchone()[0]
finally:
    dst.close()
    src.close()
if integrity != 'ok':
    raise SystemExit('ABBRUCH: Integritätsprüfung der Kopie fehlgeschlagen. Originale unverändert.')
for name in ('manifest.json', 'state.json'):
    shutil.copy2(SRC / name, OUT / name)
shutil.copy2(APP / 'SHA256SUMS', OUT / 'code-SHA256SUMS')
digest = hashlib.sha256()
with target.open('rb') as stream:
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(block)
when = lambda t: datetime.fromtimestamp(t, UTC).isoformat() if t else None
summary = {'created_at': datetime.now(UTC).isoformat(), 'campaign_status': state['status'],
           'snapshots': rows, 'first_observation_utc': when(first), 'last_observation_utc': when(last),
           'orders': orders, 'integrity': integrity, 'bytes': target.stat().st_size,
           'sha256': digest.hexdigest()}
(OUT / 'pruefung.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps(summary, indent=2))
print('FERTIG: Kopie geprüft. Originale wurden nicht verändert.')
PY
```

Bei einer grossen Datenbank kann das einige Minuten dauern. Am Ende steht
`FERTIG`. Die angezeigte Zeile `sha256` notieren oder als Screenshot sichern.
Erwartet werden `"orders": 0` und `"integrity": "ok"`.

Der neue Ordner `/var/lib/memecoin-collector/r2-final-20261016` enthält:

- `observations-final.sqlite3`: die geprüfte Kopie aller Beobachtungen
- `manifest.json`, `state.json`: Plan und Endzustand der Sammlung
- `code-SHA256SUMS`: Prüfsummen des installierten Codes, zur Herkunft
- `pruefung.json`: Anzahl, Zeitraum, Grösse und Prüfsumme der Kopie

Danach die SSH-Verbindung mit `exit` schliessen.

## Schritt 3: Kopie auf den PC holen

**Windows-PowerShell** (nicht in SSH):

```powershell
scp -r root@159.195.4.228:/var/lib/memecoin-collector/r2-final-20261016 "$HOME\Downloads\"
```

Passwort wie bei SSH. Alternativ den Ordner mit WinSCP nach `Downloads` ziehen.
Danach die Prüfsumme auf dem PC berechnen:

```powershell
Get-FileHash "$HOME\Downloads\r2-final-20261016\observations-final.sqlite3" -Algorithm SHA256
Get-Content "$HOME\Downloads\r2-final-20261016\pruefung.json"
```

Der `Hash` muss dem Wert `sha256` aus `pruefung.json` entsprechen. Windows
zeigt ihn in Grossbuchstaben, das ist kein Unterschied. Weicht er ab, die
Übertragung wiederholen und die fehlerhafte Datei nicht verwenden.

## Schritt 4: Zweite Kopie ausserhalb von PC und VPS

Den ganzen Ordner `r2-final-20261016` zusätzlich auf das NAS, einen USB-Stick
oder in einen eigenen Cloud-Speicher kopieren. Die Sicherungen auf dem VPS liegen auf
derselben Festplatte wie die Originale und schützen nicht vor einem Ausfall
des ganzen Servers.

Auf dem VPS **nichts löschen**: weder die Sammlung noch die Sicherungen noch
den neuen Ordner. Aufräumen besprechen wir erst nach der Auswertung.

## Schritt 5: Auswertung

### Warum nicht auf dem VPS oder dem NAS

Die Auswertung lädt alle Beobachtungen gleichzeitig in den Arbeitsspeicher
(`backtesting/replay.py`). Messung am 13. Oktober mit der eingefrorenen
Entwicklungsreferenz: 3'937 Beobachtungen brauchten rund 110 MB zusätzlich.
Linear hochgerechnet auf voraussichtlich etwa 240'000 R2-Beobachtungen sind
das **grob 6 bis 7 GB**. Das ist eine Hochrechnung, keine Messung mit R2-Daten.

- VPS: 3,8 GiB Arbeitsspeicher. Laut Übergabe lief dort zusätzlich Velincoin;
  der Betreiber meldete am 13. Oktober, dass nur noch der Sammler läuft. Der
  Arbeitsspeicher reicht trotzdem nicht.
- NAS (Synology DS224+): 2 GB Arbeitsspeicher, reicht ebenfalls nicht.

Den Auswertungscode zu ändern ist keine Lösung: Er gehört zum eingefrorenen
Kern. Jede Änderung würde den Fingerprint brechen, und das R2-Protokoll liesse
sich nicht mehr verwenden.

### 5A: Auswertung durch Claude in der Cloud (empfohlen)

Eine Claude-Code-Sitzung in der Cloud hat 15 GB Arbeitsspeicher und 30 GB
freien Platz (geprüft am 13. Oktober). Ein Testdownload über HTTPS lief mit
etwa 23 MB/s. Auf dem PC muss dafür nichts installiert werden.

**1. Datei in Google Drive hochladen, im Browser auf dem PC**

- `drive.google.com` öffnen, "Neu", dann "Datei hochladen".
- `Downloads\r2-final-20261016\observations-final.sqlite3` wählen. Bei etwa
  2 GB dauert das je nach Internetverbindung einige Minuten.

**2. Freigeben**

- Rechtsklick auf die hochgeladene Datei, "Teilen" bzw. "Freigeben".
- Unter "Allgemeiner Zugriff" auf "Jeder, der über den Link verfügt" stellen,
  Rolle "Betrachter". Die genauen Bezeichnungen können je nach Google-Version
  leicht abweichen.
- "Link kopieren".

**3. Claude den Link geben**

Den Link zusammen mit dem Inhalt von `pruefung.json` an Claude schicken. Gibt
es die bisherige Sitzung nicht mehr, eine neue Claude-Code-Sitzung mit diesem
Repository starten und Folgendes einfügen:

```
Lies docs/NACH-R2-ENDE.md, Abschnitt 5A, und führe die Auswertung von R2 aus.
Link zur Datei: <LINK>
Inhalt von pruefung.json: <INHALT>
Ändere keinen Code. Schicke mir bericht.html und result.json.
```

**4. Was Claude dabei macht**

1. Python-Umgebung aus `requirements.txt` einrichten, falls nötig, und
   `python -m pytest -q` ausführen. Erwartet: `337 passed`.
2. Die Datei aus Google Drive mit `curl` herunterladen. Bei grossen Dateien
   verlangt Google manchmal eine Bestätigung. Dafür ist der Download über
   `https://drive.usercontent.google.com/download?id=<ID>&export=download&confirm=t`
   vorgesehen. Dieser Weg ist noch nicht mit der echten Datei getestet.
3. `sha256sum` der Datei mit `sha256` aus `pruefung.json` vergleichen. Bei
   Abweichung abbrechen.
4. Prüfen, dass keine Zugangsdaten enthalten sind:
   `grep -a -c 'api-key=' observations-final.sqlite3` muss `0` ergeben.
   Der Hostname `mainnet.helius-rpc.com` darf vorkommen; der Code speichert
   ihn als Herkunft von Risikobelegen, aber ohne Schlüssel.
5. Datei nach `runtime/r2/` legen (von Git ausgeschlossen). Auswertung und
   Bericht mit genau diesen Befehlen, im Repository-Ordner:

   ```bash
   python -m backtesting.evaluation evaluate \
     --protocol uebergabe/2026-10-12/R2-Referenz/protocol.json \
     --db runtime/r2/observations-final.sqlite3 \
     --out runtime/r2/auswertung
   python -m operations.evaluation_report \
     --result runtime/r2/auswertung/result.json \
     --out runtime/r2/auswertung/bericht.html
   ```

6. `bericht.html` und `result.json` an den Benutzer schicken. Die Daten und
   Ergebnisse werden **nicht** ins Git-Repository übernommen.

**5. Freigabe zurücknehmen**

Sobald Claude den Download bestätigt, in Google Drive unter "Allgemeiner
Zugriff" wieder "Eingeschränkt" einstellen. Die Datei enthält keine
Zugangsdaten, sollte aber nicht dauerhaft öffentlich abrufbar sein.

**Wenn 5A nicht klappt:** Scheitert der Download aus Google Drive, kann ein
Freigabelink vom NAS (File Station) dienen, sofern das NAS von aussen über
HTTPS erreichbar ist. Sonst bleibt 5B.

### 5B: Auswertung selbst auf dem PC (Alternative)

#### Einmalig: Ubuntu unter Windows (WSL) einrichten

Die Projektwerkzeuge laufen unter Linux. WSL stellt Linux unter Windows bereit.
Der PC hat 32 GB Arbeitsspeicher; WSL erhält davon nur einen Teil.

**Windows-PowerShell, als Administrator geöffnet:**

```powershell
wsl --install
```

Danach den PC neu starten. Beim ersten Start von "Ubuntu" einen
Linux-Benutzernamen und ein Passwort festlegen. Das ist ein eigenes Passwort
nur für Ubuntu auf dem PC, nicht das VPS-Passwort.

#### Projekt und Umgebung vorbereiten

**Ubuntu-Konsole (WSL):**

```bash
free -h
python3 --version
sudo apt update && sudo apt install -y python3-venv git
git clone https://github.com/nicolasspzh/MemeCoin-tading_bot.git
cd MemeCoin-tading_bot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
```

Prüfen:

- Bei `free -h` in der Zeile `Mem:` die Spalte `available`. Für die Auswertung
  sollten **mindestens 8 GB** frei sein. Ist es weniger, hier stoppen und
  Claude fragen.
- `python3 --version` muss 3.12 oder neuer zeigen.
- Die Tests müssen mit `337 passed` enden. Sonst nicht weitermachen.

#### Daten in Ubuntu kopieren und prüfen

**Ubuntu-Konsole (WSL)**, im Ordner `MemeCoin-tading_bot`:

```bash
mkdir ~/r2
cp /mnt/c/Users/nicol/Downloads/r2-final-20261016/observations-final.sqlite3 ~/r2/
sha256sum ~/r2/observations-final.sqlite3
```

Die Prüfsumme muss wieder dem Wert aus `pruefung.json` entsprechen.

#### Auswertung starten

**Ubuntu-Konsole (WSL)**, im Ordner `MemeCoin-tading_bot`, mit aktivierter
Umgebung (`source .venv/bin/activate`):

```bash
python -m backtesting.evaluation evaluate \
  --protocol uebergabe/2026-10-12/R2-Referenz/protocol.json \
  --db ~/r2/observations-final.sqlite3 \
  --out ~/r2/auswertung
python -m operations.evaluation_report \
  --result ~/r2/auswertung/result.json \
  --out ~/r2/auswertung/bericht.html
cp ~/r2/auswertung/bericht.html /mnt/c/Users/nicol/Downloads/
```

### Für 5A und 5B: was normal ist

- Das Programm prüft zuerst, dass Code und Protokoll zusammenpassen
  (Fingerprint `8dcc53e9…`). Meldet es `Evaluation failed: ValueError`, nicht
  selbst etwas ändern.
- Die Laufzeit liegt voraussichtlich bei einigen Minuten, vielleicht länger.
- Die erste Ausgabezeile zeigt `status` und `blockers`. **Exitcode 2 und der
  Status `INSUFFICIENT_EVIDENCE` sind ein reguläres Ergebnis**, kein Absturz.
  Er bedeutet: Die vorab festgelegten Anforderungen sind nicht erfüllt.
- Nicht mehrfach mit anderen Einstellungen laufen lassen. Ein zweiter Lauf
  braucht einen neuen `--out`-Ordner, weil bestehende Ergebnisse nie
  überschrieben werden.

## Schritt 6: Bericht ansehen und prüfen

`bericht.html` mit Doppelklick im Browser öffnen. Bei 5A schickt Claude die
Datei, bei 5B liegt sie in `Downloads`. Der Bericht zeigt den Status, alle
sechs Läufe (baseline und stress, je drei Seeds), offene Anforderungen,
Kosten und offene Positionen. Danach prüfen wir das Ergebnis gemeinsam.

Was der Bericht **nicht** bedeutet:

- Auch `REVIEWABLE_HOLDOUT` ist keine Gewinn- oder Echtgeldfreigabe.
- Ein positives simuliertes Ergebnis beweist keine profitable Strategie.
- Fehlende Trades oder Daten sind fehlende Evidenz, kein Nullergebnis.

Hinweis vorab, als begründete Erwartung und nicht als Ergebnis: In der
Entwicklungsreferenz bestand keine einzige bepreiste Beobachtung alle
Einstiegsprüfungen. PumpSwap-Pools sind immer gesperrt. Ein Ergebnis mit dem
Blocker `too_few_closed_trades` wäre deshalb nicht überraschend.

## Nicht tun

- Keine Auswertung vor dem 16. Oktober, 03:06 Uhr, auch nicht mit geänderter Uhrzeit.
- Keine Schwellen, Parameter oder Codedateien ändern, um ein besseres Ergebnis
  zu erhalten.
- Den Sammler nicht neu starten oder verlängern. Er startet nach dem Ende auch
  bei einem Serverneustart nicht erneut.
- Keine alten Installations-, Update- oder Retry-Skripte ausführen.
- Auf dem VPS nichts löschen.
- Keine Passwörter, API-Schlüssel oder Telegram-Token in den Chat kopieren.

## Wenn etwas abweicht

Jede Meldung mit `ABBRUCH`, `BITTE PRÜFEN`, `failed` oder ein unerwarteter
Status ist ein Grund, anzuhalten. Die vollständige Ausgabe ohne Zugangsdaten
an Claude schicken. Die Originaldaten bleiben in jedem dieser Fälle unverändert.
