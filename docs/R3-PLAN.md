# R3-Plan: den Bot handlungsfähig machen

Stand: 16. Oktober 2026. Entwurf, noch nichts umgesetzt.

## Ziel

R2 hat gezeigt: Mit den heutigen Regeln kann der Bot praktisch nie handeln
(siehe [R2-ERGEBNIS.md](R2-ERGEBNIS.md)). R3 soll ihn **handlungsfähig**
machen, damit ein neuer Test überhaupt etwas über die Strategie aussagen kann.

R3 ist ausdrücklich **kein Versuch, Gewinn auf den R2-Daten zu erzeugen.**
Es behebt die drei Hürden aus R2 und macht die Kosten realistisch. Ob die
Strategie etwas taugt, zeigt erst ein neuer Test mit festem, zukünftigem
Fenster.

## Grundsätze

1. **Ein- und Ausstiegslogik bleibt unverändert** (`trading/strategy.py`):
   Momentum ab +1 %, Kaufdruck, Stop-Loss, Take-Profit, Trailing Stop,
   Zeitlimit. Sonst wüssten wir am Ende nicht, was gewirkt hat.
2. **Sicherheitssperren bleiben Sperren.** Unbekannte Mechanik, aktive
   Mint- oder Freeze-Rechte, gefährliche Token-2022-Erweiterungen und hohe
   Konzentration blockieren weiterhin. Geändert wird, **wie** gemessen wird,
   nicht dass gemessen wird.
3. **Keine Abstimmung auf Gewinn.** Die R2-Daten dienen nur dazu, zu prüfen,
   ob die neuen Prüfungen technisch funktionieren und ob überhaupt Einstiege
   möglich werden. Gewinnzahlen aus R2 sind kein Grund für Regeländerungen.
4. **Jede Änderung mit Tests.** Bestehende Tests bleiben gültig oder werden
   begründet angepasst.
5. **Auf dem VPS ändert sich nichts**, bis der R3-Test startet. Dann als
   neue Installation neben den alten Daten, nicht als Ersatz.

## Unverändert in R3

- Strategie, Positionsgrösse (5 %, höchstens 3 Positionen), 50 USD virtuelles
  Kapital, Gewinnverteilung, DEAD-Regel.
- Mint-, Freeze- und Token-2022-Prüfungen des Meme-Tokens.
- Mindestwerte für den Einstieg: 10'000 USD Liquidität, 1'000 USD Volumen in
  5 Minuten, Poolalter 60 Sekunden bis 24 Stunden.
- Creator-Anteil höchstens 10 %, nicht einlösbare LP mindestens 90 %.
- Auswertungsregeln: baseline und stress, Seeds 7, 17, 29, mindestens 100
  Trades in 20 Coins je Lauf.

## Änderungen

### 1. Vorfilter bei der Aufnahme

**Befund R2:** Die Aufnahme nach Entdeckungsreihenfolge füllte die 8 Plätze
mit kleinen oder nicht prüfbaren Coins. Nur 130 von 836 Coins waren in der
Anfangsphase gross genug. 48 Coins hatten eine fremde Gegenwährung.

**Geprüft am 16. Oktober:** Die Kursantwort von DEX Screener enthält bereits
`dexId`, `labels`, `quoteToken.address` und `liquidity.usd`. Diese Werte
stimmten in R2 mit dem on-chain geprüften Pool-Programm überein
(`raydium` + `CPMM` = Raydium CPMM, `pumpswap` = PumpSwap, `pumpfun` =
Bonding Curve).

**Umsetzung** (`collectors/schedule.py`, `main.py`):

- Vor der Aufnahme fragt der Sammler für wartende Kandidaten die Kurse ab
  (DEX Screener, bis 30 Tokens pro Anfrage, keine Blockchain-Abfrage).
- Aufgenommen wird nur, wer zu diesem Zeitpunkt alle Bedingungen erfüllt:
  - Pool-Typ Raydium CPMM oder PumpSwap
  - Gegenwährung wSOL oder USDC
  - Liquidität mindestens 10'000 USD
