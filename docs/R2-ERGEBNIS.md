# R2: Ergebnis und Entwicklungsanalyse

Stand: 16. Oktober 2026. Dieses Dokument enthält nur zusammengefasste Zahlen.
Die Beobachtungsdatenbank und die Ergebnisdateien liegen nicht im Repository.

## Ergebnis der vorab festgelegten Auswertung

**Status: `INSUFFICIENT_EVIDENCE`.** Blocker: `too_few_closed_trades` und
`too_few_distinct_traded_tokens`. In allen sechs Läufen (baseline und stress,
Seeds 7, 17, 29) gab es **null Orders und null Trades**; jede der 233'199
Entscheidungen war `SKIP`. Das virtuelle Kapital blieb bei 50 USD.

Null Trades sind fehlende Evidenz, kein Nullergebnis. Die Auswertung sagt
nichts darüber, ob die Strategie Geld verdient oder verliert.

| Herkunft | Wert |
| --- | --- |
| Art | `PROSPECTIVE_WINDOW_EVALUATION`, erstellt 16.10.2026 15:51 UTC |
| Protokoll | `a3069969150f38ea8739e55f929b5fffcd819867bee6dbf238ccf9f0e44396f9` |
| Code-Fingerprint | `8dcc53e9b17e18bfa1d5c2ac10facbd0bc1cc8b75dea61064c55589f29a5b9bd` |
| Eingabe | 244'693 Beobachtungen, Fingerabdruck `c45a38049b11ca019f40db4aa07e6bf2c9e40736a6915028eb7adb31bdd9de8c` |
| Ausgeschlossen | 10'587 vor dem Fenster, 904 danach, 3 mit Risikodaten nach Fensterende |
| Im Fenster | 233'199 Beobachtungen zu 836 Coins |
| Datenbank | `observations-final.sqlite3`, 1'945'731'072 Bytes, SHA-256 `c270356bf1cdb20b1bd6912be8f639f345b22e489b08a97aa1f0d0ebe7b3d763` |

Prüfung durch Claude Code am 16. Oktober: `result.json` gelesen; die
Datenbank aus Google Drive geladen (als gzip übertragen, entpackt),
Integrität ok, 0 Orders, 0 Fills, keine `api-key=`-Zeichenfolge. Der neu
berechnete Fingerabdruck der Beobachtungen stimmt mit dem Wert in
`result.json` überein.

### Datenqualität: alle Anforderungen erfüllt

| Anforderung | Schwelle | R2 |
| --- | --- | --- |
| Beobachtete Tage | mind. 3 | 7 |
| Aktive 5-Minuten-Abschnitte | mind. 80 % | 99,95 % |
| Anteil mit Kurs | mind. 95 % | 98,83 % |
| Aktuelle Risikodaten | mind. 95 % | 100,00 % |
| Lange Lücken desselben Pools | höchstens 10 % | 0,05 % |
| Paare mit Folgekursen | mind. 30 | 806 |
| Vollständige Halterprüfungen mit Kontobeleg | alle | 105'113 von 105'113 |
| Geschlossene Trades je Lauf | mind. 100 | **0** |
| Coins mit Trades je Lauf | mind. 20 | **0** |

### Betrieb

- Laufzeit der Auswertung knapp 10 Minuten in einer Claude-Code-Cloud-Sitzung.
- Arbeitsspeicher mindestens 11,4 GB (alle 15 Sekunden gemessen). Die
  Schätzung in `NACH-R2-ENDE.md` lag mit 6 bis 7 GB zu tief.

## Entwicklungsanalyse: warum keine Trades

Ab jetzt sind die R2-Daten **Entwicklungsdaten**. Regeln, die daraufhin
geändert werden, brauchen ein neues, vorher festgelegtes Testfenster.

Methode: Jede Beobachtung im Fenster wurde mit den unveränderten
Einstiegsprüfungen (`trading/risk.py`, Basisparameter des Protokolls) zum
Zeitpunkt ihrer Verfügbarkeit geprüft, wie in der Auswertung. Keine
Gewinnrechnung, nur lesender Zugriff.

### 1. Kein Fall scheiterte an nur einem Filter

- 158'056 Beobachtungen (68 %) waren Nachbeobachtung; dort sind Einstiege
  verboten. 75'143 lagen in der Anfangsphase.
- Selbst ohne den Nachbeobachtungsgrund hat **jede** Beobachtung mindestens
  zwei Blocker. Keine einzige scheiterte nur an Liquidität und Volumen.
- Auch in der Nachbeobachtung hätte keine Beobachtung alle übrigen Filter
  bestanden. Ein späterer Einstiegszeitpunkt hätte also nichts geändert.

### 2. Die meisten Coins sind zu klein, die grossen sind früh gross

- 155 von 836 Coins erreichten irgendwann 10'000 USD Liquidität, 276 einmal
  1'000 USD Volumen in 5 Minuten, 142 beides in derselben Beobachtung.
