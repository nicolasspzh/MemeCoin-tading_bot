# Beobachtungsplan R2 – Update der bestehenden VPS-Installation

> Historischer Ablauf. R2 ist bereits eingerichtet und sammelt. Nicht erneut installieren oder starten; siehe [aktueller Projektstand](../docs/PROJEKTSTAND.md).

Das Update korrigiert die zu kurze Beobachtungsdauer. Es ersetzt keine Daten,
ändert keine Velincoin-Dienste und benötigt keine erneute Schlüsseleingabe.
Es ist ein Update für die bereits installierte Version vom 7. Oktober.

## Installation

1. `memecoin-update-20261008-v3.tar.gz` auf dem PC herunterladen und mit WinSCP
   ungeöffnet nach `/root/` auf den VPS kopieren.
2. Diese Befehle einzeln in der root-SSH-Konsole ausführen:

```bash
mkdir -p /root/memecoin-update-20261008
tar -xzf /root/memecoin-update-20261008-v3.tar.gz -C /root/memecoin-update-20261008 --no-same-owner
bash /root/memecoin-update-20261008/deploy/upgrade.sh
```

Bei einer Fehlermeldung stoppen und deren Ausgabe prüfen. Bestehende Zielpfade
werden nicht überschrieben. Ein unterbrochenes Update erst prüfen lassen;
nicht selbst alte oder neue Datenverzeichnisse löschen.

Der Installer prüft Paket-Hashes, unveränderte bisherige Dienstkonfiguration,
freien Platz, Abhängigkeiten, Tests und das neue zukünftige Protokoll, während
der alte Dienst weiterläuft. Anschließend stoppt er nur den MemeCoin-Dienst,
erstellt eine geprüfte SQLite-Sicherung und startet die neue Version. Er prüft
bis zu zwei Minuten auf erste frische Kurse. Fehlen sie, wird die alte
Dienstkonfiguration wiederhergestellt und bei zuvor aktivem Dienst erneut
gestartet. Ein fehlgeschlagener Wiederstart wird ausdrücklich gemeldet.

Das neue Protokoll muss beim Update noch in der Zukunft liegen. Dieses Paket
deshalb **vor dem 9. Oktober 2026, 02:00 Uhr Schweizer Zeit** installieren.
Danach ist ein neu vorbereitetes zukünftiges Fenster erforderlich.

Neue Pfade:

- Programm: `/opt/memecoin-collector-r2`
- Sammlung: `/var/lib/memecoin-collector/campaign-r2`
- Sicherung der alten Daten und Dienstkonfiguration:
  `/var/lib/memecoin-collector/upgrade-r2`

Die bisherigen Pfade `/opt/memecoin-collector` und
`/var/lib/memecoin-collector/campaign` bleiben bestehen. Der gemeinsame
Dienstname lautet weiterhin `memecoin-collector`. Die vorhandene private
RPC-Konfiguration unter `/etc/memecoin-collector/collector.env` wird übernommen.

## Fortschritt nach dem Update

Die Version des Pakets mit `-v3` enthält die deutsche Statusübersicht und die
optionale [Telegram-Anbindung](TELEGRAM.md). Telegram muss separat mit einem
eigenen Bot eingerichtet werden. Der Sammelplan und das eingefrorene
Testprotokoll bleiben unverändert.

Für die kurze, lesbare Übersicht:

```bash
cd /opt/memecoin-collector-r2
.venv/bin/python -m deploy.status
```

Die Anzeige liest lokale Daten, ohne Helius-Anfragen oder Handelsaktionen.
Sie zeigt Lebenszeichen, Kursalter, Kursabdeckung, Folgekurse, Anfragebudget,
letzte Sicherung und freien Speicher. Ein aktiver Prozess allein bestätigt
keine vollständigen Daten. Fällige, noch unbelegte Folgekurse können teilweise
noch im erlaubten Zeitspielraum eintreffen. Der manuell im Helius-Dashboard
zu prüfende Creditverbrauch wird nicht aus den RPC-Anfragen abgeleitet.
Ein erfolgreicher Aufruf bedeutet nur, dass der Status gelesen werden konnte;
angezeigte Hinweise trotzdem beachten.

Für die ausführliche JSON-Ausgabe:

```bash
cd /opt/memecoin-collector-r2
.venv/bin/python -m operations.campaign status --directory /var/lib/memecoin-collector/campaign-r2
```

Die neuen Zähler beginnen bei null. Das bedeutet keinen Verlust der alten Daten.
Die Ausgabe enthält `observation_tracks` (erste Beobachtungsphase,
Nachbeobachtung, abgeschlossen), `observation_phases` und das über Neustarts
gespeicherte `rpc_request_budget`. Die erste Runde kann nur einen Coin enthalten:
weitere werden absichtlich zeitversetzt aufgenommen. Der Dienst bleibt beim
Schließen von WinSCP/SSH aktiv und startet nach Serverneustarts innerhalb des
festgelegten Zeitfensters wieder.

## Was sich fachlich ändert