- Die Liquidität von DEX Screener dient nur der Vorauswahl. Bei PumpSwap
  überschätzt sie die echte Liquidität im Median um rund 50 %
  (siehe [Stufe A](R3-STUFE-A-PUMPSWAP.md)). Die Einstiegsprüfung misst die
  echte Liquidität on-chain.
- Unter den geeigneten Kandidaten gilt weiter die Entdeckungsreihenfolge.
  Es wird nur Wissen vom Aufnahmezeitpunkt verwendet, keine späteren Kurse.
- Abgelehnte Kandidaten werden mit Grund gespeichert, damit die Auswahl
  nachvollziehbar bleibt.

**Offen:** Wie viele geeignete Kandidaten es pro Stunde gibt, lässt sich aus
R2 nicht ablesen, weil zurückgestellte Kandidaten nie abgefragt wurden.
Davon hängt ab, ob 8 Plätze und 12 Minuten Aufnahmeabstand passen. Das wird
in einem kurzen Probelauf ohne Testcharakter gemessen. Die Abfragegrenzen
von DEX Screener sind vorher in deren Dokumentation zu prüfen.

### 2. PumpSwap unterstützen

**Befund R2:** 110 der 130 grossen Coins liefen über PumpSwap. Alle waren
gesperrt (`pumpswap_dynamic_fees_unverified`,
`unsupported_virtual_quote_reserves`, `unsupported_pool_fields`).

**Geprüft am 13. Oktober** (siehe [Recherche](RECHERCHE-2026-10-13.md)): Das
offizielle IDL hat zwei Felder mehr (`protocol_fees`, `creator_fees`, Byte
271 bis 286). Die Gebühren hängen bei kanonischen Pools von der
Marktkapitalisierung ab: 1,25 % bis 0,30 % pro Trade.

**Umsetzung** (`collectors/holders.py`):

- Pool-Layout nach dem aktuellen IDL vollständig lesen, mit Test gegen echte
  Kontodaten aus R2 (die Belege in `risk_evidence` enthalten die Rohbytes).
- Gebühr je Pool bestimmen: bevorzugt aus dem on-chain Gebührenkonto
  (`fee_config`), sonst aus der offiziellen Staffel mit
  Marktkapitalisierung = `priceNative` × 1 Milliarde. Quelle und Stand der
  Staffel werden im Code dokumentiert.
- Erst freigeben, wenn ein Feld verstanden ist. Bis dahin bleibt es eine Sperre.

**Stufe A erledigt am 16. Oktober**, Ergebnisse in
[R3-STUFE-A-PUMPSWAP.md](R3-STUFE-A-PUMPSWAP.md):

- `virtual_quote_reserves` ist Buchhaltung für wartende Gebühren und
  Boost-Reserven, keine Sperre nötig. Echte Liquidität = Tresor minus
  wartende Gebühren.
- Gebühren sind aus dem on-chain Gebührenkonto vollständig bestimmbar; es
  wird im selben Abfrageaufruf mitgelesen.
- Holder Rewards erlauben; Cashback, Mayhem und veränderbare Creator-Gebühr
  bleiben gesperrt.
- Neu: Bei PumpSwap erst ab 10 Minuten Poolalter einsteigen, wegen der
  Rückkäufe nach der Migration (BOOST).

### 3. Neue Konzentrationsmessung

**Befund R2:** In 0 von 105'115 vollständigen Prüfungen lag die Obergrenze
der Top-10-Konzentration bei höchstens 60 %. Die Regel war nicht bestehbar.

**Ursache:** Die Obergrenze rechnet alle nicht beobachteten Tokens den Top 10
zu. Die Abfrage liefert aber bereits die 20 grössten Konten. Jedes nicht
beobachtete Konto ist deshalb höchstens so gross wie das kleinste beobachtete.
In R2 lag dieses im Median bei 0,56 % der Menge ausserhalb des Pools
(P90: 1,65 %).

