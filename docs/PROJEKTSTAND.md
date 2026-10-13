# Projektstand am 13. Oktober 2026

Dieses Dokument trennt vorhandenen Code, lokale Tests und den vom Betreiber
bestätigten VPS-Betrieb. Der Bot führt keine echten Trades aus. Eine profitable
Strategie ist bisher nicht nachgewiesen.

## Auf dem VPS bestätigt

Quelle: vom Betreiber bereitgestellte Statusausgabe vom **12. Oktober 2026,
16:12:32 Uhr Europe/Zurich**. Das ist ein gespeicherter Stand, keine Live-Anzeige.

| Merkmal | 12. Oktober, 16:12 | Zum Vergleich: 10. Oktober, 16:23 |
| --- | --- | --- |
| Sammler | R2 aktiv, Lebenszeichen vor 6 Sekunden | aktiv |
| Beobachtungen | 129'194 | 63'773 |
| Coins mit Beobachtungen | 467 | 232 |
| Beobachtungen mit Kurs | 127'180, rund 98,4 % | 62'765, rund 98,4 % |
| Stundenfolgekurse | 39'734 / 39'736 bereits fällige Werte | 19'489 / 19'491 |
| Beobachtungsgruppen | 2 Anfangsphase, 6 Nachbeobachtung, 463 abgeschlossen | 2 / 6 / 225 |
| Orders / Ausführungen | 0 / 0 | 0 / 0 |
| RPC-Versuche heute (UTC) / gesamt | 16'969 / 70'000; 116'805 / 600'000 | 18'131; 57'698 |
| Letzte Sicherung | 12. Oktober 15:47:18, Integrität ok | 10. Oktober 16:08:29, ok |
| Freier Speicher | 51,8 GiB | 53,2 GiB |

Weitere Angaben des Betreibers:

- Helius-Dashboard am 13. Oktober: 212'398 von 1'000'000 Credits verbraucht.
  RPC-Versuche und Credits sind verschiedene Einheiten.
- Der Telegram-Tagesbericht vom 12. Oktober ist angekommen.
- Installierter Code geprüft: `sha256sum --check SHA256SUMS` in
  `/opt/memecoin-collector-r2` ohne Abweichung; die Datei `SHA256SUMS` selbst
  hat `eb461cd1fb11d7c3b1fb996545290f71ef4cd5a4a9fc0873a6fb540a8e65453d` und
  entspricht damit dem Originalpaket v3. Dessen 71 Code- und Dienstdateien
  sind byte-identisch mit diesem Repository.

`data_degraded=true` bleibt sichtbar. Das Flag beschreibt nur den letzten
Sammelzyklus; ein einmaliger Discovery-Fehler hält es zudem bis zum nächsten
Worker-Neustart gesetzt. Die Logauswertung vom 12. Oktober (letzte 2'000
Zeilen) zeigte vor allem abgebrochene Risikoprüfungen wegen nicht
unterstützter Token-2022-Erweiterungen an Pool-Tresoren, fehlende DEX-Kurse
und wiederholte Discovery-Transaktionen. Diese Fälle sperren Einstiege wie
vorgesehen. Seltener waren kurzzeitig gesperrte RPC-Endpunkte
(`getMultipleAccounts`). Nahezu vollständige Folgekurse aufgenommener Coins
sind keine vollständige Marktabdeckung.

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

Diese Hashes dokumentieren Zuordnungen, keine Profitabilität. Seit dem
12. Oktober liegen das vollständige Protokoll und die eingefrorenen
Entwicklungsdaten im Repository unter `uebergabe/2026-10-12/R2-Referenz/`,
das v3-Archiv und das Retry-Skript unter `uebergabe/2026-10-12/Historische-Pakete/`.
Auf dem VPS liegt dasselbe Protokoll unter
`/opt/memecoin-collector-r2/runtime/backtests/phase6-protocol-r2-20261008/`.
`deploy/release.json` verweist weiterhin auf diesen historischen `runtime/`-Pfad.
Paketbau- und Installationsbefehle sind kein aktueller Weg. Kein
Dummy-Protokoll und keine Ersatzdaten erzeugen, um Prüfungen zu umgehen.

Das Testfenster hat begonnen: alte Installer/Upgrade-/Retry-Anleitungen sind
historische Dokumentation. Die tatsächlichen Regeln, Kernquellen und ihre
Prüfsummen während der laufenden Sammlung nicht ändern.

## Als Nächstes

1. Sammlung bis zum geplanten Ende überwachen; Anbieter-Credits separat prüfen.
2. Nach dem Ende genau nach [NACH-R2-ENDE.md](NACH-R2-ENDE.md) vorgehen:
   Ende prüfen, geprüfte finale Kopie erstellen, auf den PC holen und extern
   aufbewahren. GitHub enthält diese Daten nicht.
3. Mit dem passenden unveränderten R2-Protokoll auswerten, in einer
   Claude-Code-Cloud-Sitzung oder auf dem PC, nicht auf VPS oder NAS, weil die
   Auswertung voraussichtlich mehrere GB Arbeitsspeicher braucht: Datenabdeckung, Nettoergebnisse nach Kosten, offene Positionen und Verluste.
4. Über einen begrenzten Paper-Betrieb mit echten Marktdaten entscheiden und
   dessen Installation/Telegram/Last auf dem VPS gesondert prüfen.
5. Neue Einstiegsvarianten getrennt integrieren und vorab festgelegt testen.
   Daten, an denen Parameter ausgewählt wurden, gelten danach als Entwicklung,
   nicht als unabhängiger Bestätigungstest.
6. Ideen aus der [Recherche vom 13. Oktober](RECHERCHE-2026-10-13.md) prüfen,
   vor allem realistische Gebühren je Pool (PumpSwap bis 1,25 % pro Trade statt
   der modellierten 0,3 %) und eine frühe Sperre fremder Gegenwährungen.
   Erst nach der R2-Auswertung und mit neuem Protokoll.

`REVIEWABLE_HOLDOUT` bedeutet prüfbare Evidenz, keine automatische Handelsfreigabe.
Wallet-Schlüssel, Signierung und echte Orderausführung sind nicht implementiert.
