# Phase 7 – Vorbereitung des überwachten Paper-Betriebs

Stand: 8. Oktober 2026. Die technische Betriebsprobe und ein
[eigenständiger Paper-Dienst](PAPER-SERVICE.md) sind implementiert und mit
künstlichen Daten geprüft. Ein Paper-Dienst mit echten Marktdaten ist auf dem
VPS noch nicht eingerichtet. Die unabhängige Phase-6-Auswertung steht aus.

## Jetzt überprüfbar: Prozessabbruch und Wiederherstellung

Im Projektverzeichnis mit der eingerichteten Python-Umgebung:

```bash
python -m operations.paper_rehearsal --out runtime/NEUE-PHASE7-BETRIEBSPROBE
```

Der Ausgabeordner muss neu sein. Der Lauf benötigt keine RPC-/Telegram-
Zugangsdaten, liest keine `.env` und führt keine Netzwerkanfragen aus.
Er verwendet ausschließlich die bereits vorhandenen 18 künstlichen
Demo-Beobachtungen mit den unveränderten Standardparametern der Paper-Engine.

Die Probe führt einen Referenzlauf aus und beendet zwei echte Unterprozesse
per `SIGKILL`: einmal nach einer gespeicherten Kauforder und einmal nach einem
simulierten Kauf mit offener Position. Vor dem Abbruch prüft sie, dass ein
zweiter Schreiber dieselbe Datenbank nicht gleichzeitig übernehmen kann.
Danach werden die gespeicherten Zustände mit der SQLite-Backup-Schnittstelle
gesichert, geprüft und sowohl das Original als auch die Sicherung fortgesetzt.
Ein erneuter Wiederanlauf mit denselben Eingabekursen prüft doppelte Verarbeitung.

Verglichen werden die vollständigen gespeicherten Beobachtungen, Entscheidungen,
Orders, Ausführungen, Ledger-Einträge und Wallet-Beträge. Nur die erwartbar
unterschiedlichen Prozesslauf-IDs werden aus dem Vergleich entfernt. Zusätzlich
wird ein Kursausfall simuliert: die offene Kauforder verfällt, ein verspäteter
Kurs erzeugt keine Ausführung und das virtuelle Kapital bleibt erhalten.

Die maschinenlesbare Evidenz liegt in `result.json` im Ausgabeordner, zusammen
mit den ausschließlich synthetischen Datenbanken. Ergebnis des ersten Laufs:
`runtime/phase7-rehearsal-20261008/result.json`.

Ein bestandener Lauf belegt diese Prozess- und SQLite-Wiederherstellung unter
den getesteten Bedingungen. Er simuliert keinen Stromausfall des Hosts und
belegt weder ausfallsicheren VPS-Speicher noch Strategieprofitabilität. Die
historischen Demozeiten können während einer offenen Position eine Warnung
über veraltete Kurse erzeugen; das ist keine aktuelle Marktmessung.

## Reihenfolge bis zum tatsächlichen Paper-Betrieb

1. **Bereits erledigt:** R2 läuft auf dem VPS, Telegram ist verbunden.
   Am 9. Oktober um 20:32 Uhr Schweizer Zeit meldete der Nutzer 36'478
   Beobachtungen, 134 Coins und eine geprüfte Sicherung. Nicht erneut
   installieren oder das alte Upgrade-/Retry-Skript ausführen.
2. Das neue Testfenster vom 9. bis 16. Oktober, jeweils 02:00 Uhr Schweizer Zeit,
   sammeln; die Nachbeobachtung läuft bis 16. Oktober 03:06 Uhr. Datenqualität
   überwachen, ohne anhand der laufenden Testdaten Strategieparameter anzupassen.
3. Nach dem Sammelende eine konsistente SQLite-Sicherung der tatsächlichen
   VPS-Daten erstellen und Phase 6 mit dem passenden R2-Protokoll auswerten.
   Fehlende Tage, Kurse oder abgeschlossene Trades bleiben fehlende Evidenz;
   Anforderungen nicht nachträglich lockern. `REVIEWABLE_HOLDOUT` bedeutet
   prüfbare Evidenz und ist keine automatische Freigabe oder Gewinngarantie.
4. Ergebnisse einschließlich Stresskosten, offenen Positionen und Datenlücken
   gemeinsam prüfen. Erst dann Umfang und Start eines weiteren Paper-Fensters
   festlegen. Bei unzureichender Evidenz gezielt Datenabdeckung untersuchen und
   gegebenenfalls ein neues zukünftiges Testfenster vorbereiten.
5. Für diesen späteren Betrieb einen getrennten Paper-Dienst mit eigener
   Datenbank, virtueller 50-USD-Wallet, festgelegtem Zeitraum, Sicherungen und
   Telegram-Meldungen für Orders, Buchhaltungsfehler und offene Positionen
   implementieren und auf dem VPS abnehmen. Beobachtungsdatenbanken bleiben
   erhalten und werden nicht nachträglich in Handelsdatenbanken umgewandelt.

## Noch offene technische Arbeit

Der [Offline-Auswertungsbericht](AUSWERTUNGSBERICHT.md) ist als zusätzliche
Darstellung vorbereitet. Er liest vorhandene Ergebnisdateien; die laufenden
R2-Marktdaten werden damit nicht vorzeitig ausgewertet.

- Der neue Dienst besitzt ein eigenes Anfragebudget, Kurspriorisierung für
  offene Positionen/Orders, Statusprüfung, Sicherung/Wiederherstellung und
  ein festes Ende ohne erfundene Liquidation. Diese Funktionen sind synthetisch
  geprüft; eine reale VPS-Abnahme steht aus. Das gemeinsame Helius-Kontingent
  mit weiteren Projekten muss vor einem Parallelbetrieb berücksichtigt werden.
- Die [Paper-Telegram-Ergänzung](PAPER-TELEGRAM.md) für Wallet, Ausführungen,
  fehlgeschlagene Orders und Buchhaltungsfehler ist lokal implementiert und
  geprüft. Installation und echte Zustellprüfung auf dem VPS stehen aus.
- Last und Koexistenz mit dem anderen VPS-Projekt prüfen. Der aktuelle
  Telegram-Zusatz überwacht den Beobachtungsdienst; er ist noch kein Monitor
  für einen eigenständigen Paper-Dienst.

Diese Arbeiten werden außerhalb des eingefrorenen R2-Kerns vorbereitet. Für
Änderungen am Sammler, an Risiko-/Strategiecode oder den Kostenannahmen ist vor
einem neuen unabhängigen Vergleich ein neues zukünftiges Protokoll erforderlich.
Die aktuelle Vorbereitung verändert weder R2-Code noch v3-Archiv, startet keinen
Cloud-Sammler und verbraucht keine zusätzlichen Helius-Credits.