**Neue Regel** (`collectors/holders.py`, `trading/risk.py`):

- Top-10-Anteil der beobachteten Owner (bisherige Untergrenze) höchstens 60 %.
- Zusätzlich: Das kleinste beobachtete Konto hält höchstens 1 % der Menge
  ausserhalb des Pools. Sonst gilt die Stichprobe als zu grob, und der
  Einstieg bleibt gesperrt.
- Die bisherige Obergrenze wird weiter gespeichert und angezeigt, aber nicht
  mehr als Sperre verwendet.

Restrisiko: Eine Person kann ihre Tokens auf viele kleine Konten oder
verschiedene Wallets verteilen. Das erkennt weder die alte noch die neue
Regel. Dafür ist die Bundle- und Cluster-Erkennung gedacht (Punkt 6, nicht
Teil von R3).

Zur Information, nicht als Ziel: Auf den R2-Daten bestünden mit dieser Regel
13,8 % der PumpSwap-Prüfungen (71 Coins) und 0,8 % der Raydium-CPMM-Prüfungen
(1 Coin). Die Grenze von 1 % wurde nach Ansicht dieser Daten gewählt. Ob sie
trägt, zeigt erst der neue Test.

### 4. Realistische Kosten je Pool

**Befund:** Das Modell rechnet fix mit 0,3 % Gebühr. PumpSwap kostet bei
kleinen Coins bis 1,25 % pro Trade. Raydium-Pools mit mehr als 0,3 % wurden
bisher ganz gesperrt.

**Umsetzung** (`trading/execution.py`, `trading/paper_wallet.py`, `trading/risk.py`):

- Gebühr je Trade aus dem geprüften Pool (`known_fee_bps`) statt fix 0,3 %.
- Sperre nur noch bei unbekannter Gebühr oder bei mehr als 2 % pro Trade.
- Höchstens 3 % ungünstige Kursbewegung bis zur Ausführung, sonst gilt der
  Trade als fehlgeschlagen. Bisher 10 %. Die Recherche nennt hohe
  Slippage-Toleranz als Hauptziel von Sandwich-Angriffen. Das stammt nur aus
  Zweitquellen; der Bitquery-Bericht ist noch zu lesen.
- Stress-Szenario zusätzlich mit einem Sandwich-Aufschlag. Die Höhe wird vor
  dem Test festgelegt und dokumentiert, nicht nach Ergebnissen gewählt.

### 5. Coins ohne prüfbare Gegenwährung früh sperren

Erledigt durch den Vorfilter (Punkt 1). Zusätzlich prüft die Pool-Prüfung
die Gegenwährung vor den Tresoren, damit ein solcher Fall als klare Sperre
`unsupported_quote_mint` erscheint und nicht als Datenfehler.

### Optional: sparsamere Auswertung

Die Auswertung brauchte mindestens 11,4 GB Arbeitsspeicher. Da R3 ohnehin
einen neuen Fingerprint bekommt, darf sie umgebaut werden, zum Beispiel mit
schlankeren Zwischenobjekten. Bedingung: Auf den R2-Daten muss sie dasselbe
Ergebnis liefern wie die eingefrorene Version.

## Nicht Teil von R3

6. Bundle- und Cluster-Erkennung (Recherche Fund 7). Wichtig, aber eigenes
   Projekt mit zusätzlichen RPC-Kosten.
7. Pump.fun Bonding Curve, Meteora, Raydium LaunchLab und CLMM.
8. Anti-FOMO und Risikogrösse.
9. Echtgeld, Wallet, Signierung.

## Umsetzungsstand

Mit dem ersten R3-Code ändert sich der Code-Fingerprint. Das R2-Protokoll
lässt sich auf diesem Stand nicht mehr laden. Das ist gewollt. Wer R2
nachrechnen will, verwendet den eingefrorenen Code unter
`uebergabe/2026-10-12/Projekt/` oder Git-Commit `84efd66`.

