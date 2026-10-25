# R3-Protokoll: eingefroren am 20.10.2026

Datei: `protocols/r3-20261021/protocol.json`, Fingerprint
`6175b5577d9216c1870810dafdbc96bbc8399fec578fccb47525c23dc3b84c84`.
Code-Fingerprint: `2e8b8c2bd50a2de684c3c3bdfadfb9f44863d62905ff2b4f1d42860ae7532373`.
Erstellt mit `scripts/prepare_r3_protocol.py`.

## Testfenster

- Start: 21.10.2026, 00:00 UTC (02:00 Uhr Schweizer Zeit)
- Ende: 28.10.2026, 00:00 UTC (01:00 Uhr Schweizer Zeit; am 25.10. gilt
  wieder Winterzeit), 7 Tage
- Sammelende mit Nachbeobachtung: 28.10.2026, 01:06 UTC (02:06 Uhr Schweizer Zeit)
- Der Sammler startet schon bei der Installation. Beobachtungen vor dem
  Start zählen nicht (Vorlauf).

## Entwicklungsdaten

Alles, was beim Entwurf von R3 bekannt war, ist mit Prüfsumme, Zeilenzahl
und Zeitraum im Protokoll gebunden. Die Daten selbst liegen ausserhalb
(Protokoll Version 2), weil die R2-Datenbank zu gross ist:

| Name | Zeitraum (UTC) | Zeilen | Ort |
| --- | --- | ---: | --- |
| r2-final | 08.10. 14:58 bis 16.10. 01:05 | 244'693 | Datenbank-Datei, Kopien PC, NAS, Google Drive |
| probe-d1 | 17.10. 08:07 bis 16:07 | 5'713 | Bericht im Repository, Daten auf dem VPS |
| supply-sampler | 17.10. 16:12 bis 19:11 | 2'140 Zeilen Log | `uebergabe/2026-10-17/supply-sampler-log.jsonl` |
| probe-d2 | 18.10. 07:40 bis 15:05 | 7'582 | Bericht im Repository, Daten auf dem VPS |
| cloud-dry-runs | 16.10. bis 19.10., zusammen 73 Zeilen | 73 | `uebergabe/2026-10-20/cloud-dry-runs.json` |
| probe-d3 | 19.10. 18:13 bis 20.10. 18:13 | 28'570 | Bericht im Repository, Daten auf dem VPS |

Ende der Entwicklungsdaten: 20.10. 18:13:54 UTC. Das Testfenster beginnt
mehr als eine Stunde danach (Sperrfrist).

Bei den Probeläufen ist der Hash der übermittelte Bericht, nicht die
Datenbank auf dem VPS. Die Datenbanken habe ich nie gesehen, nur die
Berichte.

## Regeln, die gegenüber R2 neu sind

Alle in den Stufen B bis D begründet und vor dem Test festgelegt:

- Vorfilter bei der Aufnahme: Raydium CPMM oder PumpSwap, wSOL oder USDC,
  Kurs, mindestens 10'000 USD Liquidität, Pool höchstens 24 Stunden alt.
- PumpSwap mit Gebühr aus dem Gebührenkonto, echter Liquidität und
  Einstieg erst ab 10 Minuten Poolalter.
- Konzentration: beobachteter Top-10-Anteil höchstens 60 % und kein
  unbeobachtetes Konto über 1 %.
- Gemessene Poolgebühr je Trade, Sperre über 2 %.
- Verkauf darf auf die letzte vollständige Pool-Prüfung zurückgreifen,
  höchstens 900 Sekunden alt.
- Erlaubte ungünstige Kursbewegung bis zur Ausführung: Kauf 3 %,
  Verkauf 10 % (Stress: Kauf 3 %, Verkauf 5 %).
- Stress-Szenario zusätzlich mit 0,5 % Sandwich-Aufschlag pro Kauf. Die
  Höhe ist eine vorsichtige Annahme ohne verlässliche Quelle.

Unverändert gegenüber R2: Strategie (Ein- und Ausstieg), Positionsgrösse
5 %, höchstens 3 Positionen, 50 USD Startkapital, Auswertungsregeln
(baseline und stress, Seeds 7, 17, 29, mindestens 100 Trades auf 20 Coins
je Lauf), Sammeltakt (8 Plätze, ein neuer Coin höchstens alle 12 Minuten).

## Betrieb

- Dienst `memecoin-collector-r3`, Code `/opt/memecoin-collector-r3`,
  Daten `/var/lib/memecoin-collector-r3/campaign-r3`.
- Startet nach einem Neustart des VPS von selbst und setzt fort.
- Speichergrenzen 1 GB (weich) und 1,5 GB (hart). Sammler und Aufseher
  schreiben ihren Höchstwert in `state.json`.
- Ausfälle bis insgesamt 24 Stunden machen den Test nicht ungültig. Mehr
  als 24 Stunden Ausfall: Der Test wird nicht bewertet. Diese Regel steht
  in diesem Dokument, nicht in der Protokoll-Datei; sie gilt trotzdem und
  wurde vor dem Teststart festgelegt.

## Was danach passiert

Erst nach dem 28.10. 01:06 UTC wird die Datenbank kopiert und mit
`backtesting.evaluation evaluate` gegen dieses Protokoll ausgewertet. Vorher
wird kein Gewinn angeschaut. Der Statusbericht während des Tests zeigt nur
Datenabdeckung und Technik, keine Kurse oder Ergebnisse.
