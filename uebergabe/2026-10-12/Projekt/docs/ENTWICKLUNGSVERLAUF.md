# Historischer Entwicklungsverlauf

Die folgenden Abschnitte dokumentieren frühere Entwicklungsstände und Tests.
Alte Zeitfenster, Installationsbefehle und Cloud-Startanweisungen sind keine
Handlungsanweisung für den laufenden R2-VPS. Maßgeblich ist der
[aktuelle Projektstand](PROJEKTSTAND.md). Lokale runtime-Dateien sind nicht
Teil des Git-Repositories.

# Meme Coin Bot v0.1

Python-Grundlage für Solana-Marktdaten und **ausschließlich Paper Trading**.
Startkapital: simulierte **50 USD**. Es gibt keine Wallet-Anbindung, privaten
Schlüssel, Transaktionssignierung oder Live-Order-Funktion.

Vorbereitung der späteren Phase-6-Auswertung: Der
[Offline-Auswertungsbericht](../operations/AUSWERTUNGSBERICHT.md) stellt eine
bereits vorhandene `result.json` im Browser dar. Die laufende R2-Sammlung
bleibt unverändert; ihre Ergebnisse werden erst nach dem Sammelende geprüft.

Separat vorbereitet: [Anti-FOMO und risikobasierte Positionsgröße](../operations/EINSTIEGSVARIANTEN.md).
Der synthetische Entscheidungsvergleich erzeugt keine Trades und ändert den
laufenden Sammler oder die bestehende Strategie nicht.

## Start

Python 3.12 oder neuer; Linux/macOS (Prozesssperre mit `fcntl`). In der vorbereiteten Cloud-Umgebung:

```bash
cd /workspace/MemeCoin-tading_bot
source /workspace/.venvs/memecoin/bin/activate
python main.py demo
python -m pytest -q
```

