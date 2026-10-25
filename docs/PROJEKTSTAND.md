# Projektstand am 16. Oktober 2026

Dieses Dokument trennt vorhandenen Code, lokale Tests und den vom Betreiber
bestätigten VPS-Betrieb. Der Bot führt keine echten Trades aus. Eine profitable
Strategie ist bisher nicht nachgewiesen.

## R2 abgeschlossen

Die R2-Sammlung endete planmässig am 16. Oktober 2026 um 03:06 Uhr. Die
vorab festgelegte Auswertung ergab **`INSUFFICIENT_EVIDENCE`**: alle
Datenqualitätsanforderungen erfüllt, aber **null Trades** in allen sechs
Läufen. Details, Prüfung und Entwicklungsanalyse:
**[R2-Ergebnis](R2-ERGEBNIS.md)**.

Kurzfassung der Ursachen: Die meisten aufgenommenen Coins waren zu klein;
die grossen lagen fast alle auf dem gesperrten PumpSwap; und die
Top-10-Konzentrationsregel war in keiner einzigen vollständigen Prüfung
bestehbar. Die R2-Daten gelten ab jetzt als Entwicklungsdaten.

Telegram-Monitor des Sammlers: am 16. Oktober abgeschaltet
(`systemctl disable --now memecoin-telegram.timer`); der Betreiber bestätigte
`disabled`. Die private Konfiguration mit dem Bot-Token bleibt für einen
späteren Paper-Monitor erhalten. Auf dem VPS wurde nichts gelöscht.

## Letzter Betriebsstand während R2


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

Erledigt: R2-Sammlung, finale Sicherung nach [NACH-R2-ENDE.md](NACH-R2-ENDE.md)
und Auswertung (Ergebnis in [R2-ERGEBNIS.md](R2-ERGEBNIS.md)).

1. Externe Kopien der finalen Datenbank bestätigen (PC und NAS), erst danach
   über Aufräumen auf dem VPS entscheiden.
2. VPS absichern: SSH-Anmeldung auf Schlüssel umstellen.
3. R3 nach dem [R3-Plan](R3-PLAN.md) umsetzen, auf Basis der Entwicklungsanalyse in
   [R2-ERGEBNIS.md](R2-ERGEBNIS.md) und der
   [Recherche vom 13. Oktober](RECHERCHE-2026-10-13.md): Vorfilter bei der
   Aufnahme, PumpSwap mit Gebührenstaffel, neue Konzentrationsmessung,
   realistische Kosten je Pool.
   Stand 16.10.: Stufen A bis C erledigt (Code mit Tests, Diagnose in
   [R3-STUFE-C-DIAGNOSE.md](R3-STUFE-C-DIAGNOSE.md)).
4. Blockierte Verkäufe aus Stufe C sind behoben (Rückgriff auf die letzte
   vollständige Prüfung). Als Nächstes: Probelauf des Sammlers mit Vorfilter
   (Stufe D, Anleitung in [R3-STUFE-D-ANLEITUNG.md](R3-STUFE-D-ANLEITUNG.md)),
   dann ein neues Protokoll mit zukünftigem Testfenster festlegen.
   Stand 20.10.: Stufe D mit D3 bestanden, Protokoll eingefroren
   ([R3-PROTOKOLL.md](R3-PROTOKOLL.md)), R3-Test seit 20.10. 22:01 Uhr auf
   dem VPS aktiv. Testfenster 21.10. 02:00 Uhr bis 28.10. 01:00 Uhr Schweizer
   Zeit (00:00 bis 00:00 UTC; am 25.10. Umstellung auf Winterzeit).
5. Erst danach über einen begrenzten Paper-Betrieb mit echten Marktdaten
   entscheiden. Anti-FOMO und Risikogrösse getrennt integrieren und testen.

`REVIEWABLE_HOLDOUT` bedeutet prüfbare Evidenz, keine automatische Handelsfreigabe.
Wallet-Schlüssel, Signierung und echte Orderausführung sind nicht implementiert.
