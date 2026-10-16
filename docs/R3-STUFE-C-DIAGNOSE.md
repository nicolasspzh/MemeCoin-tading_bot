# R3 Stufe C: Entwicklungsdiagnose auf den R2-Daten

Stand: 16.10.2026. Code: R3-Stand nach Commit `a68dde4` (Code-Fingerprint
`133e475d…`). Daten: R2-Testfenster, 233'199 Beobachtungen, 836 Coins.

**Wichtig vorweg:** Diese Diagnose ist kein Test. Die R2-Daten waren beim
Entwurf von R3 bekannt. Sie zeigt nur, ob der R3-Code überhaupt Einstiege
erzeugt und warum er sperrt. Gewinn oder Verlust auf diesen Daten sind kein
Kriterium und kein Grund, Regeln zu ändern.

## Vorgehen

1. `scripts/r3_stufe_c_rebuild.py` liest die R2-Datenbank nur lesend
   (`mode=ro&immutable=1`). Für jede Beobachtung mit gespeichertem Beleg
   (`risk_evidence`) baut es die Halter- und Poolprüfung mit dem R3-Code neu.
   Grundlage sind die damals gelesenen Kontodaten, unverändert. Bei PumpSwap
   kommt das Gebührenkonto aus dem Schnappschuss vom 08.09.
   (`tests/fixtures/pumpswap_fee_config_20260908.json`) dazu, weil R2 dieses
   Konto nicht gelesen hat. Der ursprüngliche Prüfzeitpunkt bleibt erhalten.
2. `scripts/r3_stufe_c_diagnose.py` zählt pro Beobachtung die Sperrgründe
   (`risk_reasons`) und spielt die sechs Szenarien durch (baseline und stress,
   Seeds 7, 17, 29), mit `scenario_definitions` aus dem R3-Code.

Einstellungen: genau die R2-Strategieparameter aus dem R2-Protokoll. Geändert
sind nur die in Stufe B beschlossenen Punkte: neue Felder mit ihren
Standardwerten und die erlaubte ungünstige Bewegung von 10 % auf 3 %.

Neu gebaut: 105'113 Beobachtungen aus 26'983 Belegen, ohne Fehler. Die
105'708 Beobachtungen mit `unsupported_pool` hatten in R2 keinen Beleg. Das
sind Pools anderer Programme (vor allem pump.fun-Bonding-Curve, Meteora). Sie
bleiben gesperrt, wie in R2.

Laufzeit der sechs Replays: 109 Sekunden, Speicherbedarf höchstens rund
4,9 GB.

## Ergebnis Einstiegsprüfungen

| | R2 | R3 |
| --- | ---: | ---: |
| Beobachtungen, die alle Einstiegsprüfungen bestehen | 0 | 2'753 |
| Coins mit mindestens einer solchen Beobachtung | 0 | 41 |

Alle 2'753 Beobachtungen stammen von PumpSwap-Pools. Raydium CPMM liefert
keine: Dort sperren vor allem Konzentration, Creator-Bestand und zu wenig
Liquidität.

Coins nach Pooltyp (laut DEX Screener):

| Pooltyp | Coins | Bestandene Beobachtungen |
| --- | ---: | ---: |
| pump.fun (Bonding Curve, nicht unterstützt) | 375 | 0 |
| PumpSwap | 286 | 2'753 |
| Raydium CPMM | 148 | 0 |
| Meteora DBC | 15 | 0 |
| Meteora DYN2 | 8 | 0 |
| ohne Paar | 5 | 0 |
| MetaDAO | 1 | 0 |
| Raydium CLMM | 1 | 0 |

Folgerung: 45 % der R2-Plätze gingen an Coins auf der Bonding Curve. Der
Vorfilter aus Stufe B nimmt solche Coins künftig nicht auf. Wie viele Coins
mit Vorfilter pro Stunde bestehen, lässt sich auf R2 nicht nachspielen. Das
klärt Stufe D.

### Wichtigste Sperrgründe (Beobachtungen, Mehrfachnennung)