- Höchstens acht gleichzeitig beobachtete Coins; höchstens eine neue Aufnahme
  alle zwölf Minuten. Auswahl nach Entdeckungszeit und Adresse, nicht nach
  späterem Kursgewinn oder bestandenen Risikoprüfungen.
- Pro Coin 30 Minuten für neue Ausgangsbeobachtungen, danach bis zu 66 Minuten
  ab dem letzten vorhandenen Ausgangskurs. Dadurch bleibt auch dessen
  Ein-Stunden-Fenster plus sechs Minuten Zeitspielraum beobachtbar.
- Nachbeobachtungen sind ausdrücklich als `followup` markiert. Sie schließen
  vorhandene Zeitfenster, eröffnen keine neuen Fenster und dürfen im Replay
  keine neuen Positionen eröffnen. Bestehende Positionen dürfen anhand dieser
  Kurse weiterhin geschlossen werden. Historische Daten ohne Phasenfeld bleiben
  unverändert lesbar.
- Fehlende Kurse führen nicht zur vorzeitigen Verdrängung einer aufgenommenen
  Beobachtungsreihe. Bleibt ein Coin während der ganzen Anfangsphase ohne Kurs,
  endet sie nach den 30 Minuten, da keine Kursfenster zu verfolgen sind.
- Ein bestätigter Pool wird nicht gewechselt. Fehlt er in der DEX-Sammelantwort,
  wird zusätzlich die Token-Paare-Abfrage für genau diesen Pool versucht.
  Fehlt der Kurs weiterhin, bleibt die Lücke sichtbar.
- Risikoprüfungen einschließlich Fehlerkennzeichen werden bis zu 60 Sekunden
  zwischengespeichert. Ihre ursprünglichen Prüfzeiten bleiben erhalten.
  Unvollständige Prüfungen werden dadurch nicht zu Freigaben. Bei komplett
  fehlendem Preis werden zusätzliche Risiko-RPCs eingespart.
- Maximal 70.000 RPC-Versuche pro UTC-Tag und 600.000 insgesamt in der neuen
  Sammlung. Die Zähler werden vor jeder Anfrage einschließlich Fehlversuchen
  und Ausweichendpunkten dauerhaft gespeichert. Nach Erreichen der Grenze
  laufen DEX-Kursabfragen weiter; fehlende Blockchain-Prüfungen bleiben gesperrt.
  **Anfragen sind keine Credits:** Anbietergewichtung und andere Projekte sind
  nicht erfasst. Den Helius-Creditstand weiterhin kontrollieren.

Die acht Slots begrenzen den Umfang. Nicht alle entdeckten Meme-Coins werden
aufgenommen, nicht alle Pools unterstützt. Ein fester Beobachtungsplan kann
keine ausgefallene Datenquelle ersetzen. Die bisherigen Risiko- und
Qualitätsschwellen werden nicht gelockert; Gewinne sind nicht nachgewiesen.

## Neues Testfenster und Erhalt der alten Untersuchung

Das neue Protokoll liegt unter
`runtime/backtests/phase6-protocol-r2-20261008/protocol.json` im neuen Programm.
Es verwendet bereits bekannte Entwicklungsdaten, den neuen Code und feste
Parameter. Das alte Protokoll ist für die geänderte Software nicht mehr gültig;
seine Datei und die alte Software bleiben in der vorherigen Installation erhalten.

Neues unbekanntes Fenster: **9. Oktober 2026, 02:00 Uhr, bis 16. Oktober 2026,
02:00 Uhr Europe/Zurich**, Ende exklusiv. Die Sammlung endet anschließend am
**16. Oktober um 03:06 Uhr** nach der letzten Nachbeobachtung. Bis dahin keine
Leistungsoptimierung anhand dieses Testfensters durchführen. Ein neuer Plan
garantiert weder ausreichende Daten noch rentable Ergebnisse.

Nach vollständigem Sammelende:

```bash
cd /opt/memecoin-collector-r2
.venv/bin/python -m backtesting.evaluation evaluate \
  --protocol runtime/backtests/phase6-protocol-r2-20261008/protocol.json \
  --db /var/lib/memecoin-collector/campaign-r2/observations.sqlite3 \
  --out /var/lib/memecoin-collector/phase6-r2-auswertung
```

Der Auswertungsordner muss neu sein. Datenlücken, unvollständige Prüfungen,
offene Positionen und zu wenige Trades werden weiterhin als Einschränkungen
ausgewiesen. Vor Testende blockiert die Auswertung.

## Gezielte Rückkehr zur alten Version

Nur wenn eine Rückkehr fachlich gewünscht oder zur Fehlerbehebung nötig ist:

```bash
bash /opt/memecoin-collector-r2/deploy/rollback.sh
```

Das Skript prüft, dass weiterhin genau der R2-Dienst installiert ist, stoppt ihn
und stellt die gespeicherte alte Dienstdatei wieder her. Beide Datenbestände
bleiben erhalten. Die alte Version hat weiterhin den bekannten Planungsfehler
und ihre ursprüngliche Endzeit am 15. Oktober. Ein Rollback ist daher eine
Betriebsreserve, keine gültige Fortsetzung des neuen Tests.
