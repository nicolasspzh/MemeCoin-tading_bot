# Nach dem R3-Test: Sichern, Kopieren, Auswerten

Stand: 25.10.2026. Grundlage ist die erprobte Anleitung nach R2
([NACH-R2-ENDE.md](NACH-R2-ENDE.md)), angepasst auf die R3-Pfade.
Regeln und Testfenster: [R3-PROTOKOLL.md](R3-PROTOKOLL.md).

## Zeiten

| | UTC | Schweizer Zeit (Winterzeit) |
| --- | --- | --- |
| Testfenster endet | 28.10. 00:00 | 28.10. 01:00 Uhr |
| Sammler beendet sich selbst | 28.10. 01:06 | 28.10. 02:06 Uhr |

Alle Schritte unten **frühestens am 28.10. ab 02:30 Uhr**, am besten
einfach am Morgen.

## Überblick

| Schritt | Wo | Was |
| --- | --- | --- |
| 1 | SSH-Konsole | Prüfen, dass der Sammler regulär beendet ist |
| 2 | SSH-Konsole | Geprüfte finale Kopie in einen neuen Ordner schreiben |
| 3 | Windows-PowerShell | Kopie auf den PC holen und Prüfsumme vergleichen |
| 4 | Windows, NAS | Zweite Kopie auf die NAS (Synology DS224+) |
| 5 | Browser | Datei in Google Drive hochladen und Link an Claude geben |
| 6 | Claude in der Cloud | Auswertung gegen das eingefrorene Protokoll |

"SSH-Konsole" heisst: in Windows-PowerShell zuerst
`ssh root@159.195.4.228` eingeben und das Passwort eintippen.

Auf dem VPS wird in keinem Schritt etwas gelöscht.

## Schritt 1: Ende prüfen

**SSH-Konsole:**

```bash
cd /opt/memecoin-collector-r3 && .venv/bin/python -m deploy.status --directory /var/lib/memecoin-collector-r3/campaign-r3
systemctl is-active memecoin-collector-r3
```

Erwartet:

- `Sammler-Prozess: beendet; Sammelzeit abgelaufen`
- `Orders: 0; Ausführungen: 0`
- `Letzte Sicherung` mit `Integritätsprüfung: ok`, kurz nach 02:06 Uhr
- `systemctl` meldet `inactive`

Steht dort noch `aktiv` oder `active`, 15 Minuten warten und erneut prüfen.
Bleibt es so, **nichts stoppen oder löschen**, sondern die Ausgabe an Claude
schicken.

## Schritt 2: Finale Kopie erstellen

Das Programm prüft zuerst, dass der Sammler beendet ist und der Status
`completed_scheduled_window` lautet. Erst dann erstellt es mit der
SQLite-Sicherungsfunktion eine Kopie, prüft deren Integrität und berechnet
eine Prüfsumme. Der Zielordner darf noch nicht existieren. Bei jeder
Abweichung bricht es mit `ABBRUCH` ab, ohne etwas zu verändern. Es ist
dasselbe Programm wie nach R2, nur mit den R3-Pfaden.

**SSH-Konsole:** den ganzen Block auf einmal einfügen, von `cd` bis `PY`.