| Grund | R2 | R3 |
| --- | ---: | ---: |
| `insufficient_or_unknown_volume` | 206'068 | 206'068 |
| `insufficient_or_unknown_liquidity` | 201'069 | 201'069 |
| `followup_only_no_new_entry` | 158'056 | 158'056 |
| `unsupported_pool_program` | 105'708 | 105'708 |
| `insufficient_onchain_liquidity` (neu) | gab es nicht | 78'047 |
| `pumpswap_dynamic_fees_unverified` | 72'037 | 0 |
| `unsupported_virtual_quote_reserves` | 71'732 | 0 |
| `high_top10_owner_concentration` | 62'941 | 62'941 |
| `unsupported_pool_fields` | 62'592 | 0 |
| `uncertain_top10_owner_concentration` | 42'172 | entfällt |
| `coarse_holder_sample` (neu) | gab es nicht | 32'123 |
| `high_creator_observed_balance` | 25'732 | 25'732 |
| `unsupported_pumpswap_mode` | 13'095 | 285 |
| `pool_fees_exceed_execution_assumption` | 4'597 | entfällt |
| `custom_pool_creator_fee` (neu) | gab es nicht | 3'105 |
| `pool_fee_above_limit` (neu) | gab es nicht | 578 |
| `pumpswap_boost_window` (neu) | gab es nicht | 89 |

Die PumpSwap-Sperren aus R2 sind weg, weil R3 diese Pools jetzt versteht. Neu
sperrt die on-chain gemessene Liquidität viele Beobachtungen. Das ist
gewollt: DEX Screener rechnet bei PumpSwap das virtuelle Guthaben mit.

Beobachtungen mit genau **einem** Sperrgrund:

| Einziger Grund | Beobachtungen |
| --- | ---: |
| `followup_only_no_new_entry` | 4'718 |
| `coarse_holder_sample` | 2'599 |
| `insufficient_or_unknown_volume` | 134 |
| `pair_age_outside_entry_window` | 92 |
| `high_top10_owner_concentration` | 14 |
| `insufficient_onchain_liquidity` | 13 |
| `pumpswap_boost_window` | 11 |

`coarse_holder_sample` ist damit die Regel, die am häufigsten allein einen
Einstieg verhindert. Ich lockere sie trotzdem nicht: Sie schützt davor, dass
ein grosses, nicht gesampeltes Konto die Konzentration verfälscht.

## Ergebnis Replay

| Szenario | Seed | Orders | ausgeführt | abgelehnt | fehlgeschlagen | geschlossene Trades | Coins mit Trades | offene Positionen |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 7 | 82 | 68 | 10 | 4 | 34 | 13 | 0 |
| baseline | 17 | 82 | 68 | 10 | 4 | 34 | 13 | 0 |
| baseline | 29 | 82 | 68 | 10 | 4 | 34 | 13 | 0 |
| stress | 7 | 84 | 64 | 9 | 11 | 32 | 13 | 0 |
| stress | 17 | 83 | 60 | 9 | 14 | 30 | 12 | 0 |
| stress | 29 | 83 | 58 | 10 | 15 | 29 | 13 | 0 |

R2 hatte in allen sechs Läufen 0 Orders.

Die drei Baseline-Läufe sind identisch. Ich habe nachgeprüft, ob das ein
Fehler ist: Die zufällige Ausfallziehung liegt bei allen 72 Ausführungen je
Seed über 2 % (kleinste Werte 0,0248, 0,0283 und 0,0282). Das ist Zufall, kein
Fehler. Die 4 Fehlschläge in Baseline sind alle `price_moved_beyond_limit`.

Verkaufssignale (Baseline, Seed 7, Gründe der Signale, nicht der
Ausführungen): 13× Trailing Stop, 10× Stop Loss mit Trailing Stop, 5× Take
Profit, 4× Zeitstopp, 1× Verkaufsdruck, 8× wegen fehlender Prüfdaten (3 davon
zusammen mit Stop Loss), 5× wegen sinkender Liquidität (4 davon zusammen mit
Stop Loss). Total 46 Signale.

Mit 34 Trades und 13 Coins liegt die Diagnose unter den Mindestwerten für eine
Auswertung (100 Trades, 20 Coins). Das R2-Fenster hatte aber nur 434 Coins
auf unterstützten Pools.

