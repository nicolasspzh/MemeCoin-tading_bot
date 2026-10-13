# Recherche vom 13. Oktober 2026 und Einordnung für den Bot

Dieses Dokument hat zwei Teile:

- **Teil A:** Einordnung durch Claude Code. Abgleich mit dem Code, eigene
  Prüfung an Primärquellen und Logauswertung vom VPS.
- **Teil B:** Der unveränderte Originalbericht der Recherche auf X, erstellt
  mit Claude in Chrome am 13. Oktober 2026.

Nichts davon ändert die laufende R2-Sammlung. Alle Ideen gelten erst für eine
neue Version mit neuem, vorab festgelegtem Testfenster. Beiträge auf X sind
keine Belege. Teil B enthält Aussagen, die nicht geprüft sind.

# Teil A: Einordnung

## Selbst an Primärquellen geprüft (13. Oktober 2026)

### PumpSwap-Gebühren

Quelle: `https://pump.fun/docs/fees`, am 13. Oktober 2026 abgerufen.

- Bonding Curve: 1,25 % pro Trade (Creator 0,30 %, Protokoll 0,95 %, LP 0 %).
- PumpSwap, kanonische Pools mit SOL-Paar: Staffel nach Marktkapitalisierung
  (Preis in SOL mal 1 Milliarde Tokens). 1,25 % bei 0 bis 420 SOL, 1,20 % bei
  420 bis 1'470 SOL, danach stufenweise sinkend bis 0,30 % ab 98'240 SOL.
- PumpSwap mit USDC-Paar: eigene Staffel, ebenfalls von 1,25 % bis 0,30 %.
- Nicht kanonische PumpSwap-Pools: 0,3 % (Creator 0 %, Protokoll 0,05 %, LP 0,25 %).
- Coins mit anderer Gegenwährung (Custom Pairs): eigene Pauschale, nicht weiter
  ausgewertet.

Vergleich mit dem Bot: Das Modell rechnet fix mit 0,3 % (`fee_bps=30`). Für
kleine PumpSwap-Coins ist die echte Gebühr etwa viermal so hoch. Grobe
Rechnung, nicht getestet: Kauf und Verkauf zusammen kosten rund 2,5 %
Gebühren, dazu 2 % modellierte Slippage. Ein Einstieg ab +1 % Anstieg muss
damit erst rund 4,5 % Kosten aufholen.

R2 ist davon nicht verfälscht: PumpSwap ist dort gesperrt, und bei
Raydium-CPMM wird die echte Gebühr on-chain gelesen und jeder Pool über 0,3 %
gesperrt (`trading/risk.py`).

### PumpSwap-Pool-Layout

Quelle: offizielles IDL
`https://raw.githubusercontent.com/pump-fun/pump-public-docs/main/idl/pump_amm.json`,
am 13. Oktober 2026 abgerufen, Programm `pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA`.

| Byte | Feld | Behandlung im Code (`collectors/holders.py`) |
| ---: | --- | --- |
| 8 bis 242 | Bump, Index, Creator, Mints, LP-Mint, Tresore, LP-Supply, Coin-Creator | korrekt gelesen |
| 243 | `is_mayhem_mode` | gesetzt: Sperre `unsupported_pumpswap_mode` |
| 244 | `is_cashback_coin` | gesetzt: Sperre `unsupported_pumpswap_mode` |
| 245 bis 260 | `virtual_quote_reserves` (i128) | ungleich null: Sperre `unsupported_virtual_quote_reserves` |
| 261 bis 268 | `creator_fee_bps` | ungleich null: Sperre `unsupported_pool_fields` |
| 269, 270 | `can_edit_creator_fee`, `is_holder_reward` | gesetzt: Sperre `unsupported_pumpswap_mode` |
| 271 bis 278 | `protocol_fees` | **neu**, jedes Byte ungleich null: Sperre `unsupported_pool_fields` |
| 279 bis 286 | `creator_fees` | **neu**, jedes Byte ungleich null: Sperre `unsupported_pool_fields` |