| Punkt | Stand | Prüfung |
| --- | --- | --- |
| 3. Konzentrationsmessung | umgesetzt am 16.10. (`trading/risk.py`, Einstellung `max_unobserved_account_fraction`) | 3 neue Tests; R2-Zählung: 72 Coins bestehen (71 PumpSwap, 1 Raydium CPMM), vorher 0 |
| 2. PumpSwap | umgesetzt am 16.10. (`collectors/holders.py`, `trading/risk.py`, Einstellung `min_pumpswap_age_seconds`) | 18 neue Tests in `tests/test_pumpswap.py`, u. a. PDA-Vergleich mit solders 0.26.0 und echtes Gebührenkonto vom 08.09. |
| 4. Kosten je Pool | offen | |
| 1. Vorfilter | offen | |
| 5. Gegenwährung früh | offen | |

Umgesetzte Konzentrationsregel: bestanden, wenn die konservative Obergrenze
höchstens 60 % beträgt. Sonst bestanden, wenn der beobachtete Top-10-Anteil
höchstens 60 % beträgt **und** kein unbeobachtetes Konto mehr als 1 % halten
kann. Neue Sperrgründe: `coarse_holder_sample`,
`unknown_unobserved_account_size`. `uncertain_top10_owner_concentration`
entfällt.

Umgesetzt für PumpSwap: aktuelles Pool-Layout (287 Bytes, Zusatzbytes müssen
0 sein), `virtual_quote_reserves` mit Vorzeichen, echte Reserven nach
wartenden Gebühren, Erkennung kanonischer Pools über die PDA
`["pool-authority", mint]`, Gebühr aus dem Gebührenkonto (im selben
`getMultipleAccounts`-Aufruf), Holder Rewards erlaubt, Mayhem, Cashback,
reservierte Felder und eigene Creator-Gebühr gesperrt. Neu für alle
vollständig geprüften Pools: Liquidität on-chain aus der Quote-Reserve
(`insufficient_onchain_liquidity`, `unknown_onchain_liquidity`). Neu für
PumpSwap: Einstieg erst ab 10 Minuten Poolalter (`pumpswap_boost_window`).

Bewusst noch gesperrt: PumpSwap-Pools mit Gebühr über 0,3 % scheitern an
`pool_fees_exceed_execution_assumption`, bis Punkt 4 die Gebühr je Pool in
die Kosten übernimmt.

## Ablauf und Erfolgsbedingungen

| Stufe | Inhalt | Weiter, wenn |
| --- | --- | --- |
| A | Offene Fragen zu PumpSwap klären (Punkt 2) | Jedes freigegebene Feld ist belegt verstanden |
| B | Änderungen 1 bis 5 umsetzen, je mit Tests | Alle Tests bestehen |
| C | Entwicklungsdiagnose auf den R2-Daten mit dem R3-Code | Es entstehen überhaupt Einstiege; Gründe für Sperren sind nachvollziehbar |
| D | Kurzer Probelauf des Sammlers mit Vorfilter, ohne Testcharakter | Genug geeignete Kandidaten pro Stunde; RPC- und DEX-Limits eingehalten |
| E | Neues Protokoll mit zukünftigem 7-Tage-Fenster, Installation auf dem VPS neben R2 | Protokoll vor Beginn eingefroren |
| F | R3-Test sammeln und auswerten | `REVIEWABLE_HOLDOUT` und Gewinn nach Kosten auch im Stress-Szenario |

Erst nach Stufe F entscheiden wir über einen Paper-Betrieb mit echten
Marktdaten. Echtgeld steht erst danach und nur nach ausdrücklicher Freigabe
zur Diskussion.

In Stufe C gilt: Es wird gezählt, wie viele Einstiege möglich werden und
woran die übrigen scheitern. Gewinn oder Verlust auf R2 sind kein Kriterium.
Selbst wenn die Diagnose Gewinne zeigt, beweist das nichts, weil diese Daten
beim Entwurf bekannt waren.