### Gewinn und Kosten, nur zur Einordnung

Alle sechs Läufe enden mit Verlust: baseline −10,68 USD von 50 USD, stress
−12,48 bis −15,07 USD. Das ist auf bekannten Entwicklungsdaten gemessen und
**kein** Urteil über die Strategie. Ich ändere deswegen keine Regel.

Zur Einordnung der Grössenordnung (Baseline, Seed 7): Die 34 Käufe hatten im
Schnitt 2,19 USD Volumen. Gebühren plus Slippage und Preiseinfluss betrugen
4,68 USD, das sind 6,3 % des gekauften Volumens. Die übrigen rund 6 USD des Verlusts
kommen aus Kursbewegungen und Gebühren fehlgeschlagener Orders. Der feste
Anteil (0,02 USD feste Gebühr plus 0,005 USD Priority Fee pro Seite) wiegt bei so kleinen
Positionen schwer. Ob die Positionsgrösse für R3 anders sein soll, ist eine
Entscheidung vor dem R3-Protokoll und darf nicht auf diesen Zahlen optimiert
werden.

## Befund zur Mechanik: blockierte Ausstiege

In jedem Lauf werden 7 bis 8 Verkaufsorders abgelehnt mit
`execution_risk:incomplete_onchain_checks,missing_verified_holder_risk`.
Ursache: In der Beobachtung zum Ausführungszeitpunkt fehlt eine vollständige
On-Chain-Prüfung (in R2 zum Beispiel nach einem RPC-Fehler). `execution.py`
zählt diese Gründe als „Mechanik unbekannt" und lässt dann auch den Verkauf
nicht zu.

Dazu kommt ein Widerspruch: 5 Verkaufssignale entstehen nur **wegen**
dieser fehlenden Daten (die Position soll raus, weil die Prüfung fehlt), und
derselbe Grund verhindert dann die Ausführung.

Auswirkung in Baseline, Seed 7: Vom ersten Verkaufssignal bis zum
ausgeführten Verkauf vergingen im Median 20 Sekunden. In 3 von 34 Fällen
waren es über 120 Sekunden, im längsten Fall 429 Sekunden. Die längste
Haltedauer lag bei 956 Sekunden, also über dem Zeitstopp von 900 Sekunden.

Das ist kein Gewinnthema, sondern eine Frage der Sicherheit: Ein Bot, der
wegen einer fehlenden Datenabfrage nicht verkaufen kann, bleibt in einem
fallenden Coin stecken. Mögliche Lösungen, noch nicht umgesetzt:

- Für den Verkauf die letzte vollständige Prüfung desselben Pools verwenden,
  wenn sie nicht zu alt ist.
- Fehlende Halterdaten beim Verkauf nicht als Sperre werten, nur unsichere
  Token-Mechanik (Freeze Authority, Token-2022-Erweiterungen) weiter sperren.
  Die Gebühr würde dann mit dem Höchstwert `max_pool_fee_bps` angesetzt.

Die Entscheidung gehört vor das R3-Protokoll (Stufe E).

## Grenzen

- Entwicklungsdaten, keine unabhängige Prüfung.
- Das Gebührenkonto stammt vom 08.09., nicht aus dem jeweiligen Zeitpunkt
  im R2-Fenster. Dass die Staffel bis dahin gleich blieb, ist eine Annahme.
  Stufe A führt diese Prüfung als offen.
- Der Vorfilter wirkt bei der Aufnahme. Er lässt sich auf den R2-Daten nicht
  nachspielen, weil R2 andere Coins aufgenommen hat.
- Der Sandwich-Aufschlag im Stress-Szenario fehlt noch (Stufe E).

## Nachrechnen

```
python scripts/r3_stufe_c_rebuild.py <R2-Datenbank> <ausgabe.pkl>
python scripts/r3_stufe_c_diagnose.py <ausgabe.pkl> <neuer Ausgabeordner>
```

Die R2-Datenbank ist nicht im Repository (rund 1,9 GB, SHA-256
`c270356b…`). Das zweite Skript braucht rund 5 GB Arbeitsspeicher.