- Wer gross war, war es meist schon bei der Aufnahme (Median 0 Minuten,
  147 von 155 in der Anfangsphase). Die 30 Minuten Anfangsbeobachtung sind
  nicht das Problem.

### 3. Pool-Typen: der unterstützte Typ hatte keine grossen Coins

Häufigster Pool-Typ je Coin:

| Pool-Typ | Coins |
| --- | ---: |
| Pump.fun Bonding Curve | 352 |
| PumpSwap | 255 |
| Raydium CPMM | 117 |
| Mint geprüft, keine Halterprüfung | 64 |
| keine Risikodaten | 30 |
| Meteora DBC (vermutlich) | 10 |
| Meteora DAMM v2 (vermutlich) | 7 |
| Raydium CLMM (vermutlich) | 1 |

In der Anfangsphase hatten 130 Coins genug Liquidität und Volumen. Davon
liefen **110 über PumpSwap, keiner über Raydium CPMM**. Raydium CPMM ist der
einzige Pool-Typ, den die Regeln voll unterstützen. PumpSwap ist gesperrt
(`pumpswap_dynamic_fees_unverified`, `unsupported_virtual_quote_reserves`,
`unsupported_pool_fields`; siehe [Recherche](RECHERCHE-2026-10-13.md)).

### 4. Die Konzentrationsregel ist praktisch nicht bestehbar

In **0 von 105'115** vollständigen Halterprüfungen (372 Coins, Raydium CPMM
und PumpSwap) lag die Obergrenze der Top-10-Konzentration bei höchstens 60 %.
Diese Zählung filtert nur nach Empfangszeit; die Auswertung zählt 105'113,
vermutlich weil sie zusätzlich Beobachtungen mit erst nach Fensterende
verfügbaren Risikodaten ausschliesst.

| Kennzahl | P10 | Median | P90 |
| --- | ---: | ---: | ---: |
| Untergrenze Top-10-Anteil | 24,1 % | 78,8 % | 100 % |
| Obergrenze Top-10-Anteil | 80,9 % | 91,4 % | 100 % |
| Nicht beobachteter Anteil der Menge | 0 % | 10,7 % | 62,9 % |

Grund (aus dem Code, `collectors/holders.py`): Die Prüfung sieht nur die
bis zu 20 grössten Konten. Für die Obergrenze wird die ganze nicht
beobachtete Menge den zehn grössten Haltern zugerechnet. Damit die
Obergrenze 60 % nicht übersteigt, müssten die Plätze 11 bis 20 fast so viel
halten wie die Top 10 und darüber hinaus kaum etwas übrig bleiben. Das
kommt in echten Coins praktisch nicht vor. Die Untergrenze lag bei 42'174
Prüfungen bei höchstens 60 %; dort ist die Konzentration also möglicherweise
akzeptabel, aber nicht belegt.

Auch mit PumpSwap-Unterstützung und realistischen Gebühren hätte diese
Regel allein jeden Einstieg verhindert.

### 5. Fremde Gegenwährungen

48 Coins hatten eine Gegenwährung ausser wSOL/USDC oder einen
Tresorfehler wegen Token-2022-Erweiterungen (Transfer Hook, Pausable).
Sie machten 13'858 Beobachtungen aus (5,9 %) und belegten Beobachtungsplätze,
ohne je handelbar zu sein.

## Folgerungen

Diese Folgerungen sind Einschätzungen aus den Entwicklungsdaten, nicht getestet.

1. **Auswahl und Regeln passen nicht zusammen.** Die Aufnahme nach
   Entdeckungsreihenfolge füllt die 8 Plätze mit kleinen, nicht prüfbaren
   Coins. Die wenigen grossen Coins liegen fast alle auf PumpSwap.
2. **Drei Hürden blockieren unabhängig voneinander:** Grösse, Pool-Typ und
   Konzentrationsregel. Eine allein zu ändern bringt keine Trades.
3. **Die Konzentrationsregel misst nicht, was sie soll.** Sie bestraft vor
   allem fehlende Sicht auf kleinere Halter. Eine neue Messung braucht
   eigenes Design, zum Beispiel mehr beobachtete Konten oder eine getrennte
   Grenze für den unbekannten Anteil. Sie darf nicht einfach gelockert werden.
4. **Kosten realistisch machen, bevor Regeln geöffnet werden:** PumpSwap
   kostet bei kleinen Coins bis 1,25 % pro Trade statt der modellierten 0,3 %.

## Nächste Schritte

1. R3 bewusst entwerfen: Vorfilter bei der Aufnahme (aktuelle Liquidität,
   Gegenwährung wSOL/USDC, unterstützter Pool-Typ), PumpSwap-Unterstützung
   mit Gebührenstaffel, neue Konzentrationsmessung, realistische Kosten.
2. Jede Änderung zuerst mit Tests und auf diesen Entwicklungsdaten prüfen,
   dann ein neues Protokoll mit zukünftigem Testfenster festlegen.
3. Echtgeld bleibt ausgeschlossen.
