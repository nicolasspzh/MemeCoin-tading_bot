# Projektstand am 10. Oktober 2026

Dieses Dokument trennt vorhandenen Code, lokale Tests und den vom Betreiber
bestätigten VPS-Betrieb. Der Bot führt keine echten Trades aus. Eine profitable
Strategie ist bisher nicht nachgewiesen.

## Auf dem VPS bestätigt

Quelle: vom Betreiber bereitgestellte Statusausgabe vom **10. Oktober 2026,
16:23:16 Uhr Europe/Zurich**. Das ist ein gespeicherter Stand, keine Live-Anzeige.

| Merkmal | Stand |
| --- | --- |
| System | Debian 13, Python 3.13.5, systemd |
| Sammler | R2 aktiv, ausschließlich Beobachtung |
| Beobachtungen | 63'773 |
| Coins mit Beobachtungen | 232 |
| Beobachtungen mit Kurs | 62'765 / 63'773, rund 98,4 % |
| Stundenfolgekurse | 19'489 / 19'491 bereits fällige Werte |
| Orders / Ausführungen | 0 / 0 |
| RPC-Versuche der Sammlung | 57'698 / 600'000; keine Helius-Creditmessung |
| Letzte Sicherung | 10. Oktober 16:08:29, Integritätsprüfung ok |
| Telegram | Tagesbericht ab 09:00 Schweizer Zeit; Störungsprüfung alle fünf Minuten |
| Sammelende einschließlich Nachbeobachtung | **16. Oktober 2026, 03:06 Uhr Schweizer Zeit** |

`data_degraded=true` bleibt sichtbar. In den Logs vom 9. Oktober wurden
Kapazitätsgrenzen und noch ausstehende Pool-Discovery-Transaktionen gemeldet.
Die Statusausgabe vom 10. Oktober belegt deren aktuelle Ursache nicht allein.
Nahezu vollständige Folgekurse aufgenommener Coins sind keine vollständige
Marktabdeckung. Zurückgestellte Kandidaten und fehlende Kurse bleiben relevant.

Nur zum Lesen des aktuellen Status auf dem bereits eingerichteten VPS:

```bash
cd /opt/memecoin-collector-r2
.venv/bin/python -m deploy.status
```

Die Cloud-Sammlung ist gestoppt. Nicht parallel neu starten. Die laufende
VPS-Installation nicht mit einem Git-Pull oder alten Upgrade-Skripten ersetzen.
Quellcode auf GitHub hochzuladen ist keine Bereitstellung auf dem Server.

## Implementiert und lokal getestet

- Marktdaten-Erkennung, Risikoprüfungen und persistente Beobachtungsplanung.
- Paper-Engine mit virtuellen 50 USD, reserviertem Kapital, späteren
  Ausführungskursen, Gebühren, Slippage, Preiseinfluss und Ausfallannahmen.
- Replay und Phase-6-Auswertung mit eingefrorenem Protokoll und Stresskosten.
- Eigenständiger Paper-Dienst: begrenzte Laufzeit, Wiederanlauf, Sicherung,
  Wiederherstellung und Status. Auf dem VPS noch nicht installiert.
- Paper-Telegram-Ergänzung: getestete Nachrichtenlogik, noch kein echter
  Zustelltest dieses neuen Dienstes auf dem VPS. Der Sammler nutzt bereits
  seine separate Telegram-Anbindung.
- Offline-Auswertungsbericht aus vorhandener `result.json`.
- Separate Anti-FOMO- und Risikogrößen-Varianten: nur synthetischer
  Entscheidungsvergleich, noch kein vollständiger Ausführungs-/Gewinnvergleich.

Der veröffentlichte Stand wird mit **337 Tests** aus einer sauberen Quellkopie
ohne `.env`, laufende Datenbank oder eingefrorene lokale Entwicklungsdaten
geprüft. Tests ersetzen keine Abnahme des tatsächlichen VPS-Betriebs.

## Eingefrorene R2-Evidenz

Das unabhängige Zeitfenster reicht vom 9. bis 16. Oktober 2026, jeweils
02:00 Uhr Europe/Zurich. Die Nachbeobachtung endet um 03:06 Uhr.

- Protokoll-Fingerprint: `a3069969150f38ea8739e55f929b5fffcd819867bee6dbf238ccf9f0e44396f9`
- Kern-Fingerprint: `8dcc53e9b17e18bfa1d5c2ac10facbd0bc1cc8b75dea61064c55589f29a5b9bd`
- Unverändertes v3-Archiv: `4483d005818421a416da9431b3012613ada1e6230ecc5dffc627388a774b40e4`

Diese Hashes dokumentieren Zuordnungen, keine Profitabilität. Das vollständige
Protokoll mit Entwicklungsdaten liegt separat unter
`runtime/backtests/phase6-protocol-r2-20261008/` und ist **nicht im Git-Repository**.
Die originalen v3-/Retry-Artefakte bleiben ebenfalls separat erhalten.
`deploy/release.json` referenziert dieses historische lokale Paket. Deshalb
funktionieren dessen Paketbau-/Installationsbefehle aus einem frischen Klon
ohne die separat gesicherten Originaldateien nicht. Kein Dummy-Protokoll und
keine Ersatzdaten erzeugen, um diese Prüfungen zu umgehen.

Das Testfenster hat begonnen: alte Installer/Upgrade-/Retry-Anleitungen sind
historische Dokumentation. Die tatsächlichen Regeln, Kernquellen und ihre
Prüfsummen während der laufenden Sammlung nicht ändern.

## Als Nächstes

1. Sammlung bis zum geplanten Ende überwachen; Anbieter-Credits separat prüfen.
2. Konsistente SQLite-Sicherung erstellen und extern aufbewahren. Lokale
   VPS-Sicherungen ersetzen kein externes Backup; GitHub enthält diese Daten nicht.
3. Nach Sammelende mit dem passenden unveränderten R2-Protokoll auswerten:
   Datenabdeckung, Nettoergebnisse nach Kosten, offene Positionen und Verluste.
4. Über einen begrenzten Paper-Betrieb mit echten Marktdaten entscheiden und
   dessen Installation/Telegram/Last auf dem VPS gesondert prüfen.
5. Neue Einstiegsvarianten getrennt integrieren und vorab festgelegt testen.
   Daten, an denen Parameter ausgewählt wurden, gelten danach als Entwicklung,
   nicht als unabhängiger Bestätigungstest.

`REVIEWABLE_HOLDOUT` bedeutet prüfbare Evidenz, keine automatische Handelsfreigabe.
Wallet-Schlüssel, Signierung und echte Orderausführung sind nicht implementiert.
