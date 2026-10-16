# MemeCoin Trading Bot

Solana-Marktdaten sammeln, Risiken prüfen und Handelsregeln mit **virtuellen
50 USD** untersuchen. Ausschließlich Paper Trading; keine Wallet-Schlüssel,
Transaktionssignierung oder echten Orders. Profitabilität ist nicht nachgewiesen.

## Übergabe an Claude – 12. Oktober 2026

Das vollständige entpackte Übergabepaket liegt unter
[`uebergabe/2026-10-12/`](uebergabe/2026-10-12/).
**Zuerst den [Startauftrag](uebergabe/2026-10-12/START-FUER-CLAUDE.md), dann die
[vollständige Übergabe](uebergabe/2026-10-12/UEBERGABE.md) lesen.**
Die [Leseanleitung](uebergabe/README.md) erklärt aktuelle Quellen, eingefrorene
Referenzdaten und historische Pakete. Die enthaltene Entwicklungsdatenbank ist
keine Kopie der aktuell laufenden VPS-Sammlung.

## Aktueller Stand am 16. Oktober 2026

**[Projektstand und nächste Schritte](docs/PROJEKTSTAND.md)**

- Die R2-Datensammlung auf dem VPS ist planmässig beendet (16. Oktober 2026, 03:06 Uhr).
- Ergebnis der vorab festgelegten Auswertung: **`INSUFFICIENT_EVIDENCE`**, gute
  Datenqualität, aber null Trades. Ursachen und Analyse: **[R2-Ergebnis](docs/R2-ERGEBNIS.md)**.
- Eigenständiger Paper-Dienst, Paper-Telegram und Auswertungsbericht sind lokal
  vorbereitet. Neue Anti-FOMO-/Risikogrößen-Regeln sind isolierte Testvarianten.
- **337 Tests**. Profitabilität bleibt unbelegt; die R2-Daten gelten jetzt als
  Entwicklungsdaten für eine nächste Version.

Dieses Repository enthält Code, Tests, Dienstvorlagen, Anleitungen und
künstliche Vorschauen sowie seit dem 12. Oktober das ausdrücklich freigegebene
Übergabepaket mit eingefrorener R2-Entwicklungsreferenz und historischen Paketen.
Es enthält keine API-Schlüssel, Telegram-Zugangsdaten,
laufenden Datenbanken, Logs oder aktuellen Server-Backups. Ein GitHub-Upload
aktualisiert den VPS nicht. Die laufende Installation unverändert lassen.

## Lokal ausprobieren – ohne Anbieterzugänge

Python **3.12 oder neuer**, Linux/macOS. Windows: WSL für den Python-Betrieb;
HTML-Vorschauen funktionieren direkt im Browser. Prozesssperren verwenden
`fcntl`, die Servervorlagen systemd.

```bash
git clone https://github.com/nicolasspzh/MemeCoin-tading_bot.git
cd MemeCoin-tading_bot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
```

Künstliche Demo, ohne `.env` oder Marktdatenabruf:

```bash
python main.py demo --db runtime/meine-demo.sqlite3
python -m operations.entry_variants --out runtime/meine-einstiegsvarianten
```

Für jede neue Probe neue Ausgabepfade wählen. Die zweite Probe erzeugt
`Vorschau.html` mit einem Vergleich von Einstiegsentscheidungen; sie erzeugt
keine Trades und berechnet keine Rendite.

## Anleitungen

| Thema | Dokument |
| --- | --- |
| Was läuft, was fehlt, Zeitfenster | [Projektstand](docs/PROJEKTSTAND.md) |
| Ergebnis und Analyse von R2 | [R2-Ergebnis](docs/R2-ERGEBNIS.md) |
| Plan für die nächste Version | [R3-Plan](docs/R3-PLAN.md) |
| R3-Diagnose auf den R2-Daten | [Stufe C](docs/R3-STUFE-C-DIAGNOSE.md) |
| Nach dem R2-Ende: Sicherung und Auswertung | [Nach R2](docs/NACH-R2-ENDE.md) |
| Recherche und Ideen für die nächste Version | [Recherche](docs/RECHERCHE-2026-10-13.md) |
| Fortschritt auf dem bereits eingerichteten VPS | [Statusbefehl](docs/PROJEKTSTAND.md#auf-dem-vps-bestätigt) |
| Bestehende Telegram-Anbindung des Sammlers | [Telegram](deploy/TELEGRAM.md) |
| Phase 7 und technische Betriebsprobe | [Phase 7](operations/PHASE7.md) |
| Eigenständiger Paper-Dienst | [Paper-Dienst](operations/PAPER-SERVICE.md) |
| Zusätzliche Telegram-Meldungen für Paper | [Paper-Telegram](operations/PAPER-TELEGRAM.md) |
| Spätere Auswertung im Browser | [Auswertungsbericht](operations/AUSWERTUNGSBERICHT.md) |
| Anti-FOMO und Positionsgröße | [Einstiegsvarianten](operations/EINSTIEGSVARIANTEN.md) |
| Künstliche Vorschauen herunterladen/öffnen | [Beispiele](docs/beispiele/README.md) |
| Frühere Phasen und technische Details | [Entwicklungsverlauf](docs/ENTWICKLUNGSVERLAUF.md) |

Die Anleitungen unter `deploy/` zur [Erstinstallation](deploy/ANLEITUNG.md),
[zur R2-Umstellung](deploy/UPDATE-R2.md) und [zur damaligen Wiederholung](deploy/RETRY-R2.md)
sind historische Dokumentation. Nicht auf dem bereits laufenden VPS erneut
ausführen. Sie setzen separate Originalpakete und damalige Zeitfenster voraus.

## Aufbau

- `collectors/`: DEX-/Solana-Abfragen, Mint-/Holder-/Pool-Prüfungen, Beobachtungsplanung.
- `trading/`: feste Strategie, Risikovetos, virtuelle Wallet und simulierte Ausführung.
- `data/`: Modelle und atomare SQLite-Speicherung.
- `backtesting/`: reproduzierbarer Replay, Datenqualität und vorab festgelegte Auswertung.
- `operations/`: Dienste, Sicherungen, Berichte und getrennte Forschungsergänzungen.
- `deploy/`: historische Installation, Statusanzeige und Sammler-Telegram.
- `tests/`: automatisierte Prüfungen mit isolierten Testdaten.

## Reale Daten und Zugangsdaten

Für eine spätere bewusst eingerichtete Marktdatensammlung erklärt
[der Entwicklungsverlauf](docs/ENTWICKLUNGSVERLAUF.md) die Konfiguration.
`.env.example` enthält ausschließlich Beispielwerte. Private Zugangsdaten
gehören in eine ignorierte `.env` oder sichere Umgebungsvariablen.
Auf dem bereits eingerichteten VPS sind diese separat gespeichert.

Die eingefrorene R2-Entwicklungsreferenz und das vollständige Protokoll liegen
seit der Übergabe unter `uebergabe/2026-10-12/R2-Referenz/`. Lokale Demo und Tests
benötigen sie nicht. Historische Paketbauer erwarten weiterhin ihre ursprünglichen
`runtime/`-Pfade und sind kein aktueller Installationsweg. Für Auswertungen
die Originalreferenz ausdrücklich zuordnen; keine neuen Daten als Ersatz
unter einem alten Protokoll ausgeben.