Neuinstallation auf einem eigenen Rechner:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
```

`bash scripts/setup.sh` installiert und testet in der Cloud. Mit
`BOT_VENV=/gewünschter/pfad` lässt sich der Installationsort ändern.

Die Demo verwendet feste, **synthetische** Beobachtungen. Erwartet werden
18 Snapshots, 18 Entscheidungen, ein Kauf und ein Verkauf. Eine Wiederholung
mit derselben Datenbank erzeugt keine weiteren Trades. Für einen neuen Demolauf
einen anderen Dateinamen verwenden: `python main.py demo --db runtime/demo2.sqlite3`.
Demo-Gewinne belegen keine profitable Handelsstrategie.

## Live-Marktdaten sammeln

```bash
cp .env.example .env  # nur wenn noch keine eigene .env existiert
python main.py collect --once
python main.py collect --cycles 3 --log-file logs/bot.log
python main.py collect --log-file logs/bot.log
```

`collect` verwendet echte Marktdaten und simuliert ausschließlich die Orders.
`Ctrl+C` beendet den Lauf; Wallet und Positionen werden beim nächsten Start
aus derselben SQLite-Datei geladen. Der Prozess läuft im Vordergrund und muss
nach dem Neustart der Cloud-Maschine erneut gestartet werden. Es ist kein
unbeaufsichtigter Dauerbetrieb eingerichtet.

Erforderliche HTTPS-Domains:

- `api.dexscreener.com`: Kandidatenprofile und Pool-Marktdaten.
- `api.mainnet-beta.solana.com`: Mint-Account und größte Token-Accounts.
- `solana-rpc.publicnode.com`: zusätzlicher öffentlicher RPC für verfügbare Methoden.
- `mainnet.helius-rpc.com`: eingerichteter primärer RPC über die sichere Variable `SOLANA_RPC_URL`.

DEX Screener und die öffentlichen RPCs benötigen hier keinen API-Schlüssel;
Helius nutzt den bereits sicher hinterlegten Anbieterzugang.
Öffentliche RPCs können Requests ablehnen oder begrenzen. Nach Ergänzung der
Domain-Freigaben speicherte der Cloud-Test am 6. Oktober 2026 einen Zyklus mit
22 echten DEX-Snapshots und 22 Entscheidungen. Es gab keine Käufe. Ein
On-Chain-Check scheiterte; eine separate Diagnose bestätigte HTTP 429 bei
`getTokenLargestAccounts` am öffentlichen Solana-RPC. `getHealth` und
`getAccountInfo` antworteten mit HTTP 200. Stichproben bestätigten Token-2022
bei als nicht unterstützt eingestuften Kandidaten.
Der Zyklus meldete deshalb korrekt Status 2. Vollständige Risikodaten für
beliebige Tokens und längerer störungsfreier Betrieb sind noch nicht nachgewiesen.

`collect --once` beendet sich mit Status 0 nur bei mindestens einem empfangenen
Snapshot ohne API-/On-Chain-Fehler im Zyklus. Fehlende Kandidaten, fehlende Paare
oder Datenfehler ergeben Status 2. Konkrete Risikofunde sind reguläre `SKIP`s.
Bei ausgefallenem Solana-RPC werden verfügbare DEX-Snapshots trotzdem gespeichert,
aber neue Käufe gesperrt. Netzwerkfehler loggen keine Schlüssel oder URL-Parameter.

Mit `--cycles N` endet die Sammlung nach N Zyklen. Status 2 bleibt erhalten, wenn
irgendein Zyklus unvollständige Daten hatte; ein später erfolgreicher Zyklus
überschreibt die Warnung nicht. `--once` und `--cycles` sind gegenseitig exklusiv.

Optionale Mint-Adressen in `WATCH_TOKENS` (kommagetrennt) ergänzen die automatische
Erkennung. `SOLANA_RPC_URL` kann auf einen anderen HTTPS-RPC zeigen.
`SOLANA_RPC_FALLBACK_URLS` enthält optionale weitere HTTPS-RPCs, kommagetrennt;
ein leerer Wert deaktiviert Fallbacks. Zugangsdaten
gehören in die lokale `.env` bzw. sichere Umgebungseinstellungen; `.env` wird
von Git ausgeschlossen. Systemvariablen überschreiben die `.env`.

## Was Version 0.1 kann

| Baustein | Verhalten |
| --- | --- |
| Discovery | Verifizierte Raydium-CPMM-Pool-Eröffnungen über Solana-RPC; ergänzend DEX-Profile und eigene Watchlist |
| Collector | Gebündelte Kursabfragen, Marktkennzahlen und Rohdaten; persistente Abrufversuche, fehlende Kurse und Beobachtungslücken |
| On-Chain-Prüfung | Mint-/Freeze-Authority, Token-2022-Erweiterungen, verifizierte Pool-Konten, Konzentrationsgrenzen je Kontoinhaber, beobachtete Creator- und LP-Bestände |
| Risk Engine | Fehlende, veraltete oder bedenkliche Daten blockieren Einstiege; unbekannte oder nicht unterstützte Erweiterungen werden gesperrt |
| Strategie | Zwei zeitlich aufeinanderfolgende Kurse desselben Pools, mindestens 1 % Anstieg, mindestens zehn Käufe und Kauf-/Verkaufsverhältnis mindestens 2 |
| Positionen | Höchstens drei Positionen; pro Einstieg 5 % des geschätzten Trading-Kapitals; höchstens 0,1 % der gemeldeten Pool-Liquidität |
| Ausstiege | Stop Loss, Take Profit, Trailing Stop, Zeitlimit, Verkaufsdruck, Liquiditätsrückgang und Risikofunde |
| Paper-Ausführung | Persistente Orders reservieren Kapital; Fill erst an einem späteren Kurs desselben Pools, mit Kosten, Preisgrenze und möglichen Ausfällen |
| Audit | Beobachtung, Order, Entscheidung, Fill, Buchungsbeleg und Wallet-Zustand werden atomar gespeichert; Neustarts erzeugen keine Doppelbuchungen |

Die Schwellen sind Startannahmen für Forschung, keine optimierten Parameter.
Sie stehen in `config/settings.py`; die entsprechenden Großbuchstaben-Namen
können in `.env` gesetzt werden. Jeder Start speichert die verwendeten Parameter
ohne Endpoint-URLs in der Tabelle `runs`.

DEX-Profile sind ein **unvollständiger, durch Profil-Veröffentlichungen verzerrter
Kandidatenfeed**, kein Stream aller neuen Pools. Die v0.1 pollt HTTP; ein Solana-
WebSocket-Pool-Indexer ist noch nicht implementiert. Die zusätzliche On-Chain-
Quelle deckt reguläre Raydium-CPMM-Eröffnungen ab (siehe Phase 2). Market Cap und andere
fehlende Kennzahlen bleiben unbekannt; FDV wird nicht als Market Cap ausgegeben.
Pool-Erstellungszeit ist kein sicherer Nachweis des Token-Alters.

Höchstens `MAX_WATCH_TOKENS` Kandidaten werden je Zyklus abgefragt. Offene Positionen
und ausstehende Orders haben Vorrang (bei Bedarf über diesem Limit), dann feste Watchlist-Adressen, dann zuletzt am längsten nicht
abgefragte Kandidaten. Auch ein fehlender Kurs zählt als Abrufversuch, damit
Kandidaten ohne Kurs die übrigen nicht dauerhaft verdrängen. Automatisch entdeckte Kandidaten bleiben etwa 66 Minuten
in der Auswahl. Kapazitätsgrenzen werden geloggt; bei hoher Last fehlen
Beobachtungen. Erkannt bedeutet daher nicht vollständig vermessen.
`POLL_SECONDS=20` ist der angestrebte Zyklusabstand; API-Antwortzeiten, Limits und
Anzahl der Kandidaten können ihn verlängern. Es gibt begrenzte Wiederholungen
und eine gemeinsame Request-Pause von 0,35 Sekunden.

Der bisherige Anteil der zehn größten Token-Accounts bleibt als Rohwert erhalten.
Seit Phase 3 entscheidet bei neuen Marktdaten eine konservative Berechnung nach
Kontoinhabern mit überprüften Pool-Beständen (siehe unten). Kontoinhaber sind
keine identifizierten Personen. Wallet-Cluster über mehrere Adressen, vollständige
Dev-Bestände, Unique Buyers, Holder-Wachstum, Whale-Aktivität und Wash Trading
werden weiterhin nicht erkannt.

## Token-2022 und RPC-Ausfälle

Der Collector decodiert die Account-Bytes und die vollständige TLV-Liste. Er
verlässt sich nicht darauf, dass ein RPC-JSON-Parser jede neue Erweiterung kennt.
`metadataPointer` und gültige `tokenMetadata` sind zugelassen, weil sie die hier
simulierte Übertragungsmechanik nicht ändern. Änderbare Metadaten werden als
`metadata_mutable` dokumentiert; das ist keine Aussage zur Seriosität des Coins.
Metadata-URLs werden nicht abgerufen.

Transfergebühren, Transfer-Hooks, Permanent Delegates, pausierbare oder nicht
übertragbare Tokens sowie sämtliche anderen oder unbekannten Erweiterungen
bleiben gesperrt. Auch eine Erweiterung mit momentan deaktivierter Funktion
wird nicht automatisch freigegeben. Beschädigte Binärdaten, doppelte TLVs oder
unvollständig lesbare Metadaten führen zu einem Datenfehler und blockieren Käufe.

RPC-Fehler werden pro Endpunkt **und Methode** behandelt. Bei HTTP 429 pausiert
die Methode mindestens 60 Sekunden, bei 401/403 mindestens fünf Minuten; längere
numerische `Retry-After`-Werte werden respektiert. Andere RPC-Methoden und
DEX-Sammlung laufen weiter. Ein erfolgreicher alternativer Endpunkt wird für
diese Methode bevorzugt. Jeder RPC-Versuch erfolgt einmal pro Endpunkt; dadurch
wartet nicht jeder Coin erneut auf mehrere identische abgewiesene Requests.

Vollständige bzw. eindeutig abgelehnte Prüfungen werden mit
`RPC_CACHE_SECONDS=60` je Token und Pool kurz zwischengespeichert. Die ursprünglichen Prüfzeitpunkte
bleiben erhalten; fehlgeschlagene Konzentrationsabfragen werden nicht als
erfolgreiche Ergebnisse gecacht. Vorhandene Mint-Befunde bleiben bei einem
Halterabfragefehler als Teilbefund gespeichert. Sie erlauben keinen Einstieg.

Mint- und Konzentrationsbefunde speichern eigene Zeitpunkte, RPC-Hostnamen und
Solana-Slots. Bei mehr als 150 Slots Abstand wird keine Konzentration berechnet.
API-Schlüssel/URL-Parameter werden weder dort noch in der Laufkonfiguration
gespeichert. Neue Felder verändern die Hashes alter Backtest-Eingaben nicht.

Referenz für Layout und Erweiterungs-IDs:
[offizielles Token-2022-Interface](https://github.com/solana-program/token-2022/blob/main/interface/src/extension/mod.rs).

Im Live-Test am 6. Oktober 2026 lieferte `getTokenLargestAccounts` weiterhin
HTTP 429 am Solana-Endpunkt und HTTP 403 bei PublicNode. Ein separat geprüfter
dRPC-Endpunkt verlangt für Solana einen kostenpflichtigen Plan und wird daher
nicht in der Standardkonfiguration verwendet. Kostenpflichtige Zugänge wurden
nicht eingerichtet.

Für vollständige Halterprüfungen muss `SOLANA_RPC_URL` auf einen RPC zeigen, der
`getAccountInfo` und `getMultipleAccounts` mit Base64 sowie
`getTokenLargestAccounts` unterstützt. Ein eigener
kostenloser Anbieterzugang kommt infrage, sofern dessen Tarif diese Methoden
erlaubt. Die URL mit etwaigem API-Schlüssel in sicheren Umgebungseinstellungen
oder der ignorierten lokalen `.env` eintragen, nicht in Chat oder Git. Ein eigener
Hostname braucht gegebenenfalls eine zusätzliche Netzwerkfreigabe. Bis dahin
funktionieren Sammlung und Erweiterungsprüfung mit gesperrten Einstiegen bei
fehlender Konzentration. Der Test mit drei Zyklen speicherte 15 Snapshots und
vermied 22 Wiederholungen während laufender RPC-Fehlerpausen; er endete korrekt
mit Status 2. Das beweist keine verlässliche Vollversorgung oder Profitabilität.

## Phase 1: RPC-Zugang prüfen

Der eigenständige Prüfbefehl öffnet keine Trading-Datenbank und erzeugt keine
Orders. Er prüft grundlegende Mint-/Account-Konzentrationsabfragen und dieselbe
Fallback-Logik wie der Collector. Die zusätzlichen Pool- und Halterprüfungen
aus Phase 3 sind nicht Teil dieses Verbindungstests:

```bash
python -m collectors.rpc_check --rounds 3 --interval 10 --out runtime/rpc-check-NEUER-NAME.json
```

Jede Runde benötigt frische Antworten; der Ergebnis-Cache ist dafür deaktiviert.
Fehlerpausen bleiben aktiv, damit abgewiesene Methoden nicht ständig erneut
angefragt werden. Der Bericht enthält Slots, Messzeitpunkte, Antwortzeiten,
Versuchszahlen und Fehler je Endpunkt/Methode. Er enthält nur Hostnamen, keine
vollständigen URLs, API-Schlüssel oder Anbieter-Fehlermeldungen. Die Fortschritte
erscheinen auf stderr, der vollständige JSON-Bericht auf stdout und optional in
`--out`. Vorhandene Berichte werden nicht überschrieben.

- Status **0** bedeutet: Jeder angeforderte Prüfpunkt lieferte auswertbare Daten.
- Status **2** bedeutet: Mindestens eine Prüfung blieb unvollständig, Slots waren
  rückläufig oder blieben bei mindestens fünf Sekunden Prüfintervall stehen,
  oder Konfiguration/Ausgabepfad waren ungültig. Spätere Erholung löscht einen
  früheren Fehler im Lauf nicht.
- `response_received` bei einer Methode bedeutet nur, dass eine RPC-Antwort
  einging. Erst `complete` beim Prüfpunkt bestätigt deren fachliche Validierung.
- Ein ungenutzter Ersatz-Endpunkt bleibt `not_exercised`. Eine erfolgreiche
  Stichprobe beweist weder Dauerverfügbarkeit noch genügend Kapazität für viele
  Coins. Simulierte Ausfälle werden zusätzlich in den Tests geprüft.

Standardmäßig dient ein zuvor beobachteter Token-2022-Mint als Prüfobjekt.
Mit wiederholtem `--token MINT_ADRESSE` lassen sich weitere Coins prüfen.
`probe_token_rejected` bedeutet, dass bereits die Token-Risikoprüfung den Abruf
der Halterdaten verhindert hat; dann einen anderen Prüf-Mint verwenden. Ein
gemessener hoher Konzentrationswert kann den Verbindungstest bestehen und
trotzdem einen Kauf blockieren. Der Prüflauf verändert keine Risikoschwellen.

Für einen eigenen Anbieterzugang:

1. Einen Solana-Mainnet-RPC wählen, dessen Tarif `getAccountInfo` mit Base64 und
   `getTokenLargestAccounts` tatsächlich erlaubt. Zunächst einen kostenlosen
   Tarif verwenden; dessen Leistungsumfang muss praktisch geprüft werden.
2. Die vollständige URL sicher als `SOLANA_RPC_URL` in den
   Umgebungseinstellungen oder der ignorierten `.env` hinterlegen. Keine
   Zugangsdaten in Chat, Git oder Kommandozeilenargumente einfügen.
3. Den Anbieter-Host bei eingeschränktem Cloud-Netzwerk gezielt freigeben.
   Einstellungen speichern; eine gespeicherte Konfigurationsvorlage alleine
   ist noch kein im laufenden Prozess verfügbarer Zugang.
4. Den Prüfbefehl ausführen. Danach mehrere begrenzte Collector-Läufe mit echten
   Kandidaten prüfen, bevor Phase 1 als abgeschlossen gilt.

Vor Einrichtung des eigenen Zugangs lieferten am 7. Oktober 2026 drei Prüfrunden
fortschreitende Mint-Slots, aber keine Halterdaten:
HTTP 429 bei Solana und HTTP 403 bei PublicNode. Von fünf Netzwerk-Anfragen
waren drei erfolgreich; vier weitere Versuche wurden während der Fehlerpausen
ausgelassen. Der Lauf endete korrekt mit Status 2. Der lokale Bericht liegt in
`runtime/rpc-check-20261007-phase1.json`. Alle 108 automatisierten Tests bestanden.

Nach Veröffentlichung der Umgebung ist der Helius-Zugang am 7. Oktober 2026
im laufenden Prozess verfügbar. Drei frische RPC-Prüfrunden lieferten gültige
Mint- und Konzentrationsdaten mit fortschreitenden Slots: sechs Requests,
sechs Erfolge, Status 0. Bericht: `runtime/rpc-check-helius-published-20261007.json`.
Auch der erste Collector-Lauf mit drei Zyklen und zehn Coins je Zyklus endete
ohne Datenfehler: 30 Snapshots, 54 erfolgreiche RPC-Requests, keine Trades.
Die 108 Tests bestanden auch nach dem Neustart der Cloud-Umgebung.

Ein zweiter Lauf nach Collector-Neustart setzte dieselbe Datenbank erfolgreich
fort: insgesamt 60 Snapshots zu 25 Coins, 60 Entscheidungen, keine Fills,
unverändert 50 USD Paper-Kapital. Beide Läufe endeten mit Status 0 und zusammen
108 erfolgreichen RPC-Requests. 54 Beobachtungen enthalten Konzentrationswerte;
sechs wurden bereits wegen einer Transfergebühren-Erweiterung gesperrt.
Datenbankintegrität: `ok`. Zusammenfassung:
`runtime/phase1-helius-validation-20261007.json`.

Damit ist die Grundprüfung von Phase 1 bestanden. Der Test war auf zehn Coins
je Zyklus begrenzt; weitere Kandidaten wurden zurückgestellt. Dauerbetrieb,
höhere Last und ein funktionierender öffentlicher Ersatz für die Halterabfrage
sind damit nicht nachgewiesen. Darauf baut Phase 2 mit zusätzlicher
Pool-Erkennung und nachvollziehbarer Beobachtung auf.

## Phase 2: Pool-Erkennung und nachvollziehbare Beobachtung

`collect` startet jetzt zusätzlich eine unabhängige Discovery-Aufgabe. Sie fragt
alle 20 Sekunden finalisierte Transaktionen des Raydium-CPMM-Gebührenkontos ab.
Ein Gebührenkonto-Treffer allein genügt nicht: Die Transaktion muss erfolgreich
sein und eine reguläre `initialize`-Instruktion des richtigen Programms mit dem
passenden Discriminator und Account-Layout enthalten. CPI-Instruktionen und
Version-0-Transaktionen mit geladenen Account-Adressen werden unterstützt.
Die Creator-Adresse bezeichnet den Pool-Ersteller, nicht bewiesenermaßen den
Token-Entwickler. Das ist keine Freigabe zum Handel.

Quellen für Programm-ID, Gebührenkonto und Account-Reihenfolge:
[Raydium lib.rs](https://github.com/raydium-io/raydium-cp-swap/blob/master/programs/cp-swap/src/lib.rs),
[Raydium initialize.rs](https://github.com/raydium-io/raydium-cp-swap/blob/master/programs/cp-swap/src/instructions/initialize.rs).
Die Referenzdateien wurden am 7. Oktober 2026 geprüft; ihre SHA-256-Werte stehen
im lokalen Validierungsbericht. Die öffentliche Transaktion in
`tests/fixtures/raydium_cpmm_initialize.json` ist ein echter Decoder-Testfall.

Die Abdeckung umfasst **reguläre Raydium-CPMM-Pool-Eröffnungen**. PumpSwap,
Raydium CLMM/AMM v4, permissionierte Initialisierungen und andere Programme sind
noch nicht als On-Chain-Quellen integriert. Die geprüfte PumpSwap-WebSocket-
Subscription war erreichbar, lieferte aber sehr viele gewöhnliche Trades und
wird in diesem Stand nicht dauerhaft betrieben. Es gibt keine Zusage, jeden
neuen Solana-Coin sofort zu entdecken. Finalisierung und Polling verzögern die
Erkennung; die tatsächliche Entdeckungslatenz neuer Live-Eröffnungen wurde noch
nicht gemessen.

Beim allerersten Start wird nur die jüngste Seite mit standardmäßig 20 Signaturen
geladen. Diese bewusst begrenzte Historie ist als `bootstrap_boundary` markiert.
Danach werden Cursor, angefangene Seitensuche und ausstehende Transaktionen
gespeichert. Nach Neustarts wird von dort weitergearbeitet. Pro Durchlauf werden
höchstens zwei Signaturseiten und zehn Transaktionen verarbeitet; ein Rückstand
bleibt sichtbar und wird später abgearbeitet. Fehlende Transaktionen werden mit
begrenzter Wiederholungsrate erneut angefragt. Die historische Verfügbarkeit
beim RPC-Anbieter ist keine Garantie; die Begrenzung am Erststart wird nicht als
vollständige Historie dargestellt.

Verifizierte Pool-Ereignisse bleiben einschließlich Signatur, Slot, Blockchain-
Zeit, lokaler Empfangszeit und Instruktion dauerhaft erhalten. Zu alte Pools
werden nicht neu in die aktive Beobachtung aufgenommen. Weder Blockchain-Zeit
noch nachgeladene Ereignisse werden als frühere lokale Kenntnis ausgegeben.
Für neue Kandidaten wird der entdeckte Pool bevorzugt; fehlt dessen DEX-Kurs,
wird die Lücke gespeichert. Übersprungene und illiquide Coins bleiben im Audit.

Kurse für bis zu 30 Tokens werden gemeinsam abgefragt. Die Empfangszeit steht
vor den nachfolgenden Risikoprüfungen fest. Vollständige Risikodaten können bis
zu 60 Sekunden wiederverwendet werden; ihr tatsächliches Alter bleibt erhalten.
Fehlerhafte Teilbefunde erlauben keine Einstiege. Diese Aufteilung senkt den
RPC-Aufwand, bedeutet aber auch, dass eine Änderung der Token-Eigenschaften
erst bei der nächsten Risikoprüfung auffällt.

`collection_attempts` hält erfolgreiche und fehlende Kursabrufe fest.
`collector_health` dokumentiert Start/Stop, Discovery-Fehler, Seitenfortschritt,
Kapazitätsgrenzen, Zyklusdauer und Kurslücken über dem 1,5-fachen Poll-Intervall.
Die Outcome-Fenster 30/60/120/300/900/3600 Sekunden bleiben bei unpassenden oder
fehlenden Folgebeobachtungen unbekannt. Werte werden nicht interpoliert.

```bash
python main.py collect --cycles 3 --db runtime/NEUER-PHASE2-LAUF.sqlite3 --log-file logs/phase2.log
python main.py status --db runtime/NEUER-PHASE2-LAUF.sqlite3
```

Status erst nach Ende des Collectors aufrufen. Er zeigt nun Pool-Ereignisse,
offene Discovery-Transaktionen, Abrufversuche, fehlende Kurse und aufgezeichnete
Kurslücken; die Statusabfrage erzeugt keinen neuen Handelslauf.

Einstellungen: `POOL_DISCOVERY_ENABLED=true`, `DISCOVERY_POLL_SECONDS=20`,
`DISCOVERY_PAGE_SIZE=20`, `DISCOVERY_PAGES_PER_POLL=2`,
`DISCOVERY_TRANSACTIONS_PER_POLL=10`. Mit `POOL_DISCOVERY_ENABLED=false` kann die
zusätzliche Quelle abgeschaltet werden; die übrige Sammlung bleibt verfügbar.

Zum Abschluss von Phase 2 bestanden 133 automatisierte Tests, einschließlich einer echten öffentlichen
Pool-Transaktion, CPI/v0-Decodierung, neuer Ereignisse nach dem Cursor,
Wiederaufnahme, fehlender Kurse, Ausfällen und unveränderter Statusabfragen.

Live-Validierung am 7. Oktober 2026: zwei Läufe einschließlich Neustart, jeweils
drei Zyklen mit maximal 30 Tokens. 37 Coins, 180 Abrufversuche, davon 176 Kurse
und vier fehlende Kurse; 180 gespeicherte Beobachtungen und Entscheidungen,
keine Fills, unverändert 50 USD Paper-Kapital. Die 20 anfänglichen Signaturen
ergaben 15 verifizierte Pool-Eröffnungen, drei fehlgeschlagene Transaktionen und
zwei sonstige Transaktionen. Es waren **nachgeladene Eröffnungen aus der jüngeren
Historie**, keine während des Tests neu entstandenen Pools. Der Neustart erzeugte
keine doppelten Ereignisse; kein Discovery-Rückstand blieb offen.

Keine On-Chain- oder Discovery-Fehler; wegen der fehlenden DEX-Kurse endeten beide
Läufe korrekt mit Status 2. Die Folgerunden benötigten etwa 0,1 bis 5,7 Sekunden
statt 20 bis 21 Sekunden für die anfänglichen Risikoprüfungen. Kapazitätsbedingte
Lücken sind weiterhin vorhanden und aufgezeichnet. Das ist kein Dauerlasttest
und kein Profitabilitätsnachweis. Bericht: `runtime/phase2-validation-20261007.json`.

## Phase 3: Pool- und Halterrisiken

Neue Collector-Beobachtungen verwenden `risk_version=3`. Ein Einstieg benötigt
jetzt überprüfte Pool-Konten und Halterdaten. Der bisherige Rohwert
`top10_account_fraction` bleibt zur Nachvollziehbarkeit gespeichert, entscheidet
aber nicht mehr über diese Einstiege. Ein unbekannter Pool, eine fehlgeschlagene
Prüfung oder nicht unterstützte Mechanik blockiert den Kauf.

Der Collector prüft Raydium-CPMM- und PumpSwap-Account-Layouts gegen die
Programm-ID. Er verifiziert Mint-Zuordnung, beide Token-Vaults, ihre berechnete
Pool-Authority, LP-Mint und Konfigurationskonto. Mint-Supply, Pool-Zustand,
Vault-Bestände und bis zu 20 zuvor ermittelte große Token-Accounts werden
gemeinsam mit `getMultipleAccounts` in einem Solana-Slot gelesen. Gegenüber
der vorausgehenden Auswahl sind höchstens 150 Slots Abstand zulässig.
Gefrorene Vaults, fremde Delegates/Close-Authorities, unbekannte Erweiterungen,
abgeschaltete Swaps und leere Reserven sperren den Einstieg. Aufgelaufene
Raydium-Protokoll-, Fonds- und Creator-Gebühren werden von den Reserven abgezogen.

Nur der Zieltoken-Vault des **tatsächlich verifizierten aktuellen Pools** wird
aus der Halterberechnung entfernt. Andere Pool-Konten bleiben konservativ
enthalten. Mehrere untersuchte Token-Accounts mit derselben Owner-Adresse
werden zusammengezählt. Die begrenzte Stichprobe wird nicht als vollständige
Halterliste ausgegeben:

- `N`: gesamte Token-Menge abzüglich des verifizierten Zieltoken-Vaults.
- `T`: Summe der zehn größten beobachteten Owner-Bestände außerhalb dieses Vaults.
- `R`: verbleibende, nicht beobachtete Menge außerhalb dieses Vaults.
- Konzentrations-Untergrenze: `T / N`; Obergrenze: `min(N, T + R) / N`.

Ein Einstieg verlangt, dass bereits die **Obergrenze höchstens 60 %** beträgt.
Unbekannte Bestände gelten dadurch nicht automatisch als gut verteilt. Auch ein
kleiner unbereinigter Top-10-Anteil kann zu einem blockierten Einstieg führen.
Diese Berechnung erkennt mehrere Accounts derselben Authority, aber keine
gemeinsame Kontrolle unterschiedlicher Wallet-Adressen.

Weitere Prüfungen und vorläufige Schwellen:

| Einstellung | Bedeutung |
| --- | --- |
| `REQUIRE_VERIFIED_HOLDER_RISK=true` | Marktdaten ohne die neuen Prüfdaten erlauben standardmäßig keinen Einstieg |
| `MAX_TOP10_OWNER_FRACTION=0.60` | Höchste erlaubte Konzentrations-Obergrenze außerhalb des geprüften Vaults |
| `MAX_CREATOR_OBSERVED_FRACTION=0.10` | Beobachtete Bestände des Pool-Erstellers und gegebenenfalls Protokoll-Coin-Creators über 10 % blockieren |
| `MIN_LP_NONREDEEMABLE_FRACTION=0.90` | Mindestens 90 % der im Pool geführten LP-Menge dürfen nicht als umlaufende LP-Token existieren |

Creator-Bestände sind eine **Untergrenze aus der Stichprobe**, kein Nachweis der
gesamten Entwicklerbestände. Der Pool-Ersteller oder Gebührenempfänger ist nicht
automatisch der Token-Entwickler; null beobachtete Bestände beweisen keinen
vollständigen Ausstieg. Die LP-Kennzahl lautet
`(Pool-LP-Menge − Mint-Supply) / Pool-LP-Menge` und umfasst Protokoll-Minimum sowie
verbrannte LP-Token. Noch existierende LP-Token werden auch in einem möglichen
Locker nicht als dauerhaft gesperrt angenommen. Eine hohe Kennzahl garantiert
weder dauerhafte Liquidität noch einen möglichen Verkauf.

Bekannte Raydium-Gebühren oberhalb der konfigurierten Paper-Gebühr blockieren
ebenfalls den Einstieg. **PumpSwap bleibt wegen nicht verifizierter dynamischer
Gebühren für Käufe gesperrt.** Virtuelle Reserven, besondere Modi und unbekannte
Felder werden zusätzlich ausgewiesen. Das Erkennen eines PumpSwap-Pools bedeutet
keine vollständige Unterstützung seiner Ausführung und erweitert nicht die
Raydium-Discovery aus Phase 2. Die Schwellen sind konservative Startannahmen,
keine durch Renditen optimierten oder bereits bewährten Handelsparameter.

Vollständige Account-Belege werden in `risk_evidence` einmal pro SHA-256-Hash
gespeichert. Snapshots enthalten Messwerte und den Hash-Verweis; die Speicherung
geschieht zusammen mit der Entscheidung in einer Transaktion. Belege enthalten
öffentliche Account-Bytes, Slot und RPC-Hostname, keine API-Schlüssel.
Die offizielle Referenz wurde am 7. Oktober 2026 geprüft:
[Raydium PoolState](https://github.com/raydium-io/raydium-cp-swap/blob/master/programs/cp-swap/src/states/pool.rs),
[Raydium AmmConfig](https://github.com/raydium-io/raydium-cp-swap/blob/master/programs/cp-swap/src/states/config.rs),
[PumpSwap IDL](https://github.com/pump-fun/pump-public-docs/blob/main/idl/pump_amm.json).
Quell-Hashes stehen im Validierungsbericht; öffentliche Account-Beispiele in
`tests/fixtures/*_risk_accounts.json` prüfen die Decoder.

Validierung: **167 Tests bestanden**. Zwei begrenzte Collector-Läufe mit jeweils
drei Zyklen und zehn Tokens je Zyklus speicherten insgesamt 60 Beobachtungen zu
38 Coins: 59 Kurse, eine Kurslücke, 29 vollständige Pool-/Halterbewertungen,
22 nicht unterstützte Pools und neun Beobachtungen ohne vollständige Halterdaten
(unter anderem bereits zuvor gesperrte Mints). Alle 60 Entscheidungen waren
`SKIP`; keine Fills, unverändert 50 USD Paper-Kapital. 217 RPC-Anfragen erhielten
erfolgreiche Antworten. Beide Läufe endeten korrekt mit Status 2: zuerst wegen
einer nicht unterstützten pausierbaren/Transfer-Hook-Erweiterung am Quote-Vault,
beim Neustart wegen des fehlenden DEX-Kurses. Vollständige Bewertung bedeutet
nicht, dass ein Pool die Risikogrenzen bestanden hat.

Die Belegspeicherung wurde vor dem zweiten Lauf ergänzt. Dessen 17 vollständige
Bewertungen haben gespeicherte Account-Belege; alle Hashes und berechneten
Merkmale wurden daraus erneut überprüft. Der erste Lauf bleibt unverändert
ohne nachträglich erfundene Belege. 300 gespeicherte Beobachtungen aus Phase 1–3
lassen sich weiterhin unverändert serialisieren. Bericht:
`runtime/phase3-validation-20261007.json`.

Der Backtest-Export übernimmt referenzierte Account-Belege in seine eingefrorene
Datenbank. Fehlende oder beschädigte Belege brechen den Import ab; alte
Beobachtungen ohne Beleg-Verweis bleiben lesbar. Die Kopie der 60 Live-
Beobachtungen erhielt alle 17 Belege und denselben Beobachtungs-Hash.

Historische Beobachtungen erhalten keine nachträglichen Phase-3-Merkmale.
Standardmäßige Markt-Replays blockieren deshalb alte Datensätze ohne diese
Prüfungen. Für ausdrücklich historische Forschung kann
`REQUIRE_VERIFIED_HOLDER_RISK=false` den alten Account-Grenzwert verwenden;
Beobachtungen mit `risk_version=3` behalten trotzdem die neuen Prüfungen.
Wallet-Cluster, Entwicklerhistorie, Wash Trading und Locker-Verifikation bleiben
offen. Die kurzen Läufe belegen weder Dauerbetrieb noch Profitabilität.

## Phase 4: Verzögerte Paper-Ausführung und Buchhaltung

`BUY` und `SELL` in `decisions` bedeuten jetzt einen **Order-Auftrag**, keinen
sofortigen Handel. Die Strategie erstellt einen Eintrag in `paper_orders`.
Ein Kauf reserviert sein am Signal festgelegtes USD-Budget und einen
Positionsplatz; ein Verkauf reserviert Fix-/Priority-Kosten. Reserviertes Geld
bleibt Teil des Cash-Bestands, ist aber für weitere Orders nicht verfügbar.
Pro Token kann höchstens eine Order ausstehen. Die Parameter werden bei der
Order-Erstellung eingefroren und über Neustarts unverändert übernommen.

Eine Ausführung benötigt einen **nach dem Signal empfangenen Kurs desselben
Pools** nach Ablauf der Mindestlatenz, auch wenn diese auf null gesetzt wurde.
Zusätzlich wartet der Bot auf die zugehörigen Risikoprüfungen. Ein früher
empfangener Kurs wird nicht nachträglich zum ausführbaren Folgekurs erklärt.
Sind die Daten beim Verarbeiten bereits zu alt oder die Order abgelaufen,
erfolgt kein Fill. Signalkurs, Signal-Snapshot, Ausführungskurs, späterer
Snapshot und beide Zeitpunkte bleiben getrennt nachvollziehbar.

| Einstellung | Standard | Bedeutung |
| --- | ---: | --- |
| `PAPER_LATENCY_SECONDS` | 1 | Mindestabstand zwischen Signal und nächstem ausführbarem Kurs |
| `PAPER_ORDER_TTL_SECONDS` | 120 | Order-Gültigkeit ab Signal |
| `PAPER_PRIORITY_FEE_USD` | 0,005 | Zusätzliche Kosten pro simulierter gelandeter Transaktion |
| `PAPER_FAILURE_PROBABILITY` | 0,02 | Angenommene Ausfallwahrscheinlichkeit einer Transaktion |
| `PAPER_MAX_ADVERSE_MOVE_BPS` | 1000 | Maximal 10 % ungünstige Kursbewegung seit dem Signal |
| `PAPER_SEED` | 7 | Reproduzierbare Fehlerentscheidung je Order |

Dazu kommen `FEE_BPS=30`, `SLIPPAGE_BPS=100`, `FIXED_FEE_USD=0.02` und ein
vereinfachter Preisimpact von ungefähr `2 × Orderwert / gemeldete Liquidität`.
Dies sind **Modellannahmen**, keine Messung tatsächlicher Solana-Gebühren oder
exakte Nachbildung einer AMM-Ausführung. Reale Reservekurven, Routing, MEV,
Transaktionsreihenfolge, Teilausführungen und SOL/USD-Gebührenumrechnung sind
nicht implementiert. Bei 20-Sekunden-Kursen dauert die modellierte Ausführung
meist deutlich länger als die konfigurierte Mindestsekunde.

Orders enden als `filled`, `failed`, `rejected`, `expired` oder `cancelled`.
Eine fehlende/illiquide Quote oder nicht zulässige Token-/Pool-Mechanik wird
vorab abgelehnt und kostet keine Transaktionsgebühr. Simulierte gelandete Fehler
und überschrittene Preisgrenzen kosten Fix-/Priority-Gebühren, aber keine
Swap-Gebühr. Zufallsentscheidungen hängen stabil von Seed und Order-Identität
ab; ein Neustart oder Datenbank-Rollback zieht kein günstigeres neues Ergebnis.
Die Risikodaten am späteren Kurs werden erneut geprüft. Auch ein Verkauf bleibt
unausgeführt, wenn seine Mechanik unbekannt oder nicht unterstützt ist.

Fehlgeschlagene Verkäufe lassen die Position offen. Ihre Kosten werden sofort
dem Trading-Kapital belastet und vor einer späteren Gewinnaufteilung vom
Handelsgewinn abgezogen. `Fill.realized_pnl` ist die aktuelle PnL-Buchung;
`net_trade_pnl` enthält bei vorherigen Verkaufsfehlern zusätzlich deren Kosten.
Diese früher gebuchten Kosten werden nicht ein zweites Mal vom Gesamt-PnL
abgezogen. Sogar bei Verkaufserlösen unterhalb der Fixkosten werden die vollen
Kosten berücksichtigt; Reserve und Owner-Profit dienen nicht zur Finanzierung.

`paper_ledger` hält jede abgeschlossene Order mit Cash-, Positionskosten-,
Reserve-, Owner- und PnL-Änderung fest. Geprüft wird:

`Änderung(Cash + Positions-Einstandskosten + Reserve + Owner) = Änderung(realisiertes PnL)`

Die Prüfung toleriert nur Decimal-Rundungsreste bis `1e-24` USD.
`status` zeigt `accounting.balanced`, reserviertes/verfügbares Cash, Order-Zustände
und Warnungen zu veralteten oder illiquiden Positionsbewertungen. Ein erkannter
Buchhaltungswiderspruch verhindert einen weiteren Engine-Start. Beim ersten
Start mit einer älteren Datenbank wird deren vorhandene Wallet als Ausgangspunkt
übernommen; alte Fills und Gewinne werden nicht neu berechnet.

Während der Collector läuft, verfallen Orders auch bei ausgefallenen Kursabrufen.
Beim Prozessstopp werden ausstehende Orders gespeichert; beim Wiederanlauf
werden abgelaufene Orders freigegeben, gültige Orders warten weiter. Es gibt
keinen Hintergrundprozess, der nach einem begrenzten Lauf weiterarbeitet.
Offene Positionen werden am Ende eines Laufs nicht automatisch verkauft.

Paper-Modus und Replay verwenden dieselbe Ausführungs- und Kostenfunktion.
Der Replay verarbeitet Kurse und später bekannte Risikomerkmale zeitlich
geordnet; zusätzliche Collector-Verzögerungen können seine Ergebnisse gegenüber
dem tatsächlichen Paper-Lauf unterscheiden. Bestehende Backtest-Ergebnisdateien
bleiben erhalten; neue Läufe dokumentieren den geänderten Code-Hash.

Validierung: **187 Tests bestanden**, darunter spätere Fills, Reservierung,
Neustarts mit eingefrorenen Parametern, veränderte Risikodaten, fehlgeschlagene
Verkäufe, vollständige Gebühren bei kleinen Erlösen, unveränderte Kapitalregeln,
Order-Verfall bei Ausfällen, atomarer Rollback und identische Paper-/Replay-
Fills bei derselben synthetischen Kursfolge. Die aktualisierte Demo hat
18 Beobachtungen, zwei spätere Fills und eine ausgeglichene Buchhaltung;
Wiederholung erzeugt keine weiteren Fills. Das ist eine Funktionsprüfung,
kein Profitabilitätsnachweis. Bericht: `runtime/phase4-validation-20261007.json`.

Der ergänzende Live-Datentest am 7. Oktober 2026 umfasste zwei Zyklen und einen
weiteren Zyklus nach Neustart, jeweils maximal zehn Tokens: 30 Beobachtungen,
keine Orders/Fills, unverändert 50 USD Paper-Kapital. Beide Prozesse endeten mit
Status 2: im ersten Lauf fehlten drei DEX-Paarantworten, im zweiten blockierte
eine pausierbare Vault-Erweiterung die vollständige Prüfung. Eine weitere
empfangene Paarantwort enthielt keinen numerischen Preis. Alle 110 RPC-Anfragen
lieferten Antworten; das bedeutet keine erfolgreiche fachliche Prüfung aller
Tokens. Datenbankintegrität und Buchhaltung waren korrekt. Da kein Live-Signal
die Filter bestand, belegen hier die synthetischen Tests die Ausführung.

## Paper Wallet und Kapitalregeln

- Start: 50 USD Trading-Kapital, 0 USD News-Reserve, 0 USD Owner-Profit.
- Positive **realisierte Nettogewinne nach simulierten Handelskosten** werden aufgeteilt.
- Solange das Trading-Kapital unter 100 USD liegt: 80 % Trading, 20 % Reserve.
- Darüber: 60 % Trading, 20 % Reserve, 20 % Owner-Profit.
- Ein Gewinn, der die Grenze überschreitet, wird in zwei Anteile geteilt. Beispiel:
  99 USD Kapital + 10 USD Gewinn → 105,25 USD Trading, 2 USD Reserve,
  1,75 USD Owner-Profit. Die Grenze ist damit klar und reproduzierbar definiert.
- Verluste belasten das Trading-Kapital. Reserve und Owner-Profit werden nicht
  zum Nachschießen verwendet. Owner-Profit ist eine simulierte Buchung;
  eine Auszahlungsfunktion gibt es nicht.
- Unter 5 USD geschätztem Trading-Kapital wird `DEAD` dauerhaft gespeichert.
  Neue Einstiege enden; noch vorhandene Positionen dürfen weiter geschlossen werden.

`cash_usd` enthält auch reserviertes Geld; `available_cash_usd` zieht bestehende
Order-Reservierungen ab. `estimated_trading_equity_usd` addiert
geschätzte Liquidationserlöse offener Positionen und schließt Reserve/Owner-Profit
aus. Letzte Kurse können veralten oder bei fehlender Liquidität unerreichbar sein.
Der Wert ist keine Garantie für einen ausführbaren Verkauf. Fehlende Liquidität
führt zu einem protokollierten, nicht ausgeführten Ausstiegsversuch und einer
weiterhin offenen Position.

Geld und Mengen werden mit `Decimal` gerechnet; die Anzeige rundet auf Cent,
die Datenbank bewahrt die Genauigkeit. Standardmäßig werden je Seite 30 Basispunkte
Gebühr, 100 Basispunkte Slippage, 0,02 USD Fixkosten sowie die in Phase 4
beschriebenen Priority-Kosten und der vereinfachte Preisimpact simuliert. Das sind
konfigurierbare Annahmen, keine aktuellen Solana-/DEX-Gebührenmessungen.

## Daten und Auswertung

Live-Daten liegen standardmäßig in `runtime/paper.sqlite3`, Demo-Daten in
`runtime/demo.sqlite3`. Ein Schutz verhindert, dass beide Quellen dieselbe
Datenbank verwenden. Laufzeitdaten und Logs werden nicht versioniert.

```bash
python main.py status --source demo
python main.py status
```

Statusabfragen erst nach dem Anhalten des Collectors ausführen, da eine
Prozesssperre parallele Zugriffe über die CLI verhindert.

| Tabelle | Inhalt |
| --- | --- |
| `tokens` | Erste lokale Entdeckung und Discovery-Quelle |
| `pool_events` | Verifizierte Pool-Eröffnungen mit On-Chain- und Empfangszeit |
| `chain_scan_state` | Persistenter Cursor und Fortschritt einer begonnenen Seitensuche |
| `chain_transactions` | Signaturen, Verarbeitungszustand, Wiederholungen und Transaktionsbelege |
| `collection_attempts` | Jeder versuchte Kursabruf, einschließlich fehlender Kurse |
| `collector_health` | Discovery-Ausfälle, Neustarts, Grenzen und zeitliche Lücken |
| `snapshots` | Empfangszeit, Pool, Kennzahlen, Rohdaten und On-Chain-Prüfung |
| `risk_evidence` | Öffentliche Account-Belege für Pool-/Halterprüfungen, nach SHA-256 dedupliziert |
| `decisions` | BUY/HOLD/SELL/SKIP mit Gründen, Signalzeit und Konfiguration des Laufs |
| `paper_orders` | Order-Aufträge, Reservierungen, eingefrorene Parameter und terminaler Ausführungszustand |
| `paper_ledger` | Buchungsbeleg je erledigter Order, einschließlich Fehlerkosten und Verfall |
| `fills` | Simulierter Entry/Exit, Preis, Menge, Kosten, Netto-PnL und Snapshot-Bezug |
| `wallet` | Dauerhafter Kontostand und offene Positionen |
| `outcomes` | Spätere Beobachtungen nach 30/60/120/300/900/3600 Sekunden |
| `runs` | Verwendete Parameter pro Start |

Auch übersprungene Coins erzeugen Snapshots und Folgebeobachtungen. Ein Label
verweist auf die erste später empfangene Beobachtung desselben Pools ab dem
Zielzeitpunkt. Zulässige Verzögerung: maximal 30 Sekunden oder 10 % des Horizonts,
je nachdem, was größer ist. Fehlende Zeitfenster bleiben `NULL`; die tatsächliche
Verzögerung wird gespeichert. Beispiel für nachvollziehbare Renditelabels:

```sql
SELECT o.snapshot_id, o.horizon_seconds, o.delay_seconds,
       CAST(f.price AS REAL) / CAST(s.price AS REAL) - 1 AS observed_return
FROM outcomes o
JOIN snapshots s ON s.id = o.snapshot_id
JOIN snapshots f ON f.id = o.future_snapshot_id;
```

Die Strategie liest nur die aktuelle und bereits gespeicherte vorherige
Beobachtung. Spätere Labels verändern frühere Entscheidungen nicht.
DEX-Aggregate können trotzdem verzögert sein: Ihre tatsächliche Eventzeit ist
unbekannt; `received_at` ist der Zeitpunkt, zu dem wir die Antwort erhalten haben.

Live-Paper-Modus und Replay warten seit Phase 4 auf spätere Quotes und deren
Risikoprüfungen und berücksichtigen Kosten-/Ausfallszenarien.
Phase 3 speichert einzelne verifizierte AMM-Reserven;
deren Preiswirkung, Tick-Daten und historische Transaktionsausführung werden
noch nicht als Ausführungsmodell nachgebildet. Beide Modelle sind Forschungswerkzeuge.

## Chronologischer Backtest

```bash
python -m backtesting --db runtime/paper.sqlite3 \
  --out runtime/backtests/my-first-run
```

Der Backtester liest ausschließlich gespeicherte Snapshots aus der Quelldatenbank
und startet pro Szenario mit einer neuen 50-USD-Paper-Wallet. Er verändert keine
Live-Positionen und liest weder spätere Renditelabels noch gespeicherte
Entscheidungen. Eine eingefrorene Kopie der Eingabebeobachtungen wird zusammen
mit Quell-/Code-Hashes gespeichert. Vorhandene Ergebnisordner werden nicht
überschrieben. Es gibt keine Parameteroptimierung anhand der Ergebnisse.

| Annahme | Basis | Stress |
| --- | ---: | ---: |
| Mindestlatenz | 1 Sekunde | 5 Sekunden |
| Slippage je Seite | 100 Basispunkte aus Standardkonfiguration | 300 Basispunkte |
| Priority Fee je Versuch | 0,005 USD | 0,02 USD |
| Angenommene Transaktionsausfälle | 2 % | 10 % |
| Maximal tolerierte ungünstige Preisbewegung seit Signal | 10 % | 5 % |
| Order-Gültigkeit | 120 Sekunden | 120 Sekunden |

Die normalen Gebühren/Fixkosten kommen hinzu (Standard: 30 Basispunkte und
0,02 USD je Seite). Der Zufallsseed ist standardmäßig 7 (`--seed` zum Ändern);
seit Phase 4 wird daraus eine stabile Fehlerentscheidung je Order abgeleitet.
Alle Werte sind Szenarioannahmen und stehen vollständig in `result.json`.
`--scenario baseline` oder `--scenario stress` begrenzt den Lauf auf ein Szenario.

Ein Signal entsteht erst, wenn seine On-Chain-Prüfdaten bekannt sind. Seine Order
darf erst an einer **später empfangenen Quote desselben Pools** nach der
Mindestlatenz und nach Abschluss ihrer Risikoprüfung ausgeführt werden. Damit beträgt die effektive Verzögerung bei
20-Sekunden-Daten oft deutlich mehr als eine Sekunde. Am Signal werden Budget
und verfügbare Positionsplätze reserviert. Doppelte oder widersprüchliche
Beobachtungsschlüssel werden beim Einlesen zurückgewiesen.

Zusätzlich zur Slippage berücksichtigt das Modell einen vereinfachten Impact
aus Ordergröße und gemeldeter Pool-Liquidität. Das setzt einen ausgeglichenen
Constant-Product-Pool voraus und bildet konzentrierte Liquidität nicht exakt ab.
Bei Daten-/Liquiditätslücken wird kein Fill erfunden. Simulierte fehlgeschlagene
Transaktionen kosten Fix-/Priority Fees; abgelehnte Vorabprüfungen kosten nichts.
Ohne weitere Quote bleibt eine Order am Datenende unausgeführt. Offene Positionen
werden nicht automatisch zum letzten Kurs glattgestellt.

Ergebnisdateien:

- `notes.md`: lesbares Ergebnisprotokoll und Grenzen der Aussagekraft.
- `result.json`: Parameter, Datenqualitätsprofil und vollständige Kennzahlen.
- `input.sqlite3`: verwendete Eingabebeobachtungen und referenzierte Account-Belege zur Reproduktion.
- Je Szenario `orders.csv`, `fills.csv`, `equity.csv`, `decisions.json`.

`win_rate_pct` ist ohne abgeschlossene Trades `null`; der Profit Factor ist ohne
Verlustnenner ebenfalls `null`. Equity und Drawdown beruhen auf letzten
beobachteten Kursen; bei offenen Positionen sind sie Schätzungen. Reserve und
Owner-Profit zählen zum Gesamtvermögen, aber nicht zum Trading-Kapital.

Am 6. Oktober 2026 wurden Basis und Stress auf einer neu aufgenommenen Stichprobe
mit **33 Beobachtungen, 22 Coins und rund 191 Sekunden Dauer** ausgeführt.
Beide ergaben 33 SKIPs, keine Orders und unverändert 50 USD. 28 Beobachtungen
hatten ein nicht unterstütztes Token-Programm, bei fünf fehlten On-Chain-Checks.
Die elf wiederholt beobachteten Pools hatten jeweils über 120 Sekunden Abstand.
Das ist ein überprüfbarer technischer Replay, **kein Profitabilitätsnachweis**.
Ergebnisse: `runtime/backtests/2026-10-06-market-round-1/`.

Für reine Funktionsprüfungen mit synthetischen Daten ist eine ausdrückliche
Kennzeichnung erforderlich:

```bash
python -m backtesting --db runtime/demo.sqlite3 \
  --out runtime/backtests/synthetic-example --allow-demo
```

Diese Ergebnisse dürfen nicht als Marktergebnisse oder unbekannte Testdaten
interpretiert werden. Ein belastbarer Test braucht historische Risikomerkmale,
engmaschige Kurse/Liquidität, verschwundene Pools und getrennte unbekannte
Zeiträume über mehrere Tage und Marktphasen.

## Phase 6: Getrennter Testzeitraum und Kostensensitivität

Die Phase-6-Werkzeuge sind implementiert; eine belastbare Strategieprüfung fehlt
weiterhin, weil die mehrtägige Datensammlung aus Phase 5 noch nicht erfolgt ist.
Bereits bei der Entwicklung betrachtete Daten werden nicht nachträglich zu
einem unabhängigen Test erklärt. Es gibt keine Parameteroptimierung oder
Auswahl eines besonders günstigen Seeds.

`backtesting.evaluation` bietet drei getrennte Befehle. Jeder Ausgabeordner muss
neu sein. Quelldatenbanken werden ausschließlich lesend geöffnet. Mehrere
Dateien werden anhand von Token, Pool und Empfangszeit zusammengeführt;
identische Kopien zählen nur einmal, widersprüchliche Beobachtungen führen zum
Abbruch. Die ursprünglichen Dateipfade und Zeilen-IDs bleiben erhalten.
Demo- und Marktdaten dürfen nicht gemischt werden.

Eine Diagnose vorhandener Daten:

```bash
python -m backtesting.evaluation diagnose \
  --db runtime/phase3-collector-20261007.sqlite3 \
  --db runtime/phase4-collector-20261007.sqlite3 \
  --out runtime/backtests/NEUE-PHASE6-DIAGNOSE
```

Sie friert die Eingaben samt Account-Belegen ein und testet Basis- und
Stressannahmen mit jeweils den festen Seeds **7, 17 und 29**. Jedes Szenario
beginnt mit 50 USD. Basiswerte stammen aus der aktuellen Konfiguration. Im
Stressfall werden Fixkosten verdoppelt, Slippage mindestens verdreifacht
(höchstens 9999 bps; mindestens 300 bps), Priority-Kosten mindestens vervierfacht
(mindestens 0,02 USD), Latenz mindestens verfünffacht (mindestens fünf Sekunden)
und die Ausfallannahme auf mindestens 10 % gesetzt. Die ungünstige Preisgrenze
wird auf höchstens 5 % begrenzt. Bereits höhere Basis-Kosten werden dabei nicht
unbeabsichtigt abgesenkt. Vollständige Parameter stehen in `result.json`.

Die Seeds verändern nur modellierte Transaktionsausfälle. Sie sind **keine
unabhängigen Marktstichproben**. Auch verschiedene Tokens können stark
korreliert sein. Orders, Fills, Entscheidungen und Equity-Verlauf werden je
Szenario/Seed exportiert. Ein zusätzlicher Cash-Vergleich bleibt ohne Orders bei
50 USD. Offene Positionen werden nicht zwangsverkauft, und fehlende Beobachtungen
werden nicht interpoliert. Spätere Outcome-Tabellen werden nicht gelesen.

Einen zukünftigen Test vorher festlegen:

```bash
python -m backtesting.evaluation prepare \
  --db runtime/paper.sqlite3 \
  --out runtime/backtests/NEUES-PHASE6-PROTOKOLL
```

`prepare` speichert Entwicklungsdaten, Code-Hash, Strategieparameter,
Kostenannahmen, Seeds, Qualitätsregeln und ein **zukünftiges siebentägiges
Zeitfenster**. Standardstart ist die nächste UTC-Mitternacht nach einer
einstündigen Sperrfrist. `--test-start` benötigt einen Zeitstempel mit Zeitzone;
`--days` erlaubt längere Fenster, mindestens drei Tage. Ein zurückdatierter
Teststart oder Teststart vor schon bekannten Entwicklungsdaten ist unzulässig.
Mindestens eine Stunde Abstand verhindert, dass noch laufende Entwicklungs-
Beobachtungsfenster in den Test hineinreichen.

Nach dem Ende dieses Fensters:

```bash
python -m backtesting.evaluation evaluate \
  --protocol runtime/backtests/NEUES-PHASE6-PROTOKOLL/protocol.json \
  --db runtime/paper.sqlite3 \
  --out runtime/backtests/NEUE-PHASE6-AUSWERTUNG
```

Vorher meldet der Befehl `WAITING_FOR_WINDOW_END` und öffnet die angegebenen
Testdaten nicht. Nachher werden nur Beobachtungen mit Empfang **ab Testbeginn
und vor Testende** verwendet, deren Risikomerkmale ebenfalls vor Testende
bekannt waren. Kein früherer Kurs, Signal oder Wallet-Zustand wird übernommen.
Eine neue 50-USD-Wallet beginnt je Szenario ohne Historie. Neue Quelldatenbanken
können mit weiteren `--db`-Argumenten ergänzt werden.

Geänderter Code oder veränderte eingefrorene Entwicklungsdaten führen zum
Abbruch. Nach Änderungen an Strategie, Collector oder Ausführung ist ein neues
Protokoll mit neuem zukünftigen Fenster nötig. Die lokalen Hashes schützen vor
unbemerkten Änderungen, sind aber keine signierte Vorregistrierung und kein
Beweis, dass niemand Testdaten außerhalb dieses Werkzeugs angesehen hat.
Das Erstellen eines Protokolls startet **keinen Collector oder Zeitplan**.

Vorläufige Mindestanforderungen für eine fachliche Überprüfung:

- Daten an mindestens drei Tagen; mindestens 80 % der Fünf-Minuten-Intervalle
  im festgelegten Fenster enthalten wenigstens einen numerischen Kurs.
- Mindestens 95 % der Beobachtungen enthalten einen Preis; mindestens 95 %
  der bepreisten Beobachtungen besitzen die aktuelle Risiko-Version.
- Jede vollständige Halterbewertung besitzt ihren Account-Beleg; mindestens
  30 Pools haben Folgekurse. Höchstens 10 % der aufeinanderfolgenden Kurse
  desselben Pools liegen mehr als die zulässigen 120 Sekunden auseinander.
- Jedes Kosten-/Seed-Szenario hat mindestens 100 abgeschlossene Trades in
  mindestens 20 verschiedenen Tokens. Offene Positionen oder am Datenende
  unausgeführte Orders verhindern eine vollständige Beurteilung.

Diese Grenzen sind konservative Forschungsanforderungen, keine statistische
Poweranalyse. Ein belegtes Fünf-Minuten-Intervall ist auch kein Nachweis einer
vollständigen Kursversorgung aller Pools. `REVIEWABLE_HOLDOUT` bedeutet lediglich,
dass diese Vorprüfungen bestanden sind; es ist keine Profitabilitätsbestätigung
und keine Freigabe für echtes Trading. `INSUFFICIENT_EVIDENCE`,
`SYNTHETIC_ONLY` und `WAITING_FOR_WINDOW_END` liefern Status 2;
`PROTOCOL_PREPARED` und `REVIEWABLE_HOLDOUT` liefern Status 0.

Am 7. Oktober 2026 wurden alle sieben ursprünglichen Marktdatenbanken gemeinsam
diagnostisch ausgewertet: **400 Beobachtungen zu 136 Coins**, verteilt auf zwei
Kalendertage. Nur **9 von 261 Fünf-Minuten-Intervallen** enthielten einen Kurs.
391 Beobachtungen hatten einen Preis, davon 85 die aktuelle Risiko-Version;
40 vollständige Halterbewertungen enthielten 28 gespeicherte Account-Belege.
Fehlende historische Belege wurden nicht nachträglich erfunden.
Kein Datensatz bestand sämtliche heutigen Einstiegsprüfungen. Alle sechs
Szenarien ergaben null Orders/Trades, null realisiertes PnL und 50 USD Cash.
Das Resultat lautet korrekt **INSUFFICIENT_EVIDENCE**.

Prüfspur:

- `runtime/backtests/phase6-development-verified-20261007/result.json`
- `runtime/backtests/phase6-development-verified-20261007/notes.md`
- `runtime/backtests/phase6-protocol-20261007/protocol.json`
- `runtime/phase6-validation-20261007.json`

Das vorbereitete zukünftige Fenster läuft vom **8. Oktober 2026, 02:00 Uhr,
bis 15. Oktober 2026, 02:00 Uhr (Europe/Zurich; Ende exklusiv)**. Eine vorzeitige
Prüfung bestätigte die Sperre; es wurden keine zukünftigen Gewinne ausgewertet.
Zum Zeitpunkt dieser Phase-6-Prüfung lief noch keine dauerhafte Sammlung.
**202 Tests bestanden**,
einschließlich Dubletten/Konflikten, Quellen-Trennung, dünner Zeitabdeckung,
unveränderter Quellen, Zukunftsgrenzen, verspäteten Risikomerkmalen, gesperrter
Frühauswertung, Code-/Protokolländerungen und reproduzierbaren Szenarien.

## Mehrtägige Beobachtungssammlung

`operations.campaign` sammelt echte DEX-Kurse, öffentliche Solana-Risikodaten,
Account-Belege und Folgekurse in einer eigenen SQLite-Datenbank. Es erzeugt
keine Paper-Orders und keine echten Trades. Die Strategie wird während des
vorab festgelegten Testfensters nicht ausgewertet. Fehlende Kurse, verspätete
Beobachtungen und unvollständige Risikoprüfungen bleiben sichtbar.

Die Kampagne `runtime/campaigns/market-20261007` ist bis zum
**15. Oktober 2026, 03:00 Uhr Europe/Zurich** eingerichtet. Das sind sieben Tage
des vorbereiteten Testfensters plus Vorlauf und eine Stunde für Folgekurse.
Die Endzeit ist kein Nachweis, dass der Rechner bis dahin durchläuft.

Status, Stoppen und ausdrückliches Wiederaufnehmen:

```bash
cd /workspace/MemeCoin-tading_bot
/workspace/.venvs/memecoin/bin/python -m operations.campaign status \
  --directory runtime/campaigns/market-20261007
/workspace/.venvs/memecoin/bin/python -m operations.campaign stop \
  --directory runtime/campaigns/market-20261007
/workspace/.venvs/memecoin/bin/python -m operations.campaign start \
  --directory runtime/campaigns/market-20261007
```

`stop` fordert einen geordneten Abschluss an. `start` entfernt eine vorhandene
Stop-Anforderung und setzt dieselbe Datenbank fort; eine zweite parallele
Instanz wird abgewiesen. Ein abgelaufenes Zeitfenster lässt sich nicht verlängern.
Eine neue Sammlung benötigt ein neues Verzeichnis und eine Endzeit mit Zeitzone:

```bash
python -m operations.campaign init --directory runtime/campaigns/NEUE-SAMMLUNG \
  --until 2026-10-15T01:00:00Z --max-tokens 10
python -m operations.campaign start --directory runtime/campaigns/NEUE-SAMMLUNG
```

Die Endzeit muss beim Anlegen in den nächsten 14 Tagen liegen; das Datum im
Beispiel gegebenenfalls anpassen. Im Manifest stehen die eingefrorenen
Einstellungen und Software-Hashes, jedoch keine RPC-URLs oder API-Schlüssel.
RPC-Zugangsdaten stammen weiterhin aus der aktuellen Umgebung.

Der Supervisor ersetzt beendete Collector-Prozesse, begrenzt jeden Lauf auf
90 Zyklen und startet einen seit fünf Minuten hängenden Collector neu. Nach
fünf Starts ohne abgeschlossenen Zyklus stoppt er mit Fehlerstatus. Er beendet
die Sammlung außerdem bei der Endzeit, einer Stop-Anforderung oder weniger
als 2 GiB freiem Speicher. Ein Prozess kann laufen, obwohl ein Anbieter keine
Kurse liefert; diese Schutzmaßnahmen garantieren keine vollständige Abdeckung.

`status` zeigt deshalb zusätzlich die Zahl gültiger Preise, den Zeitpunkt des
letzten gültigen Kurses, abgeschlossene Zyklen, fehlende Abfragen und verfügbare
Folgekurse. Der letzte Zyklus enthält Fehlerzahlen und verschobene Tokens.
Standardmäßig werden höchstens zehn Tokens pro Zyklus mit einem Zielabstand
von 20 Sekunden bearbeitet; neu entdeckte Pools werden alle 60 Sekunden gesucht.
Die Watchlist rotiert. Einzelne Coins werden daher seltener als alle 20 Sekunden
beobachtet, und langsame APIs verlängern den Zyklus. Die Abdeckung umfasst nur
die unterstützten Quellen und Pools, nicht alle neuen Meme-Coins.

Dateien im Kampagnenverzeichnis:

- `observations.sqlite3`: Originalbeobachtungen und Prüfspur.
- `state.json`: aktueller Betriebszustand, letzter Zyklus und letzte Sicherung.
- `manifest.json`: Endzeit, Einstellungen und Code-Hashes.
- `backups/observations-0.sqlite3` und `observations-1.sqlite3`: zwei wechselnde,
  mit SQLite-Backup erstellte und auf Integrität geprüfte Sicherungen. Die erste
  entsteht nach einem abgeschlossenen Zyklus, weitere ungefähr stündlich und
  beim geordneten Stoppen. Eine Sicherung wird bei Platzmangel ausgelassen und
  als Fehler im Status vermerkt.
- `logs/`: rotierende Collector- und Supervisor-Logs, jeweils höchstens vier
  Dateien von ungefähr 5 MB.

Die RPC-Zähler summieren die vom Collector gemeldeten Zyklen. Bei einem Absturz
vor einer Meldung fehlen dessen letzte Anfragen; die Zahlen sind keine
Anbieter-Abrechnung. Bestehende API-Limits gelten weiter. Es wird kein
kostenpflichtiger Tarif gebucht.

**Diese Codex-Maschine hat keinen eingerichteten Autostart- oder Weckdienst.**
Der Hintergrundprozess übersteht das Schließen der aufrufenden Shell, aber
keinen Stopp oder eine Pause der ganzen Maschine. Ein Neustart kann mit `start`
fortsetzen; vergangene Datenlücken werden nicht nachträglich erfunden. Nach
einem absichtlichen `stop` soll ein späterer Agent erst auf ausdrücklichen
Wunsch fortsetzen. Für unterbrechungsfreien Betrieb wird ein dauerhaft laufender
Host benötigt. Lokale Sicherungen schützen nicht vor Verlust der ganzen
Cloud-Umgebung; sie liegen auf derselben Maschine.

Die Sammlung bricht bei geänderten Quellcode-Hashes ab. Änderungen an Strategie,
Collector oder Ausführung erfordern zusätzlich ein neues zukünftiges
Phase-6-Protokoll. Das Betriebsmodul wird separat im Kampagnenmanifest erfasst;
die bestehenden Phase-6-Code-Hashes wurden dafür nicht verändert.

Nach Ende des Testfensters können die tatsächlich gesammelten Daten mit dem
bereits vorbereiteten Protokoll ausgewertet werden:

```bash
python -m backtesting.evaluation evaluate \
  --protocol runtime/backtests/phase6-protocol-20261007/protocol.json \
  --db runtime/campaigns/market-20261007/observations.sqlite3 \
  --out runtime/backtests/phase6-holdout-20261015
```

Für eine konsistente Kopie während der laufenden Sammlung die SQLite-Backup-API
verwenden, nicht nur die Hauptdatei kopieren: neuere Daten können noch im WAL
liegen. Vor dem 15. Oktober um 02:00 Uhr Schweizer Zeit verweigert das Werkzeug
die Auswertung. Eine erfolgreiche Sammlung allein belegt noch keine rentable
Strategie.

Beim Startcheck am 7. Oktober 2026 um 18:26 Uhr Schweizer Zeit lief der
Collector mit 94 Beobachtungen zu 40 Tokens, davon 92 mit Preis. Es lagen
44 Account-Belege für 45 vollständige Halterbewertungen vor. Einzelne
fehlende Kurse und unvollständige Risikoprüfungen waren sichtbar. Stoppen,
Wiederaufnehmen ohne Änderung der 56 zuvor gespeicherten Beobachtungen,
Doppelstart-Sperre und Sicherungsintegrität wurden geprüft. **218 Tests
bestanden.** Dies ist ein Startcheck, noch kein mehrtägiges Ergebnis.
Prüfspur: `runtime/campaigns/market-20261007/initial-validation.json`.

## Installation auf einem eigenen Debian-VPS

Die eigenständige VPS-Einrichtung steht in [deploy/ANLEITUNG.md](../deploy/ANLEITUNG.md).
Sie nutzt Python 3.13, einen eigenen Benutzer und einen systemd-Dienst. Programm,
Zugangsdaten und Daten liegen getrennt unter `/opt`, `/etc` und `/var/lib`.
Bestehende Projekte werden nicht konfiguriert oder neu gestartet. Die Datenbank
des VPS beginnt separat; vor dem bestätigten Datenfluss die Cloud-Sammlung
weiterlaufen lassen. Erst danach wird die Cloud-Instanz gezielt gestoppt.

Der Dienst nutzt `operations.service` als Vordergrundprozess und lässt sich mit
`systemctl` verwalten. `Restart=on-failure` ist begrenzt; `KillMode=mixed` lässt
dem Supervisor Zeit, den Collector und seine Sicherung geordnet zu beenden.
Eine Stop-Anforderung oder ein abgelaufenes Sammelfenster wird auch beim
Serverneustart respektiert. Bestehende Kampagnen werden bei verändertem
Dienst-Hash oder anderer Endzeit nicht stillschweigend übernommen.

Ein Paket mit Quellcode, Tests, Installationsanleitung und eingefrorenem
Phase-6-Protokoll erstellen:

```bash
PYTHONPATH=. python scripts/build_vps_bundle.py --out /tmp/memecoin-vps-NEU.tar.gz
```

Das Paket enthält ausschließlich aufgelistete Dateien; laufende Datenbanken,
virtuelle Umgebungen, Logs und Zugangsdaten bleiben außen vor. SHA256SUMS
ermöglicht die Prüfung vor Installation. Der Helius-Schlüssel wird erst lokal
auf dem VPS verdeckt eingegeben. Diese Vorbereitung ist keine Bestätigung,
dass das Paket bereits auf einem externen Server installiert wurde.

## Korrigierter Beobachtungsplan R2 (8. Oktober 2026)

Die VPS-Ausgabe zeigte 23.012 Beobachtungen, davon nur 18.541 mit Preis, sowie
1.380 belegte Ein-Stunden-Fenster bei 17.113 bereits fälligen Fenstern. Ein
reproduzierter Planungsfehler trug dazu bei: die bisherige rotierende Watchlist
entfernte Coins 66 Minuten nach der ersten Entdeckung, obwohl spätere Kurse noch
eigene Ein-Stunden-Folgefenster benötigten. Alte Daten und Software bleiben zur
Nachvollziehbarkeit erhalten; sie werden nicht nachträglich repariert.

R2 verwendet explizite, gespeicherte Beobachtungsphasen: höchstens acht Coins,
eine Neuaufnahme alle zwölf Minuten, 30 Minuten Ausgangsbeobachtungen pro Coin,
anschließend Nachbeobachtung bis 66 Minuten nach dessen letztem Ausgangskurs.
Nachbeobachtungen erfüllen vorhandene Outcome-Fenster, erzeugen keine weiteren
Fenster und erlauben keine neuen Einstiege im Replay. Fehlende Kurse bleiben
sichtbar; die Kriterien für ein geeignetes Token oder belastbare Evidenz werden
nicht abgeschwächt. Coins ohne verfügbaren Kurs werden nicht vorzeitig aus ihrer
festgelegten Anfangsphase entfernt. Verfügbarkeit und unbekannte Pool-Mechaniken
können weiterhin erhebliche Lücken verursachen.

Die API-Last wird durch wiederverwendete Risikoergebnisse mit ursprünglichen
Zeitstempeln sowie ein dauerhaftes Budget begrenzt: 70.000 RPC-Versuche pro
UTC-Tag und 600.000 insgesamt. Dies ist ausdrücklich kein Helius-Creditlimit.
Das neue Konto des Sammlers kennt weder Anbietergewichte noch den Verbrauch
anderer Projekte. Fehlgeschlagene Abfragen und Ausweichversuche zählen mit.

Eine aus der Batch-Antwort verschwundene, festgelegte Pool-Adresse wird zusätzlich
über die Token-Paare-Abfrage gesucht; der Pool wird nicht still gewechselt.

Das neue Protokoll `runtime/backtests/phase6-protocol-r2-20261008/protocol.json`
legt den Zeitraum 9.–16. Oktober 2026, jeweils 02:00 Uhr Europe/Zurich, fest.
Die Sammlung endet einschließlich Nachbeobachtung am 16. Oktober um 03:06 Uhr.
Eine vorzeitige Leistungsbewertung bleibt gesperrt. Nach Änderungen an diesem
Code ist wieder ein neues zukünftiges Protokoll erforderlich.

Die konkreten Update- und Rückkehrschritte stehen in
[deploy/UPDATE-R2.md](../deploy/UPDATE-R2.md). Das Update testet vor der Umschaltung,
behält das bisherige Programm und alle Daten, verwendet die vorhandene private
RPC-Konfiguration und bestätigt neue Kurse. Die bisherigen Abschnitte über
die Erstinstallation und das alte Testfenster beschreiben den älteren Stand.

Das Updatepaket `memecoin-update-20261008-v3.tar.gz` ergänzt eine deutsche
Statusübersicht: nach der Installation im neuen Programmverzeichnis
`.venv/bin/python -m deploy.status` ausführen. Sie liest lokale Daten und
zeigt Betriebszustand, Datenabdeckung und Anfragebudget; zusätzliche
Helius-Abfragen oder Änderungen am eingefrorenen Sammelplan entstehen nicht.
Optional lässt sich danach [Telegram einrichten](../deploy/TELEGRAM.md): ein
Tagesbericht ab 09:00 Uhr Schweizer Zeit und Meldungen über Betriebsstörungen.
Die Zugangsdaten werden erst auf dem VPS eingegeben; diese Ergänzung sendet
ohne Einrichtung keine Nachrichten und nimmt keine Handelsbefehle entgegen.

## Nächste Ausbauschritte

Die [Phase-7-Betriebsprobe](../operations/PHASE7.md) ist vorbereitet: echte
Unterprozessabbrüche bei offener virtueller Order und Position, Wiederanlauf,
SQLite-Sicherung und Wiederherstellung werden mit künstlichen Kursen geprüft.
Aufruf: `python -m operations.paper_rehearsal --out runtime/NEUE-PHASE7-PROBE`.
Das ist technische Vorbereitung; ein dauerhafter Paper-Dienst mit echten
Marktdaten ist noch nicht gestartet. Das v3-VPS-Update bleibt unverändert.

Inzwischen ist auch der [eigenständige Paper-Dienst](../operations/PAPER-SERVICE.md)
implementiert: eigener Datenbestand, begrenzte Laufzeit, Neustart, Sicherungen,
Wiederherstellung und lesbarer Status. `operations.paper_service init` verwendet
standardmäßig künstliche Daten. Der Marktdatenmodus verlangt einen geprüften,
passenden Phase-6-Bericht nach dem vollständigen Beobachtungsfenster. Die
systemd-Vorlage ist noch nicht auf dem VPS installiert.

Die [Telegram-Ergänzung für Paper](../operations/PAPER-TELEGRAM.md) meldet virtuelle
Ausführungen, offene Positionen, Fehler und einen Tagesbericht. Sie liest nur
den Paper-Datenbestand und speichert bestätigte Zustellfortschritte separat.
`python -m operations.paper_notify --directory runtime/MEIN-PAPER-DEMO
--state runtime/MEIN-PAPER-VERSAND/state.json` zeigt standardmäßig nur eine
Vorschau; echter Versand benötigt ausdrücklich `--send`. Die laufende
Beobachtungssammlung und ihr Telegram-Dienst werden dadurch nicht geändert.

1. Phase 5: über mehrere Tage nachvollziehbare Beobachtungen und vollständige Outcome-Fenster sammeln.
2. Phase 6: das vorbereitete Werkzeug nach tatsächlicher Datensammlung und Ende eines gültigen Testfensters fachlich auswerten.
3. Phase 7: überwachten, dauerhaften Paper-Betrieb mit Ausfall- und Qualitätskontrollen aufbauen.
4. Phase 8: ML nur ergänzen, wenn es die einfache Baseline auf unbekannten Daten verbessert.
5. Phase 9: mögliche echte Ausführung nur nach ausdrücklicher Freigabe; kostenpflichtige News erst aus tatsächlichen Gewinnen.

Parallel bleiben breitere Pool-Abdeckung, Entwickler-/Wallet-Cluster und genauere
Ausführung anhand tatsächlicher AMM-Daten Forschungsaufgaben.
