# R3 Stufe A: PumpSwap verstehen

Stand: 16. Oktober 2026. Ergebnis der Stufe A aus dem [R3-Plan](R3-PLAN.md).
Noch kein Code geändert.

## Quellen

| Quelle | Stand |
| --- | --- |
| Offizielles Repository `github.com/pump-fun/pump-public-docs` | Commit `639b87f` vom 13.10.2026 |
| IDLs `idl/pump_amm.json`, `idl/pump_fees.json` aus diesem Repository | gleicher Commit |
| Offizielles SDK `@pump-fun/pump-swap-sdk` von npm | Version 2.1.0 vom 07.10.2026 |
| Schnappschuss des echten Gebührenkontos im SDK (`feeConfigMainnetFixture.ts`) | aufgenommen 08.09.2026, Slot 445186127 |
| Gebührentabelle `pump.fun/docs/fees` | abgerufen 13.10.2026 |
| R2-Daten: 19'177 gespeicherte PumpSwap-Pool-Konten zu 262 Pools | 09. bis 16.10.2026 |

Das Gebührenkonto live von der Blockchain zu lesen, scheiterte aus der Cloud:
Der öffentliche Solana-RPC antwortete mit 429, PublicNode mit 403. Das kann
später einmalig über den Helius-Zugang auf dem VPS nachgeholt werden.

## 1. `virtual_quote_reserves`: geklärt, keine Sperre nötig

Laut Doku (`NEGATIVE_VIRTUAL_QUOTE_RESERVES.md`,
`VIRTUAL_QUOTE_RESERVES_FEE_ADJUSTMENT.md`) und SDK:

```text
pool_quote_token_account.amount = echte Quote-Reserven + protocol_fees + creator_fees
virtual_quote_reserves          = boost_reserves - protocol_fees - creator_fees   (i128, mit Vorzeichen)

effektive Quote-Reserven = Tresor + virtual_quote_reserves   (dient der Preisbildung)
echte Liquidität         = Tresor - protocol_fees - creator_fees
Boost liegt vor, wenn    virtual_quote_reserves + protocol_fees + creator_fees != 0
```

- Das Feld kann seit dem 30.09.2026 negativ sein. Es muss als `i128` mit
  Vorzeichen gelesen werden.
- Die Basisseite bleibt der rohe Tresorbestand.
- Widerspruch in der Doku: `PUMP_SWAP_README.md` sagt noch, das Feld sei "auf
  allen Pools 0". Die neueren Dokumente und die R2-Daten widersprechen. Ich
  folge den neueren Dokumenten und den Daten.

**In R2:** Bei 260 von 262 Pools lag ein Boost vor. Die Boost-Reserven
betrugen im Median 62 % des Quote-Tresors (P10 12 %, P90 636 %). Die
Preisbildung rechnet also bei den meisten Pools mit deutlich mehr Reserven,
als echt vorhanden sind.

Laut SDK kauft eine Boost-Berechtigung über `boost_buy_and_burn` Tokens aus
dem Pool und verbrennt sie. Die Recherche vom 13. Oktober (offizielles Konto
@Pumpfun, 21.07.2026) beschreibt das als Rückkauf in den ersten 5 Minuten
nach der Migration. Eine genaue Beschreibung im Doku-Repository fehlt; dort
wird auf "bestehende Doku" verwiesen.

## 2. Liquidität: DEX Screener überschätzt bei PumpSwap