Das erklärt, warum in der Entwicklungsreferenz 540 von 623 PumpSwap-Zeilen
`unsupported_pool_fields` hatten. `virtual_quote_reserves` war in allen
623 Zeilen ungleich null. Wofür das Feld genau dient, ist noch nicht geklärt.
Zusätzlich sperrt `pumpswap_dynamic_fees_unverified` jeden PumpSwap-Pool.

## Logauswertung vom VPS (13. Oktober 2026)

`grep` über das aktuelle Sammlerlog (rotiert bei 5 MB, also nicht die ganze
Sammlung):

| Anzahl | Meldung | Bedeutung |
| ---: | --- | --- |
| 3'469 | `Unsupported vault extension:15` | TransferHookAccount am Pool-Tresor |
| 2'646 | `Unsupported vault extension:27` | PausableAccount am Pool-Tresor |

Ableitung aus dem Code, nicht einzeln an Transaktionen geprüft: Hätte der
Meme-Token selbst Transfer Hook oder Pausable, würde schon die Mint-Prüfung
sperren und die Tresorprüfung gar nicht laufen. Die Erweiterungen sitzen
deshalb sehr wahrscheinlich im Tresor der **Gegenwährung**: Pools mit
tokenisierten Aktien oder anderen Token-2022-Assets als Gegenwährung, passend
zu Fund 1, 2 und 7 in Teil B.

Folgen: Diese Coins werden nie gekauft (vorsichtig und korrekt). Der Fall
erscheint aber als Datenfehler statt als klare Sperre, setzt `data_degraded`,
belegt einen der 8 Beobachtungsplätze für rund 96 Minuten und verbraucht
RPC-Anfragen ohne Nutzen.

## Abgleich der Funde aus Teil B mit dem Code

| Fund | Stand im Code | Einordnung |
| --- | --- | --- |
| 1, 2 Andere Gegenwährungen | Nur wSOL und USDC erlaubt (`holders.py`, `unsupported_quote_mint`). | Abgedeckt. Vermutete Nebenwirkung, nicht geprüft: Die Raydium-Erkennung nimmt beide Tokens eines Pools als Kandidaten auf (`collectors/pools.py`), auch eine tokenisierte Aktie. |
| 3 BOOST mode | Nicht relevant, solange PumpSwap gesperrt ist. | Später wichtig: Rückkäufe in den ersten 5 Minuten nach der Migration erhöhen die Kaufzahlen von DEX Screener. |
| 4 Dynamic Fees | Feste 0,3 % im Modell. | Bestätigt, siehe oben. Grösster Einfluss auf die Kosten. |
| 5 IDL-Fallen | Token-2022 nur mit Metadaten ist erlaubt. `dataSize` wird nicht genutzt. | Layout bestätigt, siehe oben. |
| 6 Sandwich | Fixe Slippage 1 % plus Preiseinfluss. Fehlschlag erst ab 10 % ungünstiger Bewegung. | Praktisch 10 % Toleranz, keine Sandwich-Kosten. Studie nur aus Zweitquellen. |
| 7 Bundle | Transfer Fee und fremde Gegenwährung wären gesperrt. Keine Bundle-Erkennung. | Bekannte Lücke (Wallet-Cluster). Merkmale konkret umsetzbar, kosten zusätzliche RPC-Anfragen. |
| 8 Helius-Umstellung | Nur normale RPC-Methoden (`collectors/solana.py`). | Nicht betroffen. |
| 9, 10 LaserStream, Migration | Polling über HTTP, keine Erkennung von Pump oder Meteora. | Späterer Umbau der Pool-Erkennung. |
| 11, 12 | | Schwache Belege, tiefe Priorität. |

## Ideen für die nächste Version, nach der R2-Auswertung

Priorisiert. Keine davon ist umgesetzt oder getestet.

1. **Kostenmodell je Pool:** echte Gebühr aus Staffel oder Pool-Konto statt
   fix 0,3 %. Grundlage für alle weiteren Schritte.