```bash
cd /opt/memecoin-collector-r3
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
import hashlib, json, shutil, sqlite3
from datetime import UTC, datetime
from pathlib import Path
from operations.campaign import locked

SRC = Path('/var/lib/memecoin-collector-r3/campaign-r3')
OUT = Path('/var/lib/memecoin-collector-r3/r3-final-20261028')
APP = Path('/opt/memecoin-collector-r3')

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

Das kann einige Minuten dauern. Am Ende steht `FERTIG`. Erwartet werden
`"orders": 0` und `"integrity": "ok"`. Die ganze Ausgabe bitte aufbewahren
und an Claude schicken.

Danach die SSH-Verbindung mit `exit` schliessen.

## Schritt 3: Kopie auf den PC holen

**Windows-PowerShell** (nicht in SSH):

```powershell
scp -r root@159.195.4.228:/var/lib/memecoin-collector-r3/r3-final-20261028 "$HOME\Downloads\"
```

Danach die Prüfsumme auf dem PC berechnen:

```powershell
Get-FileHash "$HOME\Downloads\r3-final-20261028\observations-final.sqlite3" -Algorithm SHA256
Get-Content "$HOME\Downloads\r3-final-20261028\pruefung.json"
```

Der `Hash` muss dem Wert `sha256` aus `pruefung.json` entsprechen. Windows
zeigt ihn in Grossbuchstaben, das ist kein Unterschied. Weicht er ab, die
Übertragung wiederholen.

Hinweis aus der Installation: Liegt im Ordner `Downloads` schon ein Ordner
oder eine Datei mit gleichem Namen, legt Windows beim Herunterladen über den
Browser eine Kopie mit `(1)` an. Beim `scp` oben passiert das nicht, dort
wird überschrieben. Darum zählt immer die Prüfsumme.

## Schritt 4: Zweite Kopie auf die NAS

Den ganzen Ordner `r3-final-20261028` aus `Downloads` auf die NAS kopieren,
zum Beispiel im Windows-Explorer auf die freigegebene NAS-Ablage ziehen
oder über File Station hochladen. Die Sicherungen auf dem VPS liegen auf
derselben Festplatte wie die Originale und schützen nicht vor einem
Ausfall des Servers.

Die NAS dient nur als Ablage. Für die Auswertung reichen ihre 2 GB
Arbeitsspeicher nicht (R2 brauchte mindestens 11,4 GB).

## Schritt 5: Datei an Claude geben (Google Drive)

Wie nach R2:

1. `drive.google.com` öffnen, "Neu", dann "Datei hochladen", und
   `Downloads\r3-final-20261028\observations-final.sqlite3` wählen.
2. Rechtsklick auf die Datei, "Freigeben", unter "Allgemeiner Zugriff"
   "Jeder, der über den Link verfügt", Rolle "Betrachter". "Link kopieren".
3. Den Link und den Inhalt von `pruefung.json` an Claude schicken.

Sobald Claude den Download bestätigt hat, die Freigabe wieder auf
"Eingeschränkt" stellen.

Gibt es die bisherige Sitzung nicht mehr, eine neue Claude-Code-Sitzung mit
diesem Repository starten und Folgendes einfügen:

```
Lies docs/NACH-R3-ENDE.md, Schritt 6, und führe die Auswertung von R3 aus.
Link zur Datei: <LINK>
Inhalt von pruefung.json: <INHALT>
Ändere keinen Code. Schicke mir bericht.html und result.json.
```

## Schritt 6: Auswertung (Claude in der Cloud)

1. Prüfen, dass der Kerncode dem Protokoll entspricht:
   `python -c "from backtesting.evaluation import code_digest; print(code_digest())"`
   muss `2e8b8c2bd50a2de684c3c3bdfadfb9f44863d62905ff2b4f1d42860ae7532373`
   ergeben. Sonst abbrechen; dann ist der Stand auf dem Branch nicht der
   eingefrorene.
2. Python-Umgebung aus `requirements.txt` einrichten und
   `python -m pytest -q` ausführen. Alle Tests müssen bestehen.
3. Datei aus Google Drive laden, wie nach R2 über
   `https://drive.usercontent.google.com/download?id=<ID>&export=download&confirm=t`.
4. `sha256sum` mit `sha256` aus `pruefung.json` vergleichen. Bei
   Abweichung abbrechen.
5. `grep -a -c 'api-key=' observations-final.sqlite3` muss `0` ergeben.
6. Datei nach `runtime/r3/` legen (von Git ausgeschlossen) und auswerten:

   ```bash
   python -m backtesting.evaluation evaluate \
     --protocol protocols/r3-20261021/protocol.json \
     --db runtime/r3/observations-final.sqlite3 \
     --out runtime/r3/auswertung
   python -m operations.evaluation_report \
     --result runtime/r3/auswertung/result.json \
     --out runtime/r3/auswertung/bericht.html
   ```

7. `bericht.html` und `result.json` an den Betreiber schicken. Rohdaten und
   Ergebnisse kommen nicht ins Repository; das Ergebnis wird in einem
   eigenen Dokument zusammengefasst, wie bei R2.

## Was das Ergebnis bedeuten kann

Die Auswertung liefert einen von drei Zuständen:

- `INSUFFICIENT_EVIDENCE`: zu wenig Daten oder Trades für eine Aussage
  (wie bei R2). Kein Urteil über die Strategie.
- `REVIEWABLE_HOLDOUT`: Daten und Trades reichen für eine Prüfung. Das
  heisst noch nicht, dass die Strategie Geld verdient. Das zeigen erst die
  Zahlen nach Kosten in beiden Szenarien.
- `SYNTHETIC_ONLY`: nur bei Testdaten, hier nicht zu erwarten.

Eine Handelsfreigabe erteilt die Auswertung nie (`live_trading_approved`
ist immer `false`).

## Aufräumen

Erst nach der Auswertung und erst, wenn die Kopien auf PC und NAS geprüft
sind, besprechen wir, was auf dem VPS gelöscht werden darf.