Vergleich in R2 (6'852 Stichproben, nur Pools mit SOL als Gegenwährung):

| Verhältnis | P10 | Median | P90 |
| --- | ---: | ---: | ---: |
| DEX-Liquidität / (2 × echter Quote-Wert) | 1,06 | 1,52 | 4,99 |
| DEX-Liquidität / (2 × effektiver Quote-Wert) | 0,55 | 0,74 | 0,94 |

DEX Screener liegt zwischen echter und effektiver Liquidität. Die echte
Liquidität ist im Median um ein Drittel kleiner als angezeigt, bei jedem
zehnten Pool um rund vier Fünftel oder mehr. Kleine Zeitunterschiede zwischen
Kurs und Kontoabfrage sind im Vergleich enthalten.

**Folge für R3:** Die Grenze von 10'000 USD muss bei PumpSwap an der echten
on-chain Liquidität gemessen werden. Die DEX-Angabe taugt nur für die
Vorauswahl.

## 3. Gebühren: vollständig bestimmbar

Aus Doku (`FEE_PROGRAM_README.md`) und SDK (`src/sdk/fees.ts`, `util.ts`, `pda.ts`):

- Gebührenkonto: `FeeConfig` des Fee-Programms
  `pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ`, Adresse
  `5PHirr8joyTMp9JMm6nW7hNDVyEYdkzDqazxPD7RaTjx` (PDA aus `"fee_config"` und
  der PumpSwap-Programm-ID; selbst nachgerechnet).
- **Kanonischer Pool**: `pool.creator` = PDA `["pool-authority", base_mint]`
  des Pump-Programms. Nur diese zahlen die Staffel.
- Nicht kanonische Pools: `flat_fees` = 0,30 % (LP 0,25 %, Protokoll 0,05 %).
- Kanonisch mit SOL: `fee_tiers`; mit USDC: `stable_fee_tiers`; andere
  Gegenwährung: `exotic_flat_fees`, solange gesetzt, sonst `flat_fees`.
- Marktkapitalisierung = effektive Quote-Reserven × Base-Mint-Supply /
  Base-Reserven (in Lamports bzw. USDC-Einheiten). Mayhem-Pools rechnen mit
  festem Supply von 10^15.
- Pro Pool kann `creator_fee_bps` die Creator-Gebühr ersetzen. Laut Doku nur
  bei fremder Gegenwährung; in R2 bei 11 Pools gesetzt, die 10 davon
  geprüften hatten alle eine fremde Gegenwährung.

Gebührenstaffel aus dem Schnappschuss vom 08.09.2026 (deckt sich mit der
Webseite vom 13.10.2026):

| Marktkapitalisierung (SOL-Paar) | LP | Protokoll | Creator | Total |
| --- | ---: | ---: | ---: | ---: |
| unter 420 SOL | 0,02 % | 0,93 % | 0,30 % | 1,25 % |
| ab 420 SOL | 0,20 % | 0,05 % | 0,95 % | 1,20 % |
| sinkt in 25 Stufen | | | | |
| ab 98'240 SOL | 0,20 % | 0,05 % | 0,05 % | 0,30 % |

USDC-Paare: gleiche Sätze, Stufen ab 59'000 bis 20'000'000 USDC.

**Folge für R3:** Das Gebührenkonto wird bei jeder Pool-Prüfung im selben
`getMultipleAccounts`-Aufruf mitgelesen. Das kostet keine zusätzliche Anfrage.

## 4. Sonderfälle

| Merkmal | Bedeutung laut Doku/SDK | Pools in R2 | Vorschlag R3 |
| --- | --- | ---: | --- |
| `is_holder_reward` | Creator-Gebühr geht an die Halter; Handel unverändert | 48 | erlauben |
| `is_cashback_coin` | veraltet; Creator-Gebühr kann an Käufer zurückfliessen | 0 | gesperrt lassen |
| `is_mayhem_mode` | eigener Modus, Gebühren nicht dokumentiert | 1 | gesperrt lassen |
| `can_edit_creator_fee` | reserviert, immer `false` | 0 | sperren, falls `true` |
| `creator_fee_bps > 0` | nur bei fremder Gegenwährung | 11 | gesperrt (Gegenwährung) |
| Konto länger als 287 Bytes | Platz für künftige Felder | alle (300/301 Bytes), Zusatzbytes immer 0 | erlauben, solange die Zusatzbytes 0 sind |

## 5. BOOST und der Einstiegszeitpunkt

Fast jeder PumpSwap-Pool in R2 war geboostet. Der Rückkauf nach der Migration
erzeugt Kaufdruck, der nicht vom Markt kommt. Die Kaufzahlen von DEX Screener
dürften ihn enthalten. Das ist eine Vermutung, nicht geprüft.

**Vorschlag für R3:** Bei PumpSwap erst ab 10 Minuten Poolalter einsteigen
(5 Minuten Rückkauf laut @Pumpfun plus Puffer). Bisher gilt für alle Pools
ein Mindestalter von 60 Sekunden. Diese Grenze ist eine Annahme und wird im
R3-Protokoll vorab festgelegt.

## Noch offen

1. Gebührenkonto einmalig live lesen, über Helius auf dem VPS, um zu
   bestätigen, dass die Stufen seit dem 08.09. unverändert sind.
2. Genaue Funktionsweise von BOOST (Dauer, Umfang) aus einer Primärquelle.
3. Wie DEX Screener die PumpSwap-Liquidität berechnet. Für R3 nicht nötig,
   wenn die Einstiegsprüfung on-chain misst.

Keiner dieser Punkte blockiert den Beginn von Stufe B.