2. **Gegenwährung zuerst prüfen:** Nur wSOL und USDC zulassen, alles andere
   sofort mit klarer Begründung sperren und nicht in einen Beobachtungsplatz
   aufnehmen. Gegenwährungen mit Transfer Hook, Pausable oder Permanent
   Delegate bleiben gesperrt.
3. **PumpSwap gezielt unterstützen:** aktuelles Layout mit `protocol_fees`
   und `creator_fees` lesen, Bedeutung von `virtual_quote_reserves` klären,
   Gebührenstaffel anwenden, die ersten Minuten nach der Migration
   ausschliessen (BOOST mode).
4. **Sandwich-Kosten** abhängig von der Slippage-Toleranz simulieren, mit
   tieferer Toleranz.
5. **Bundle-Merkmale** als zusätzliche Sperre: mehrere Signierer in einer
   Transaktion, Käufe im Erstellungsblock, gleiche Beträge über mehrere
   Launches, Verkäufe in der ersten Minute.

Jede Änderung in `collectors/`, `trading/`, `data/`, `config/`,
`backtesting/` oder `main.py` ändert den Code-Fingerprint. Danach braucht es
ein neues Protokoll mit neuem zukünftigem Testfenster. Ob sich die Strategie
mit realistischen Kosten überhaupt lohnt, zeigt erst dieser neue Test.

## Nicht geprüft

Bitquery-Bericht (Fund 6), GitHub-Code aus Fund 5, Solscan-Transaktion aus
Fund 7, Helius-Dokumentation (Fund 8 und 9), Jito-Dokumentation (Fund 12),
Medium-Artikel (Fund 11).

# Teil B: Originalbericht der Recherche (unverändert)

# Recherche auf X: Verbesserungen für den Solana-Meme-Coin-Bot

Stand: 13.10.2026. Recherche nur lesend auf X, rund 40 Minuten, in einem Tab. Keine Links zu Wallets, Claims oder Telegram geöffnet. Kein Captcha, keine Sperre.

**Echtheit der offiziellen Konten** (geprüft über die verlinkten X-Konten auf den Websites):

| Website | Verlinktes Konto |
|---|---|
| pump.fun | @Pumpfun |
| raydium.io | @Raydium |
| meteora.ag | @MeteoraAG |
| helius.dev | @helius |
| dexscreener.com | @dexscreener |

---

## Funde

