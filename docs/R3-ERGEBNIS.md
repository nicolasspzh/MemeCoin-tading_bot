# R3: Ergebnis des 7-Tage-Tests

Ausgewertet am 30.10.2026 gegen das eingefrorene Protokoll
([R3-PROTOKOLL.md](R3-PROTOKOLL.md)). Zusammenfassung ohne Rohdaten:
`uebergabe/2026-10-30/r3-ergebnis-zusammenfassung.json`.

## Herkunft und Prüfung

- Datenbank vom VPS, finale Kopie vom 30.10.: 186'490 Beobachtungen,
  Integrität ok, 0 Orders, SHA-256 `239fa1b3…`. Über Google Drive als
  `.gz` übertragen (`fe10b2a0…`), nach dem Entpacken wieder `239fa1b3…`.
  Keine Zugangsdaten enthalten.
- Kerncode `2e8b8c2…` wie im Protokoll, 397 Tests bestanden, Protokoll
  `6175b557…` geladen.
- Im Fenster: 180'840 Beobachtungen; ausgeschlossen 4'720 vor dem Start
  (Vorlauf) und 930 nach dem Ende.
- Der erste Lauf von `backtesting.evaluation evaluate` brach nach den
  sechs Durchläufen ab: Beim erneuten Einlesen der eingefrorenen Kopie für
  ihre Prüfsumme war der Arbeitsspeicher (15 GB) voll. Die Auswertung lief
  danach mit `scripts/evaluate_low_memory.py`: dieselben eingefrorenen
  Funktionen in derselben Reihenfolge, nur mit freigegebenem Speicher vor
  diesem letzten Schritt. Höchstwert 9,0 GB.

## Status: REVIEWABLE_HOLDOUT

Alle Qualitäts- und Mengenanforderungen sind erfüllt: Datenqualität ohne
Hindernis (99,5 % der 5-Minuten-Abschnitte aktiv, 100 % mit Kurs und mit
aktueller Risikoprüfung), mindestens 100 Trades auf mindestens 20 Coins in
jedem Lauf, keine offenen Positionen. Der Test ist damit **auswertbar**.
Bei R2 war das wegen null Trades nicht der Fall.

## Ergebnis: Verlust in allen sechs Läufen

Startkapital je Lauf 50 USD.

| Szenario | Seed | Trades | Coins | Netto realisiert | Gewinnquote | Profit-Faktor | Gebühren | Slippage und Preiseinfluss | Status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| baseline | 7 | 347 | 86 | −39,66 USD | 26,8 % | 0,41 | 25,81 | 8,08 | DEAD |
| baseline | 17 | 349 | 87 | −39,77 USD | 26,6 % | 0,40 | 26,06 | 8,20 | DEAD |
| baseline | 29 | 358 | 89 | −39,43 USD | 27,1 % | 0,42 | 26,54 | 8,24 | DEAD |
| stress | 7 | 190 | 50 | −43,54 USD | 19,5 % | 0,16 | 27,16 | 13,57 | DEAD |
| stress | 17 | 175 | 45 | −43,78 USD | 17,7 % | 0,13 | 24,95 | 12,34 | DEAD |
| stress | 29 | 181 | 46 | −43,71 USD | 17,1 % | 0,14 | 25,70 | 12,43 | DEAD |

`DEAD` heisst: Das Handelskapital fiel unter 5 USD, danach gab es keine
neuen Einstiege mehr. In baseline (Seed 7) war der letzte Kauf am 25.10.,
im Stress-Szenario am 23.10.

**Die Strategie ist in dieser Form nicht profitabel.** Das ist das
vorher festgelegte Urteil über ein unabhängiges, zukünftiges Fenster.

## Woran es liegt (Analyse nach dem Test, keine neue Regel)

Gemessen in baseline, Seed 7:

- **Kosten:** Gebühren 25,81 USD plus Slippage und Preiseinfluss 8,08 USD,
  zusammen 33,89 USD. Vor diesen Kosten lag das Ergebnis bei rund
  −5,52 USD (Stress: rund −1,12 USD). Die Kosten machen also den grössten
  Teil des Verlusts aus.
- **Kleine Positionen:** Gekauft wird mit 5 % des Kapitals. Der
  Durchschnitt lag bei 1,18 USD pro Kauf, die ersten fünf Käufe bei
  2,44 USD, die letzten fünf bei 0,23 USD. Die festen Kosten von 0,025 USD
  pro Seite (Netzwerkgebühr und Priority Fee) wiegen bei so kleinen
  Beträgen sehr schwer und werden mit sinkendem Kapital immer schwerer.
- **Kein Vorteil vor Kosten:** Auch ohne Kosten bleibt ein leichter
  Verlust. Die Einstiegsregel (Momentum) bringt also keinen erkennbaren
  Vorsprung.
- **Ausstiege:** Die häufigsten Verkaufsgründe waren Trailing Stop (256),
  Stop Loss (138) und Take Profit (74). Die Gewinnquote liegt bei rund
  27 %.

Das sind Beobachtungen auf den Testdaten. Sie dürfen nicht dazu dienen,
Regeln auf genau diese Daten anzupassen. Eine neue Idee braucht ein neues
Protokoll und ein neues, zukünftiges Testfenster.

## Was das für den Echtgeld-Handel heisst

Keine Freigabe. Die Auswertung erteilt nie eine Freigabe
(`live_trading_approved: false`), und hier ist das Ergebnis zudem klar
negativ.

## Grenzen

- Ein Zeitraum von 7 Tagen. Die Seeds variieren nur Kosten und Ausfälle
  derselben Marktdaten und sind keine unabhängigen Stichproben.
- Kosten, Slippage, Preiseinfluss und Ausfälle sind Modellannahmen.
- Coins können stark korreliert sein; 86 Coins sind keine 86 unabhängigen
  Versuche.