### 1. Pump.fun Custom Pairs: Pools mit anderer Gegenwährung als SOL
- **Thema:** 1, 2
- **Zusammenfassung:** Seit September kann man Pump.fun-Tokens mit tokenisierten Aktien, grossen Coins oder Metallen paaren. Am Start gab es 20 neue Paare. Bonding-Curve- und PumpSwap-Protokollgebühren sind gleich wie bei normalen Launches. Laut FAQ gibt es eine Option «Cashback» (Gebühren gehen an die Trader zurück), keine zusätzliche Transfersteuer, und das Paar kann nachträglich nicht mehr geändert werden.
- **Relevanz:** Dein Bot geht vermutlich von SOL als Gegenwährung aus. Liquidität, Kurs und Slippage stimmen dann bei diesen Pools nicht mehr.
- **Links:** [Thread](https://x.com/Pumpfun/status/2097785975434846285), [FAQ](https://x.com/Pumpfun/status/2097785995789742253), @Pumpfun, 09.09.2026
- **Zuverlässigkeit:** offiziell
- **Prüfen:** Wie die Gegenwährung im PumpSwap-Pool gespeichert ist und wie die Gebühren mit Cashback aussehen.

### 2. Raydium LaunchLab und Meteora DBC: auch beliebige Paare
- **Thema:** 2
- **Zusammenfassung:** Raydium sagt, LaunchLab unterstütze jetzt jedes Token-Paar. Meteora wirbt bei DBC mit «Any token. Any pair.».
- **Relevanz:** Das gleiche Problem wie bei Fund 1, nur auf allen drei Launchpads. Dein Bot sollte die Gegenwährung jedes Pools lesen und Pools mit unbekannter Gegenwährung ablehnen.
- **Links:** [Raydium](https://x.com/Raydium/status/2096695643049714111), 06.09.2026; [Meteora](https://x.com/MeteoraAG/status/2099712351058698639), 15.09.2026
- **Zuverlässigkeit:** offiziell, aber ohne technische Details
- **Prüfen:** In den LaunchLab- und DBC-Dokus nachsehen, welche Felder die Gegenwährung angeben.

### 3. Pump.fun BOOST mode: Rückkäufe direkt nach der Migration
- **Thema:** 1, 6
- **Zusammenfassung:** Pump.fun schreibt, dass bei einer Migration bisher etwa 20 % der Liquidität für immer im LP feststeckten. Seit dem 21.07.2026 werden alle migrierten Coins automatisch in 5 Minuten per TWAP zurückgekauft (17.6 SOL bei SOL-Paaren, 2'516 $ bei USDC-Paaren), und die gekauften Tokens werden verbrannt. TWAP heisst: Der Kauf wird in kleine Stücke über die Zeit verteilt. Coins aus «Mayhem» haben das nicht.
- **Relevanz:** Sehr wichtig, sobald du PumpSwap freigibst. Dieser Kaufdruck ist gesteuert und kommt nicht vom Markt. Dein Signal «mindestens 1 % Anstieg mit Kaufdruck» löst in diesen 5 Minuten wahrscheinlich falsch aus, und nach 5 Minuten fällt der Kaufdruck weg. Das ist meine Folgerung, nicht getestet.
- **Links:** [Erklärung](https://x.com/Pumpfun/status/2079580272488562975), [Hinweis zu Mayhem](https://x.com/Pumpfun/status/2079580274124316995), @Pumpfun, 21.07.2026
- **Zuverlässigkeit:** offiziell
- **Prüfen:** Wie man die Käufe des Boost-Programms on-chain erkennt, um sie aus dem Kaufdruck herauszurechnen.

### 4. PumpSwap Dynamic Fees V1
- **Thema:** 1 (grundlegend, darum älter als 6 Monate)
- **Zusammenfassung:** Die Creator Fee auf PumpSwap hängt von der Marktkapitalisierung ab: Je höher die Marktkapitalisierung, desto tiefer die Gebühr. Das gilt für alle PumpSwap-Coins. Protokoll- und LP-Gebühr sind gleich geblieben. Die vollständige Tabelle steht unter pump.fun/docs/fees.
- **Relevanz:** Eine feste Gebühr in deiner Simulation ist für PumpSwap falsch. Mit Cashback aus Fund 1 kann die Gebühr zudem pro Coin anders sein.
- **Links:** [Beitrag](https://x.com/Pumpfun/status/1962916237148926104), @Pumpfun, 02.09.2025
- **Zuverlässigkeit:** offiziell
- **Prüfen:** Die aktuelle Stufentabelle in pump.fun/docs/fees. Ich habe sie nicht geöffnet.

### 5. Entwickler-Log: was in der PumpSwap-IDL fehlt
- **Thema:** 1, 3
- **Zusammenfassung:** Die IDL ist die Schnittstellenbeschreibung eines Programms. Der Entwickler nennt diese Fallen:
  - Die Event-Diskriminatoren weichen von der Anchor-Formel ab.
  - Beim Kauf und Verkauf braucht es zusätzliche Accounts, die in der IDL fehlen.
  - Die fee_config-PDA wird unter dem Fee-Programm abgeleitet, nicht unter dem Pump-Programm.
  - **Neuere Pump-Coins sind Token-2022.** Das Token-Programm muss man aus dem Owner des Mint-Accounts lesen.
  - Bei der Migration ist die Gegenwährung wSOL, obwohl die Curve natives SOL nutzte.
  - Pool-Accounts wachsen nachträglich. Ein Filter `dataSize=178` findet darum nichts mehr, `memcmp` auf `base_mint` schon.
- **Relevanz:** Wenn dein Bot Token-2022 grundsätzlich verdächtig findet, verpasst er viele Pump-Coins. Den Fehler mit dataSize kannst du direkt in deiner Pool-Erkennung prüfen.
- **Links:** [Thread](https://x.com/solgrid_dev/status/2098813144730685573), @solgrid_dev, 12.09.2026
- **Zuverlässigkeit:** technisch belegt. Er verlinkt Code auf GitHub, den ich aber nicht geprüft habe.
- **Prüfen:** Die offizielle Pump-IDL und das SDK.

### 6. Bitquery-Studie zu Sandwich-Angriffen
- **Thema:** 5
- **Zusammenfassung:** Zwischen 30.10.2025 und 07.10.2026 gab es 6'850'144 Sandwich-Angriffe von 2'545 Bot-Wallets, mit 29.7 Mio. $ Bruttoertrag. Bei einem Sandwich kauft ein Bot direkt vor dir und verkauft direkt nach dir.
  - 96 % der Angriffe trafen die Pump.fun-Curve und PumpSwap.
  - Rund 39 % des Ertrags stammten von anderen Bots, zum Beispiel Snipern.
  - Bei Jupiter-Swaps über Pump oder PumpSwap wurden Trades mit 20 bis 50 % Slippage-Toleranz 14-mal häufiger angegriffen als Trades unter 3 %.
  - In einer kleinen Stichprobe von 63 Angriffen machten 18 nach Kosten Verlust.
  - Meine eigene Rechnung: im Schnitt etwa 4.3 $ pro Angriff, also brutto.
- **Relevanz:** Dein Bot ist genau dort unterwegs. Simuliere Sandwich-Kosten abhängig von deiner Slippage-Toleranz, nicht als feste Zahl.
- **Links:** [Zusammenfassung auf Vietnamesisch, am ausführlichsten](https://x.com/coinphoton_vi/status/2109586202743734405), 12.10.2026; [Kurzfassung auf Englisch](https://x.com/0xvitech/status/2110002344968470646), 13.10.2026
- **Zuverlässigkeit:** nur Zweitquellen gelesen, die sich auf CryptoSlate und Bitquery berufen. Mehrere Konten nennen die gleichen Zahlen.
- **Prüfen:** Den Originalbericht von Bitquery.

### 7. Ein Bundle-and-Dump on-chain zerlegt (StonkFun auf LaunchLab)
- **Thema:** 3, 4
- **Zusammenfassung:** Der Coin war Token-2022 mit 1 % Transfer Fee, Mint- und Freeze-Rechte waren entfernt. Er war mit NVDAx gepaart, einer tokenisierten Aktie. Der Ablauf:
  - Drei Transaktionen im selben Block: zuerst finanzieren, dann Coin erstellen plus Dev-Kauf, dann kaufen drei weitere Wallets.
  - Vier Wallets haben eine einzige Transaktion gemeinsam signiert. Das spricht stark für ein Team.
  - Zusammen hielten sie etwa 31.6 %, bevor jemand anderes kaufen konnte.
  - Die drei Wallets verkauften alles zwischen Sekunde 44 und 76, mit rund 40 SOL Gewinn.
  - Die gleichen Beträge (2.15 / 1.81 / 1.94 SOL) tauchten bei 11 weiteren Launches auf.
  - Wichtig für Thema 3: Der NVDAx-Tresor des Pools meldet einen **Permanent Delegate**. Der Emittent kann diese Tokens also jederzeit einziehen, auch aus dem Pool.
- **Relevanz:** Daraus ergeben sich konkrete Merkmale für deinen Bot: mehrere Signierer in einer Transaktion, Käufe im Erstellungsblock, gleiche Beträge über mehrere Launches und Verkäufe in der ersten Minute. Prüfe Token-2022-Erweiterungen auch bei der Gegenwährung, nicht nur beim Meme-Token.
- **Links:** [Artikel mit Solscan-Link](https://x.com/KombuchoBuild/status/2110033898306404620), @KombuchoBuild, 13.10.2026
- **Zuverlässigkeit:** technisch belegt, mit Transaktions-Hash. Die Transaktion selbst habe ich nicht nachgeprüft.

### 8. Helius: Webhooks und Enhanced Transactions werden ersetzt
- **Thema:** 7
- **Zusammenfassung:** «Parsed Streams» und die «Parsed Events API» ersetzen die alte Enhanced Transactions API und die Webhooks. Laut Helius kostet die Parsed Events API 10 Credits pro Anfrage (10-mal weniger), Parsed Streams 1 Credit pro Event (gleich wie Webhooks). Beides gibt es in allen Plänen, auch im Gratisplan.
- **Relevanz:** Wenn dein Bot Webhooks oder Enhanced Transactions nutzt, musst du wahrscheinlich umstellen.
- **Links:** [Beitrag](https://x.com/Helius/status/2103232776069935254), @Helius, 24.09.2026
- **Zuverlässigkeit:** offiziell
- **Prüfen:** Ob und wann die alten Endpunkte abgeschaltet werden. Ein Datum habe ich nicht gesehen.

### 9. Helius LaserStream: Filter `matchMints`
- **Thema:** 4, 7
- **Zusammenfassung:** Bei normalen SPL-Transfers steht der Mint nicht in den Account-Keys. gRPC-Filter mit `accountInclude` verpassen solche Transfers deshalb. Das neue Flag `matchMints` vergleicht Kontostände vor und nach der Transaktion. Es funktioniert auch beim Nachladen der letzten 24 Stunden.
- **Relevanz:** Damit siehst du, wenn ein Dev Tokens per einfachem Transfer an weitere Wallets verteilt. Das ist für die Erkennung von Clustern wichtig.
- **Links:** [Beitrag](https://x.com/Helius/status/2101007447389598059), @Helius, 18.09.2026
- **Zuverlässigkeit:** offiziell
- **Prüfen:** helius.dev/docs/laserstream/mint-filtering und die Kosten dafür.

### 10. Curve voll heisst noch nicht migriert
- **Thema:** 2
- **Zusammenfassung:** Pump verwaltet die Curve und die Migration, PumpSwap übernimmt ab dem Pool. Das Ende der Curve und die Migration sind zwei getrennte Ereignisse. Die Curve kann voll sein, bevor der Pool existiert.
- **Relevanz:** Für eine frühe und zuverlässige Erkennung solltest du beide Programme beobachten.
- **Links:** [Beitrag](https://x.com/SupanodeXYZ/status/2092286590215500180), @SupanodeXYZ, 25.08.2026
- **Zuverlässigkeit:** technisch, aber Werbung eines RPC-Anbieters
- **Prüfen:** Die offizielle Pump-Doku zum Ablauf der Migration.

### 11. «Migration Specialists»
- **Thema:** 6
- **Zusammenfassung:** Der Autor hat 10'797 Wallets bei 155 migrierten Tokens untersucht. 14 Wallets kaufen immer vor der Migration und verkaufen danach.
- **Relevanz:** Wenn dein Bot direkt nach der Migration einsteigt, kauft er möglicherweise genau von diesen Wallets.
- **Links:** [Beitrag](https://x.com/Ola_Crrypt/status/2063158035699163514), @Ola_Crrypt, 06.06.2026
- **Zuverlässigkeit:** Meinung mit eigener Analyse. Die Stichprobe ist klein, und ich habe den Medium-Artikel nicht gelesen.

### 12. Jito-Tip nach den aktuellen Perzentilen
- **Thema:** 5
- **Zusammenfassung:** Ein Tool liest alle 30 Sekunden die Perzentile der erfolgreichen Jito-Tips (p50, p75, p95). Zum Zeitpunkt des Beitrags lag p50 bei etwa 0.000002 SOL. Ein anderer Beitrag erklärt, dass Priority Fee und Jito-Tip verschiedene Probleme lösen.
- **Relevanz:** Simuliere den Tip dynamisch statt als feste Zahl.
- **Links:** [Beitrag](https://x.com/shadeswap_sol/status/2109190136101744717), 11.10.2026
- **Zuverlässigkeit:** Werbung, die Zahl ist nicht belegt
- **Prüfen:** Die offizielle Jito-Doku zum Tip Floor.

---

## Die 5 wichtigsten Funde

1. **Andere Gegenwährungen als SOL** (Funde 1, 2, 7): Pump.fun, LaunchLab und DBC erlauben sie inzwischen alle. Dazu kommt das Risiko durch einen Permanent Delegate bei tokenisierten Aktien.
2. **BOOST mode** (Fund 3): gesteuerter Kaufdruck in den ersten 5 Minuten nach der Migration, also wahrscheinlich falsche Einstiegssignale.
3. **Sandwich-Studie** (Fund 6): Slippage unter 3 % halten und Sandwich-Kosten abhängig von der Toleranz simulieren.
4. **Fallen in der PumpSwap-Technik** (Fund 5): Token-2022 ist bei Pump-Coins normal, und der Filter mit dataSize funktioniert nicht mehr.
5. **Bundle-Merkmale** (Fund 7): mehrere Signierer, Käufe im selben Block, gleiche Beträge über mehrere Launches, Verkauf in der ersten Minute.

Gleich danach kommt die Umstellung bei Helius (Fund 8).

## Warnsignale und Betrugsmuster

- **Gefälschte Konten:** «PUMPFUN OFFICIAL» (@CryptoGems_1000) und «PumpFun Marketing» (@Pumpfun_FDN) haben nichts mit dem echten @Pumpfun zu tun.
- **Angebliche offizielle Token-Adresse:** Ein Beitrag nennt eine «offizielle Token-Adresse» für PUMPSWAP. Das ist nicht belegt, ich behandle es als Warnsignal.
- **Volumen-Bot als Open Source** ([@anshu_code, 2025](https://x.com/anshu_code/status/1965525284293149147)): mehrere Wallets, zufällige Beträge, Kauf und Verkauf in derselben Transaktion. Daraus ergibt sich ein Erkennungsmerkmal für Wash Trading: dieselbe Wallet kauft und verkauft den gleichen Token in einer Transaktion.
- **Automatische Scam-Warnungen** wie @ruggedornot, zum Beispiel «ein Bundle aus 6 Wallets hat die Curve allein gefüllt». Die Idee ist brauchbar, aber die Aussagen sind nicht geprüft.
- **Unbelegte Zahl:** Die «Top 25 Deployer» sollen 128 Mio. $ abgezogen haben ([@bandosei](https://x.com/bandosei/status/2108215385397059797)). Eine Quelle dazu habe ich nicht gesehen.
- **Signal- und Werbebeiträge:** «Premium Briefings» mit Trefferquoten und bezahlte Werbung in den Antworten. Das sind keine Belege.
- Es gab keinen Beitrag, der sich direkt mit Anweisungen an mich richtete.

## Gesucht, aber nicht gefunden

- Änderungen an der DEX-Screener-API: keine Beiträge von @dexscreener dazu.
- Eine offizielle Einordnung von Transfer Hook, Pausable und Transfer Fee in Pool-Tresoren. Gefunden habe ich nur Fund 7 und Lernbeiträge.
- Die genauen Zahlen der PumpSwap-Gebühren, nur den Verweis auf die Doku.
- Details zu Meteora DAMM v2, also Fee Scheduler und Schutz vor Snipern.
- Was «Mayhem mode» bei Pump.fun genau ist.
- Belegte Daten zu späten Einstiegen nach starkem Anstieg. Gefunden habe ich nur Meinungen.

## Was ich nicht prüfen konnte

- Ich habe keine externen Quellen geöffnet: kein GitHub-Repo, keinen Medium-Artikel, nicht den Bitquery-Bericht, keine Doku und keine Solscan-Transaktion.
- Einige lange Beiträge waren gekürzt («Show more»). Ich habe nur gelesen, was angezeigt wurde.
- Die X-Suche ist nicht vollständig. Es kann also gute Beiträge geben, die ich nicht gefunden habe.
- Alle Folgerungen für deinen Bot sind meine Einschätzung und nicht getestet.
