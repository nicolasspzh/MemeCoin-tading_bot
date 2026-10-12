# Vollständige Projektübergabe an Claude

Erstellt am **12. Oktober 2026**, Benutzerzeitzone **Europe/Zurich**.
Diese Übergabe enthält den vorhandenen Projektstand, Gesprächsentscheidungen,
Betriebskontext, Grenzen und offene Arbeit. Maßgebliche technische Details sind
zusätzlich im vollständigen Quellcode und den Anleitungen des Pakets enthalten.
Sie ist kein vollständiges Wortprotokoll aller früheren Chats und keine aktuelle
Kopie des entfernten Servers.

## 1. Unbedingt zuerst verstehen

- Ziel: einen Solana-Meme-Coin-Bot nachvollziehbar entwickeln, mit echten
  Beobachtungen prüfen und erst danach über weitere Betriebsstufen entscheiden.
- Aktuell **kein Echtgeldhandel**. Keine Signierung, Wallet-Schlüssel oder
  Live-Order-Funktion vorhanden. `Settings.mode` akzeptiert nur `PAPER`.
- **Aktiv auf dem VPS:** reiner R2-Beobachtungssammler mit eigenem Telegram-Monitor.
- **Lokal implementiert:** Paper-Engine, Replay/Auswertung, eigenständiger
  Paper-Dienst, Paper-Telegram, Berichtsrenderer, zusätzliche Einstiegsvarianten.
- Ein implementierter Dienst ist nicht automatisch auf dem VPS installiert.
- Die Strategie ist **nicht nachweislich profitabel**. Synthetische Gewinne
  und bestandene Tests sind kein Marktbeleg.
- R2 ist ein eingefrorener Vergleich. Sein Code, seine Parameter, Daten und
  Zeitgrenzen dürfen nicht nachträglich verändert oder Ergebnisse erfunden werden.
- Die Cloud-Sammlung wurde gestoppt. Nicht als zweiten Sammler neu starten.
- Am Übergabetag 12. Oktober liegt **kein neuer VPS-Status** vor. Der jüngste
  vom Benutzer gezeigte Status stammt vom 10. Oktober 2026 um 16:23:16 CEST.

## 2. Zusammenarbeit und Zugänge

Der Benutzer ist Nicolas, spricht Deutsch, verwendet Codex im Browser und ist
bei SSH/Linux noch Anfänger. Er arbeitet an Windows-Rechnern, nutzt PowerShell
und WinSCP. Im Büro konnte er zeitweise keine Downloads durchführen. Kurze,
konkrete Schritte sind hilfreich. Bei Befehlen das Ziel nennen: Windows-PC,
SSH-Konsole des VPS oder lokale Entwicklungsmaschine. Keine unnötigen
Bestätigungsrunden. Vorhandene Arbeit und Daten erhalten.

Repository: https://github.com/nicolasspzh/MemeCoin-tading_bot

- Branch: `main`.
- Verifizierter GitHub-Commit: `73fa133e3903628b568532a049253572f61e5297`.
- 103 versionierte Dateien, circa 693 KB unkomprimierter Quell-/Dokumentationsstand.
- Der Upload ist erfolgreich abgeschlossen; früher gab es 403-Fehler durch
  ein falsches Konto und fehlende Schreibrechte. Dies ist kein aktueller Blocker.
- GitHub-Zugriff ist nicht automatisch in Claudes Umgebung eingerichtet.
- `Projekt/` ist eine vollständige Quellkopie dieses Commits, ohne `.git`.
  Bei Bedarf das Repo selbst klonen und vor Änderungen den Commit vergleichen.
- Die Originalumgebung liegt unter `/workspace/MemeCoin-tading_bot`.
  Diese Pfade sind keine Garantie für die Dateistruktur einer neuen Umgebung.

Zugangsdaten sind **nicht beigefügt**. Keine Schlüssel aus `.env`, Serverdateien
oder Umgebungsvariablen in Chat/Logs/Git übernehmen. GitHub-Upload ist kein
Server-Deployment. Keine fremden Dienste oder Firewall-Einstellungen ändern.

## 3. VPS: bestehender Betrieb

Vom Benutzer mitgeteilter Server: netcup VPS 500 G12.5, Debian 13 „trixie“
minimal, x86_64, Python 3.13.5. Anfangsmessung: 2 CPUs, 3,8 GiB RAM,
62-GB-Rootdateisystem, damals kein Swap. Darauf läuft zusätzlich das Projekt
Velincoin (`velincoind` und ein Python-Prozess wurden gesehen). Nicht anfassen.

Letzte bekannte SSH-Adresse: `159.195.4.228`.
Hostname: `v2202610432958534592`.
Benutzer nutzte `root`. Diese Angaben sind aus dem Gespräch, kein aktueller
Erreichbarkeitstest. IP ist keine Zugangserlaubnis für eine neue Agentenumgebung.

Windows-PowerShell, vom Benutzer selbst:

```powershell
ssh root@159.195.4.228
```

Passworteingabe bleibt unsichtbar. Passwörter nicht im Chat erfragen. Nach dem
Einloggen nur den Status lesen:

```bash
cd /opt/memecoin-collector-r2
.venv/bin/python -m deploy.status
```

Relevante Pfade und Dienste:

| Zweck | Pfad/Name |
| --- | --- |
| Aktueller R2-Code | `/opt/memecoin-collector-r2` |
| Aktuelle R2-Sammlung | `/var/lib/memecoin-collector/campaign-r2` |
| Beobachtungen | `campaign-r2/observations.sqlite3` |
| Sammlerlog | `campaign-r2/logs/collector.log` |
| Sicherungen | `campaign-r2/backups/` |
| Manifest/Zustand | `campaign-r2/manifest.json`, `state.json` |
| systemd-Sammler | `memecoin-collector.service` |
| RPC-Konfiguration | `/etc/memecoin-collector/collector.env`, privat |
| Telegram-Konfiguration | `/etc/memecoin-collector/telegram.env`, privat |
| Sammler-Telegram | `memecoin-telegram.service`, `memecoin-telegram.timer` |
| Alter R1-Code | `/opt/memecoin-collector` |
| Alte R1-Daten | `/var/lib/memecoin-collector/campaign` |

Die alten Daten wurden nicht gelöscht. Alte Installations-/Updateordner und
Archive unter `/root` sind nicht der laufende Programmordner. Nicht eigenmächtig
aufräumen. Originalsammlung und Sicherungen zuerst zuordnen und bewahren.

Weitere reine Lesebefehle, nur bei Bedarf:

```bash
systemctl --no-pager --full status memecoin-collector
tail -n 40 /var/lib/memecoin-collector/campaign-r2/logs/collector.log
journalctl -u memecoin-collector -n 40 --no-pager
systemctl list-timers --all --no-pager
```

SSH und WinSCP können geschlossen werden; systemd führt den Dienst weiter.
Ein WinSCP-Arbeitsbereich ist nur die lokale Bedienoberfläche, nicht der Sammler.

Die Vorlage begrenzt den Sammler auf 512 MiB RAM, weiche Grenze 384 MiB und
50 % **eines** CPU-Kerns, mit `Nice=10`, höchstens 32 Tasks und eingeschränkten
Dateisystemrechten. Supervisor-Neustarts sind begrenzt. Stop-Marker und
abgelaufenes Zeitfenster werden respektiert; kein unbegrenzter Dauerbetrieb.

## 4. Letzter bestätigter Fortschritt, keine heutige Live-Messung

**10.10.2026, 16:23:16 CEST**, vom Benutzer gepostet:

| Messwert | Wert |
| --- | --- |
| Prozess | aktiv, Lebenszeichen vor 6 Sekunden |
| Beobachtungen | 63'773 |
| Coins mit Beobachtungen | 232 |
| Mit Kurs / ohne Kurs | 62'765 / 1'008; gerundet 98,4 % mit Kurs |
| Letzter Kurs | vor 9 Sekunden |
| Orders / Fills | 0 / 0 |
| Folgekurse 30 s | 19'939 / 19'940 bereits fällige |
| Folgekurse 60 s | 19'937 / 19'938 |
| Folgekurse 120 s | 19'932 / 19'932 |
| Folgekurse 300 s | 19'913 / 19'914 |
| Folgekurse 900 s | 19'836 / 19'836 |
| Folgekurse 3600 s | 19'489 / 19'491 |
| Beobachtungsgruppen | 2 primary, 6 followup, 225 abgeschlossen |
| RPC heute UTC | 18'131 / 70'000 |
| RPC gesamte Sammlung | 57'698 / 600'000 |
| Backup | 10.10.2026 16:08:29 CEST, Integrität ok |
| Freier Speicher | 53,2 GiB |
| Qualitätsflag | `data_degraded=true` |

Gruppen und einzigartige Coins sind unterschiedliche Zähleinheiten. Gerundete
100,0 % bedeuten nicht, dass jede Beobachtung vollständig ist. „Due“ bezeichnet
bereits fällige Fälle und ist nicht einfach die Zahl noch ausstehender Kurse.

Frühere Vergleichspunkte: am 9. Oktober 08:55 Uhr 20'070 Beobachtungen/77 Coins;
am selben Tag 20:32 Uhr 36'478/134. Diese Werte dürfen nicht zu einer aktuellen
Messung hochgerechnet oder als Gewinnbeleg benutzt werden.

Am 9. Oktober zeigten Logs `Watch capacity reached` mit etwa 25–29 zurückgestellten
Tokens **pro Runde** und `Pool discovery incomplete` mit vorgemerkten Wiederholungen.
Das sind teilweise dieselben Kandidaten; Rundenzahlen nicht aufsummieren.
Ein aktueller Flag allein identifiziert nicht alle Ursachen. Bekannte Folgekurse
sind nahezu vollständig, die Auswahl neuer Coins ist jedoch begrenzt/verzerrt.

Helius Free hatte laut Benutzer am 9. Oktober 92'732 / 1'000'000 Credits genutzt.
Das ist veraltet. **RPC-Versuche sind keine Credits**; Methode, Tarif und andere
Projekte beeinflussen den Verbrauch. Neues Dashboard abfragen, nicht schätzen,
wenn das Kontingent für eine Entscheidung benötigt wird.

## 5. Architektur und Datenfluss

1. DEX-Screener-Profile und Solana-Transaktionen liefern mögliche Kandidaten.
2. Eine Beobachtungsplanung wählt Coins/Pools mit begrenzter Kapazität aus.
3. DEX-Kurse und Marktdaten werden mit Solana-Mint-/Holder-/Poolprüfungen kombiniert.
4. SQLite speichert Beobachtungen, Risikobelege, Abrufversuche, fehlende Kurse
   und spätere Folgekurse. Herkunft und Zeitpunkte bleiben nachvollziehbar.
5. Im laufenden Beobachtungsmodus protokolliert `Recorder` nur `SKIP/observation_only`.
6. Die separate Paper-Engine entscheidet, reserviert virtuelle Mittel und
   simuliert Ausführungen erst bei einer späteren passenden Beobachtung.
7. Replay/Auswertung lesen Beobachtungen, nicht die vorhandene Wallet oder
   zukünftige Outcome-Labels als Signale. Berichte bewerten Daten und Simulation.

| Bereich | Maßgebliche Dateien |
| --- | --- |
| CLI, Sammelzyklus, Einzelschreiber | `main.py` |
| Typisierte Parameter | `config/settings.py`, `.env.example` |
| Datenmodelle/SQLite | `data/models.py`, `data/database.py` |
| HTTP/DEX | `collectors/http.py`, `collectors/dexscreener.py` |
| Solana RPC/Mint/Token-2022 | `collectors/solana.py`, `collectors/mint.py` |
| Pool-Erkennung/Holder | `collectors/pools.py`, `collectors/holders.py` |
| Kohorten/Anfragebudget | `collectors/schedule.py` |
| Handelsentscheidungen/Risiko | `trading/strategy.py`, `trading/risk.py` |
| Wallet/Ausführungsmodell/Buchhaltung | `trading/paper_wallet.py`, `execution.py`, `engine.py` |
| Kampagne/systemd-Vordergrundprozess | `operations/campaign.py`, `operations/service.py` |
| Replay/Protokoll/Evaluation | `backtesting/replay.py`, `backtesting/evaluation.py` |
| Bestehende Serveranzeige/Telegram | `deploy/status.py`, `deploy/telegram_notify.py` |
| Neuer Paper-Betrieb | `operations/paper_service.py`, `paper_feed.py` |
| Neue Paper-Nachrichten | `operations/paper_notify.py` |
| Bericht/Experimente | `operations/evaluation_report.py`, `entry_variants.py` |

SQLite verwendet WAL und Fremdschlüssel. Wichtige Tabellen: `metadata`, `runs`,
`tokens`, `snapshots`, `decisions`, `fills`, `wallet`, `outcomes`, `risk_evidence`,
`paper_orders`, `paper_ledger`, `collection_attempts`, `collector_health`,
`observation_tracks`, `rpc_request_budget`. Weitere Discovery-Tabellen sind
im Schema enthalten. JSON-Payloads sind über Pydantic typisiert.
Token/Pool/Empfangszeit ist die Beobachtungsgranularität, nicht nur der Ticker.
Decimal-Geldbeträge werden als Strings gespeichert. Einzelschreiber-Sperren,
atomare Transaktionen, Reservierungen und idempotente Verarbeitung verhindern
reguläre Doppelbuchungen. Das ist keine Garantie gegen jeden Host-/Speicherausfall.

## 6. Datensammlung und Grenzen der Quellen

- DEX Screener: Preis, Liquidität, Volumen/Transaktionszahlen, Profile und Paare.
  Profile sind **kein vollständiger Marktstream**. FDV ist nicht Market Cap.
- On-chain Discovery erkennt reguläre Raydium-CPMM-Eröffnungen; kein universeller
  Stream aller Launchpads, Pools oder Chains. Kein WebSocket-Poolindexer vorhanden.
- Pool-/Holderprüfung unterstützt konkrete Raydium-CPMM-/PumpSwap-Layouts und
  zulässige Zustände; nicht jeder erkannte Token/Pool wird dadurch handelbar.
- Slot-Abstände und einzelne Prüfzeitpunkte bleiben sichtbar. Zu weit
  auseinanderliegende Slots verhindern Konzentrationsberechnungen.
- Cache höchstens 60 Sekunden; Risikoprüfungen behalten originale Zeitstempel.
- RPCs sind lesend auf erlaubte Methoden begrenzt; keine Send-Transaction-Methode.
- Fallbacks werden methodenweise bevorzugt/pausiert. HTTP 429 pausiert mindestens
  60 Sekunden, 401/403 mindestens fünf Minuten; Retry-After kann verlängern.
- Fehlende Preise, verschwundene Pools, API-Ausfälle und unbekannte Zustände
  bleiben als Lücken sichtbar. Keine nachträglichen Ersatzkurse erfinden.
- Kontoinhaber sind keine nachgewiesenen Personen. Wallet-Cluster, vollständige
  Dev-Bestände, Wash Trading, Unique Buyers und Whale-Tracking fehlen weiterhin.

Netzwerkziele: `api.dexscreener.com`, `mainnet.helius-rpc.com`, optionale öffentliche
RPCs `api.mainnet-beta.solana.com` und `solana-rpc.publicnode.com`; für Telegram
`api.telegram.org`. Bestehende RPC-URL ist privat konfiguriert. Keine Notwendigkeit,
für lokale Demos/API-freie Tests Anbieterzugänge anzufordern.

## 7. R2-Plan und einzuhaltende Zeiten

R2 ersetzt den früheren R1-Plan, der Tokens zu früh aus der Beobachtung entfernte.
Neue Kurse spät aufgenommener Zeitpunkte hatten dadurch keine volle Nachbeobachtung.
R1-Daten blieben erhalten und werden nicht nachträglich „repariert“.

- Höchstens 8 gleichzeitig aktive Beobachtungsplätze.
- Höchstens eine Neuaufnahme alle 720 Sekunden (12 Minuten).
- 1'800 Sekunden Ausgangsbeobachtung pro Coin.
- Nachbeobachtung bis 3'960 Sekunden nach dem letzten Ausgangskurs.
- Fester Pool je Kohorte. Fehlender Kurs entfernt einen Coin nicht sofort.
- Folgekurse erfüllen vorhandene Labels, erzeugen keine endlosen neuen Fenster
  und erlauben keine neuen Replay-Einstiege. Ausstiege bleiben möglich.
- Reihenfolge nach Entdeckung/Adresse, nicht nach späteren Gewinnen.
- Zielzyklus 20 Sekunden; Discovery alle 120 Sekunden, bis zu 4 Transaktionen
  pro Discovery-Poll. Standardparameter des generischen Collectors sind teilweise
  anders: die R2-Parameter aus dem Protokoll verwenden, nicht nur Defaults.
- Persistentes Limit: 70'000 RPC-Versuche je UTC-Tag, 600'000 je Sammlung;
  einschließlich Fehlversuchen und Fallbacks, vor dem Senden verbucht.
- Folgekurshorizonte: 30, 60, 120, 300, 900 und 3'600 Sekunden.
- Zulässiger Zuordnungszeitspielraum: mindestens 30 Sekunden bzw. 10 % des Horizonts.

| Ereignis | UTC | Schweizer Zeit |
| --- | --- | --- |
| Beginn Testfenster | 09.10.2026 00:00 | 09.10.2026 02:00 CEST |
| Ende Testfenster, exklusiv | 16.10.2026 00:00 | 16.10.2026 02:00 CEST |
| Ende Sammlung mit Nachbeobachtung | 16.10.2026 01:06 | **16.10.2026 03:06 CEST** |

Der Evaluator sperrt vor dem Testfensterende. Der Paper-Marktstart verlangt
zusätzlich die 66 Minuten Nachbeobachtung. Für den vereinbarten Ablauf die finale
Auswertung ebenfalls erst nach **03:06 Uhr** mit vollständiger Sicherung beginnen.
Keine vorgezogene Auswertung über manipuliertes `now` oder geänderte Uhrzeiten.

## 8. Eingefrorene Referenzen und Paketinhalt

Fingerprint des Protokollplans (kanonischer JSON-Inhalt):
`a3069969150f38ea8739e55f929b5fffcd819867bee6dbf238ccf9f0e44396f9`

SHA-256 der tatsächlichen `protocol.json`-Datei:
`57b2ade6df31ac96b38a2805851405c10f2efd072edbbac11625e1735618ed61`

Kern-Fingerprint aus `code_digest()`:
`8dcc53e9b17e18bfa1d5c2ac10facbd0bc1cc8b75dea61064c55589f29a5b9bd`

Dateihash `development.sqlite3`:
`99dd24accc6fd4428ce870a1e05a654e3a1f59e1beb667742fa1f71fe1c77363`

Unverändertes v3-Paket:
`4483d005818421a416da9431b3012613ada1e6230ecc5dffc627388a774b40e4`

Historisches Retry-Skript:
`1be0d910dfcffaab48d7e1991aaf6cd6aa65684104ba1cba0c15c544e7290aa8`

Plan-Hash, Dateihash und Code-Fingerprint sind verschiedene Dinge. Nicht
„korrigieren“, weil zwei dieser Werte unterschiedlich aussehen.
`code_digest()` umfasst `main.py`, `requirements.txt`, `pyproject.toml` und
Python-Dateien in `backtesting`, `trading`, `collectors`, `config`, `data`.
Auch reine Formatänderungen dort würden den Fingerprint ändern.
Kampagnen-/Paper-Manifeste prüfen zusätzliche Betriebsdateien separat.

Paketstruktur:

- `START-FUER-CLAUDE.md`: direkt verwendbarer Startauftrag.
- `UEBERGABE.md`: diese Beschreibung; enthält private Betriebszuordnung wie VPS-IP.
- `Projekt/`: unveränderter GitHub-Quellstand mit allen versionierten Anleitungen.
- `R2-Referenz/`: originales Protokoll und eingefrorene **Entwicklungsdaten**.
  Das ist **nicht** die aktuelle R2-VPS-Sammlung und kein unbekannter Holdout.
- `Historische-Pakete/`: ursprüngliches v3-Paket und Retry-Skript zur Referenz.
  Nicht erneut installieren oder ausführen. Archive nicht unkontrolliert über
  den aktuellen Quellstand entpacken.
- `PARAMETER-R2.json`, `PRUEFUNG.json`, `SHA256SUMS`: maschinenlesbare Referenz
  und Paketprüfung.

Diese Übergabe und ihre lokalen Daten **nicht automatisch öffentlich auf GitHub
laden**. Das bisherige Repository schließt Betriebsdaten und Zugangsdaten aus.
Die Paket-Referenzdateien dürfen getrennt geprüft werden; ein neuer Klon allein
enthält sie nicht. `deploy/release.json` verweist historisch auf einen `runtime/`-
Pfad; die Paketdateien hier liegen bewusst außerhalb von `Projekt/`.

Prüfung in einer eingerichteten Python-Umgebung, Arbeitsverzeichnis `Projekt/`:

```bash
python -c 'from pathlib import Path; from backtesting.evaluation import load_protocol; print(load_protocol(Path("../R2-Referenz/protocol.json"))["sha256"])'
```

Das prüft den unveränderten Code und die eingefrorene Entwicklungsreferenz,
wertet aber **keine aktuellen Marktergebnisse** aus. `deploy.release_check`
ist dafür ungeeignet, weil es eine Installation vor dem zukünftigen Fenster
prüft und dieses Fenster am Übergabetag bereits begonnen hat.

## 9. Bestehende Handelsregeln, nicht mit Varianten verwechseln

Startwallet: 50 virtuelle USD. Standardmäßig maximal 3 Positionen; geplante
Käufe zählen beim Limit mit. Pro Einstieg höchstens 5 % des geschätzten
Trading-Kapitals, begrenzt durch freies, nicht reserviertes Cash und die
zulässige Poolbeteiligung von 0,1 %.

Entry verlangt insbesondere:

- Frische Kurse/On-chain-Prüfungen, höchstens 120 Sekunden alt, nicht zukünftig.
- Liquidität mindestens 10'000 USD, 5-Minuten-Volumen mindestens 1'000 USD.
- Zulässige Token-Mechanik, keine aktive/unklare Mint- oder Freeze-Authority.
- Verifizierte Holder-/Pooldaten für Marktdaten; konservative Top-10-Owner-Grenze
  60 %, beobachteter Creator-Anteil maximal 10 %, verifizierter nicht einlösbarer
  LP-Anteil mindestens 90 %. Unbekannte Zustände sind keine Freigabe.
- Unterstützte Token-2022-Metadatenerweiterungen sind möglich; andere/unbekannte
  oder transferrelevante Erweiterungen bleiben gesperrt. Keine Rugpull-Garantie.
- Poolalter im Standard zwischen 60 Sekunden und 24 Stunden; das ist nicht
  automatisch das Tokenalter.
- Zwei zeitlich passende Kurse desselben Pools (10 bis 120 Sekunden Abstand),
  mindestens 1 % Anstieg; mindestens 10 Käufe und Kauf-/Verkaufsverhältnis 2:1.
- Followup-only-Beobachtungen dürfen keine neuen Positionen eröffnen.

Ausstiegsgründe: 12 % Stop-Loss, 25 % Take-Profit, 10 % Trailing Stop,
maximal 900 Sekunden Haltedauer, Verkaufsdruck, Liquiditätsrückgang unter 65 %
der vorherigen Beobachtung, Risikofunde oder DEAD-Wallet. Fehlende aktuelle
Verkaufskurse erzeugen keine erfundene Ausführung. Unbekannte Mechanik kann
einen Verkauf verhindern. Ein Stop ist deshalb keine Verlustgarantie.

Walletbuchhaltung und Gewinnverteilung:

- Unter 5 USD geschätztem Trading-Kapital wird `dead` dauerhaft gesetzt;
  neue Einstiege enden, bestehende Positionen können noch geschlossen werden.
- Positive realisierte Gewinne werden marginal verteilt: bis 100 USD
  Trading-Kapital 80 % Kapital/20 % News-Reserve; darüber 60 % Kapital,
  20 % News-Reserve, 20 % Eigentümeranteil.
- Verluste greifen nicht automatisch auf Reserve/Eigentümeranteil zu.
- News-Reserve ist bislang ein virtuelles Buchungskonto, **kein News-Abonnement**.
- Buchwert, reserviertes Cash, realisiertes Ergebnis und geschätztes Vermögen
  sind verschiedene Größen. Gesamtvermögen kann Reserven enthalten.

## 10. Paper-Ausführung und realistische Grenzen

Persistente Order, Kapitalreservierung, frühester Zeitpunkt nach Latenz, Ablauf
ohne Kurs und Ausführung an einem **späteren** Kurs desselben Pools. Kein Fill
am Signalpreis, auch nicht bei konfigurierter Null-Latenz. Prüfungen und
Entscheidungen haben getrennte Verfügbarkeitszeiten.

Baseline-Annahmen: 30 Basispunkte Gebühr (0,3 %), 100 Basispunkte Slippage (1 %),
0,02 USD Fixgebühr und 0,005 USD Prioritätsgebühr; 1 Sekunde Latenz,
120 Sekunden Orderablauf, 2 % simulierte Fehlerwahrscheinlichkeit, Grenze für
nachteilige Bewegung 1'000 Basispunkte. Preiseinfluss hängt vom Verhältnis
Notional/Liquidität ab. Diese Werte sind Modelle, keine gemessene AMM-Ausführung.

Reproduzierbarer Zufallswert aus Order-/Token-/Zeit-/Seed-Daten. Gebühren
fehlgeschlagener Versuche werden berücksichtigt. Risiko-/Liquiditätsprüfungen
vor Ausführung können blockieren. Buchungsbelege werden auf Bilanzgleichheit
geprüft. Wiederanlauf darf keine Doppelorders oder Doppelbuchungen erzeugen.
Ende der Daten liquidiert Positionen nicht fiktiv; offene Risiken bleiben sichtbar.

## 11. Phase-6-Auswertung

`backtesting.evaluation` bietet `prepare`, `diagnose`, `evaluate`.
Bestehendes R2-Protokoll nicht neu erzeugen. Vorzeitige `diagnose` der laufenden
R2-Daten könnte Strategieauswahl beeinflussen und ist nicht vereinbart.

Festgeschriebene Kostenvarianten: baseline und stress, Seeds 7, 17, 29,
also sechs Läufe desselben Datensatzes. Stress erhöht Kosten, Verzögerung und
Ausfallwahrscheinlichkeit. Kein bester Seed wird herausgepickt; Seeds sind
keine sechs unabhängigen Marktstichproben.

Vorab festgelegte Evidenzanforderungen:

| Anforderung | Schwelle |
| --- | --- |
| Beobachtete Tage | mindestens 3 |
| Aktive 5-Minuten-Abschnitte | mindestens 80 % |
| Preisabdeckung | mindestens 95 % |
| Moderne Risikodaten bei Kursen | mindestens 95 % |
| Anteil langer Lücken desselben Pools | höchstens 10 % |
| Paare mit Folgekursen | mindestens 30 |
| Abgeschlossene Trades je Lauf | mindestens 100 |
| Verschiedene Coins mit abgeschlossenen Trades je Lauf | mindestens 20 |

Weitere Hindernisse: unvollständige Kontobelege, offene Positionen,
unerledigte Orders, keine Beobachtungen, synthetische oder vorher bekannte Daten.
Große Zahl von Snapshots bedeutet nicht viele unabhängige Trades oder geeignete
Tokens. Token-Renditen können korreliert sein. Kein automatisches Lockern der
Schwellen bei zu wenig Evidenz. Die Regeln sind Forschungsanforderungen, keine
statistische Poweranalyse.

`REVIEWABLE_HOLDOUT` = zur inhaltlichen Prüfung geeignet, **keine Gewinn-/Livefreigabe**.
Positive Nettoergebnisse sind separat ausgewiesen, nicht automatisch garantiert.
`INSUFFICIENT_EVIDENCE` und `SYNTHETIC_ONLY` sind reguläre ehrliche Ergebnisse.

Erst nach Sammelende und konsistenter Sicherung, auf der Analysemaschine im
Projektordner (DB-Pfad ersetzen, neuen Ausgabeordner verwenden):

```bash
python -m backtesting.evaluation evaluate \
  --protocol ../R2-Referenz/protocol.json \
  --db /PFAD/ZUR/KONSISTENTEN-VPS-SICHERUNG.sqlite3 \
  --out runtime/r2-auswertung-NEU
python -m operations.evaluation_report \
  --result runtime/r2-auswertung-NEU/result.json \
  --out runtime/r2-auswertung-NEU/bericht.html
```

Eine laufende SQLite-Hauptdatei ohne WAL ist keine verlässliche Sicherung.
SQLite-Backup-API mit Integritätsprüfung oder geordneten Abschluss verwenden.
Die entfernte Sammlung liegt **nicht** in dieser Übergabe. Download/Backup mit
dem Benutzer planen, nicht R2-Referenzdaten als aktuelle Sammlung ausgeben.
Lokale Originale nicht überschreiben. Ein Exitcode 2 bei der Evaluation kann
unzureichende Evidenz bedeuten; Ergebnis prüfen, nicht blind erneut laufen lassen.

Der HTML-Renderer liest nur eine vorhandene `result.json`, ändert keine
Berechnung und attestiert deren Herkunft nicht unabhängig. Fehlende Werte
bleiben unbekannt; Modelleinstellungen und Limitierungen bleiben sichtbar.

## 12. Neuer eigenständiger Paper-Dienst

Implementiert in `operations/paper_service.py` und `paper_feed.py`, dokumentiert
in `Projekt/operations/PAPER-SERVICE.md`. Noch nicht auf dem VPS abgenommen.

- Eigene Datenbank, neue virtuelle 50 USD, eigenes Manifest und Einzelwriter-Lock.
- Demo als Standard; Dauer 1 Sekunde bis höchstens 24 Stunden, unveränderte Deadline
  bei Wiederanlauf. Demo endet nach ihren 18 Beobachtungen, nicht erst nach Zeitablauf.
- Eigene Code-/Service-Fingerprints; beschädigte/geänderte Manifeste werden gesperrt.
- Backups nach erster Runde, stündlich und am Ende; zwei Slots, SQLite-Integrität.
- Wiederherstellung in neuen Ordner, alter Writer muss beendet sein; Deadline
  und Geldzustand bleiben erhalten, Original bekommt Stop-Marker.
- Stop-Marker sind dauerhaft, nicht automatisch löschen. Kein Wiederstart eines
  regulär abgeschlossenen Laufs. Keine erfundene Schlussliquidation.
- Unter 2 GiB freiem Speicher oder nach fünf Zyklen ohne frischen numerischen
  Kurs endet der Lauf; Netzwerkrunden sind zeitlich begrenzt und abbrechbar.
- Offene Positionen/Orders behalten den ursprünglichen Pool und Priorität.
  Andere Kandidaten rotieren. Normale Auswahl 8 Coins; vorhandene Positionen
  werden nicht einfach entfernt, wenn ein Limit erreicht ist.
- Neue Marktdatenaufnahme hat **keine R2-Kohorten**. Sie ist ein späterer
  eigener Betriebstest, keine identische Fortsetzung des R2-Replays.
- Eigenes Budget 70'000/600'000 RPC-Versuche. Dieses wird nicht automatisch
  mit dem Sammler oder anderen Helius-Projekten verrechnet.
- Marktmodus verlangt explizites Protokoll und passenden geprüften Ergebnisbericht,
  frühestens nach Ende plus 3'960 Sekunden. Die Prüfung ist kein signiertes Attest.

Künstliche lokale Probe, keine Zugangsdaten benötigt:

```bash
python -m operations.paper_service init --directory runtime/NEUE-PAPER-DEMO --duration 60
python -m operations.paper_service run --directory runtime/NEUE-PAPER-DEMO
python -m operations.paper_service status --directory runtime/NEUE-PAPER-DEMO --human
```

VPS-Vorlage: `/opt/memecoin-paper`, Benutzer `memecoin-paper`,
`/var/lib/memecoin-paper/run`, eigene systemd-Unit, 512 MiB/25 % eines CPU-Kerns.
Diese Pfade sind **Zielvorlagen**, keine bestätigte Installation.

## 13. Zwei verschiedene Telegram-Funktionen

### A. Bereits aktiver Sammler-Monitor

Vom Benutzer am 8. Oktober eingerichtet und erster Empfang bestätigt.
Botname war `trady25_bot`. Kein Bot-Token oder Chat-ID im Paket.
Private Datei `/etc/memecoin-collector/telegram.env`, root-lesbar; nicht öffnen
und in Ausgaben kopieren. Tagesbericht ab 09:00 Europe/Zurich, Störungen alle
fünf Minuten. Kein Neukoppeln nötig, solange keine aktuelle Störung vorliegt.

### B. Vorbereiteter Paper-Monitor

`operations/paper_notify.py`, getrennte Unit und Timer. Standardmäßig Vorschau;
echter Versand braucht `--send` und konfigurierte Credentials.
Bestätigte simulierte Fills erzeugen BUY-/SELL-Meldungen, bloße Orders nicht.
Fehlgeschlagene/abgelehnte/verfallene Orders sind getrennt. Jede Nachricht sagt
„PAPER – NUR VIRTUELLES GELD“, künstliche Kurse zusätzlich ausdrücklich markiert.

Tagesbericht zeigt Wallet, Reservierungen, offene Positionen, Buchhaltung sowie
den vollständigen Vortag in Schweizer Zeit; DST-Tage mit 23/25 Stunden getestet.
Störungen umfassen Kurs-/Heartbeatalter, fehlenden Prozess, DEAD-Wallet,
Buchhaltung, unsichere Bewertung, Backup, Speicher und RPC-Budget.

Versandstand liegt außerhalb des Paper-Datenverzeichnisses. Lock, Quelle/Manifest/
Empfängerbindung und dauerhafter Cursor. Fortschritt erst nach bestätigter
Telegram-Antwort. Pro Tick maximal fünf Events plus Status, mindestens ungefähr
eine Sekunde zwischen Nachrichten; Vorlage startet eine Minute nach vorherigem Ende.
Erste Aktivierung kann alte Ereignisse mit Originalzeit nachliefern.

**Keine Exactly-once-Garantie:** Absturz zwischen Annahme und gespeicherter
Bestätigung oder unklarer Timeout kann Duplikate erzeugen. Bei kompletter VPS-/
Netzwerkstörung kann ein Monitor auf demselben Server keine Nachricht senden.
Kein Trading per Telegram-Befehl. Echte Zustellung der Paper-Ergänzung steht aus.

## 14. Anti-FOMO und Risikogröße: neueste Forschungsarbeit

Ein Instagram-Video führte zu einer Analyse des Dokuments:
https://docs.google.com/document/d/1T6FX7_dBnY1ll34Gt0nKBBubE0PVC7FkXl9xgy9ZY3g/edit

Titel: „6 AI Bot Trading Team: Setup Guide (Paper Mode)“. Es enthält Prompts für
Scanner, Sizer, Buyer, Prediction-Market-Agent, Anti-FOMO, Logger; keinen
ausführbaren autonomen Handelsbot. Die Geschichte 89 → 55'698 USD wird dort
selbst als unbestätigt bezeichnet. Keine belegte Überlegenheit. Prediction
Markets und sechs LLM-Agenten wurden **nicht** in dieses Projekt eingebaut.

Ergebnis des Vergleichs: Anti-FOMO, sizing nach Stop-Abstand und mehr
Marktkontext sind Forschungsideen. Unser Code hat bereits deutlich konkretere
On-chain-Prüfungen, Speicherung, Kostenmodell und Prüfabläufe. Das beweist
trotzdem keine Profitabilität unseres Bots.

Auf Benutzerwunsch entstand `operations/entry_variants.py`, außerhalb des
eingefrorenen Kern-Hashumfangs. Es erzeugt nur vier **advisory decisions auf
identischen Inputs**, keine Orders und keine getrennt fortlaufenden Wallets:
Baseline, Anti-FOMO, Risikogröße, Kombination.

Vorläufige Anti-FOMO-Regeln:

- Mehr als 10 % Anstieg über 5 Minuten blockieren.
- Mehr als 25 % über 15 Minuten blockieren.
- Mehr als 25 % über dem beobachteten 15-Minuten-Tief blockieren.
- Ankerkurs am oder maximal 30 Sekunden vor Beginn; keine Lücke über 60 Sekunden.
- Fehlende/konfliktbehaftete Historie blockiert. Nur gleicher Token, Pool und Quelle;
  keine zukünftigen oder erst später verfügbaren Beobachtungen.
- Bestehende Veto-/Positions-/Cashregeln bleiben erhalten; Ausstiege unverändert.

Keine optimierten Schwellen. Die volle 15-Minuten-Historie schließt sehr frühe
Einstiege aus und verkürzt das nutzbare R2-Einstiegsfenster erheblich. Filter
können Gewinner entfernen. Keine subjektive Rücksetzer-, Support- oder
Volumenexplosionslogik implementiert; Tiefabstand ist nur eine Näherung.

Risikogröße:

- Planungsbudget 0,6 % des Handelskapitals, inklusive Kostenpuffer.
- Bisherige 5-%-Positionsobergrenze, freies Cash und Poollimit bleiben Obergrenzen.
- Verlustplanung = feste Kosten + Budget × (Stop-Abstand + zweiseitige
  Gebühren/Slippage + 2 % Zusatzpuffer) + `4 × Budget² / Liquidität`.
- Feste Kosten berücksichtigen Ein-/Ausstieg plus einen Fehlversuch.
- Budget wird nach unten gerundet. Zu teure Positionen werden blockiert.
- Kein neues Stopniveau wird gewählt. Keine garantierte Verlustgrenze, kein
  gemeinsames Risikobudget aller Positionen, noch keine Neubewertung beim Fill.
- Im künstlichen 50-USD-Beispiel sinkt der vorgeschlagene Einsatz von 2,50 auf
  1,353215 USD. Kein Gewinnvergleich und keine wirtschaftliche Empfehlung.

```bash
python -m operations.entry_variants --out runtime/NEUE-EINSTIEGSPROBE
```

Drei erzeugte Fälle: ruhiger Anstieg, starker Kurssprung, Historienlücke.
19 Tests prüfen u. a. Zeitverfügbarkeit, Pooltrennung, Grenzen, Reservierungen,
Kosten, Stops und unveränderte Ausstiege. Integration in echten getrennten
Replay-/Paper-Pfad mit je eigener Wallet steht noch aus. Danach neues vorab
festgelegtes Vergleichsfenster, keine Auswertung/Optimierung mitten in R2.

## 15. Installation, Tests und Entwicklungsumgebung

Python >=3.12, Linux/macOS; unter Windows WSL. `fcntl` ist für Sperren nötig.
Server nutzt Python 3.13.5. Abhängigkeiten in `requirements.txt` sind fixiert;
Versionen nicht beliebig ändern, weil sie Teil des Kern-Fingerprints sind.

```bash
cd Projekt
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
```

Letzte vollständige Prüfung des veröffentlichten Commits: **337 Tests bestanden
in 20,32 Sekunden**, saubere Quellkopie ohne `.env`, Laufzeitdaten oder originale
R2-Referenz. Zwei Paper-Protokolltests wurden dafür auf isolierte, synthetische
Fixtures umgestellt. Ihre künstlichen Marktquell-Labels sind Unit-Testdaten,
keine echte Marktevidenz. Core-/R2-Fingerprints blieben unverändert.

Frühere 318/309/289/264-Zahlen sind historische Zwischenstände. Nicht behaupten,
dass am 12. Oktober neue Markt-/Servertests stattgefunden haben. Paketprüfung
am Übergabetag prüft Dateigleichheit, SQLite-Integrität, Referenzhashes und Archiv.

Weitere lokale, synthetische Probe:

```bash
python main.py demo --db runtime/NEUE-DEMO.sqlite3
python -m operations.paper_rehearsal --out runtime/NEUE-BETRIEBSPROBE
```

Die Betriebsprobe beendet echte Kindprozesse per SIGKILL bei offener Order und
Position, prüft Sperren, Wiederanlauf, Wiederherstellung und identische Zustände.
Das ist kein simulierter Host-Stromausfall und keine Garantie für VPS-Speicher.
Tests nicht überspringen, um eine Installation durchzubringen.

## 16. Historische Vorfälle, nicht erneut auslösen

- R1 begann am 7. Oktober. Rotierende Watchlist ließ bei späteren Ausgangskursen
  Stundenfolgekurse fehlen; R2 änderte das explizit mit neuem Zukunftsprotokoll.
- Die erste v3-Updateprüfung wartete nur etwa zwei Minuten, während R2 die
  nächste Neuaufnahme erst nach zwölf Minuten zulässt. Erster Coin hatte keinen
  DEX-Kurs; das Update rollte zurück, obwohl R2 grundsätzlich lief.
- `memecoin-r2-retry.sh` wurde erstellt: getrennte systemd-Prüfung, Sicherungen,
  zwei verschiedene frische Kurse, maximal etwa 40 Minuten, sonst Rückkehr zu R1.
- Benutzer führte es am 8. Oktober 17:45 Uhr aus. R1 hatte 37'304 Beobachtungen,
  R2 anfangs 7. Um 17:46 Uhr war R2 bestätigt aktiv; der Prüfhelfer endete erfolgreich.
  Ein beendeter Retry-Dienst bedeutet nicht, dass der Sammler beendet wurde.
- Telegram wurde am selben Tag gekoppelt und die erste Nachricht bestätigt.
- Es gab im ersten Installationspaket Testprobleme durch kleines `/tmp`-RAM-
  Dateisystem. Nachfolgepakete nutzen geeigneten Testpfad. Speicherprüfungen
  nicht einfach abschalten; realer Mindestplatz bleibt 2 GiB.
- Alte Installer erwarten ein **noch zukünftiges** Zeitfenster. Am 12. Oktober
  dürfen sie nicht für das bereits laufende R2-Fenster erneut verwendet werden.

## 17. Empfohlene nächste Arbeit, priorisiert

1. Mit dem Benutzer den aktuellen VPS-Status und gegebenenfalls Helius-Credits
   lesen. Fehlendes aktuelles Wissen offen benennen, keinen Fortschritt erfinden.
2. Bis 16. Oktober 03:06 CEST unverändert sammeln. Qualitätswarnungen beobachten;
   nur konkret nötige Betriebsprobleme behandeln, keine Strategieparameter ändern.
3. Finales konsistentes Backup samt Manifest/Status/Softwarezuordnung planen.
   Außerhalb des VPS sichern; lokale rotierende Backups allein reichen nicht.
4. Nach Ende R2 mit der Originalreferenz auswerten, alle sechs Läufe und Blocker
   ansehen. Fehlende Evidenz bleibt fehlend. Kein automatisches Echtgeld-Go.
5. Bei geeigneter Evidenz kontrollierten Paper-Betriebstest vorbereiten:
   getrennte Pfade/Benutzer, Helius-Gesamtbudget, Koexistenz mit Velincoin,
   reale Telegram-Zustellung, Rechte/Backups/Stop und Last prüfen.
6. Parallel möglich: neue Einstiegsvarianten in separat getesteten Replaypfad
   integrieren. Nicht die eingefrorenen Module überschreiben. Einzelne Effekte
   vergleichen, alle Ergebnisse dokumentieren, neues Protokoll vor Testbeginn.
7. Breitere Discovery, Entwicklercluster, genauere AMM-Ausführung und ML sind
   weitere Forschung, nicht schon vorhandene Fähigkeiten. ML erst bei Vorteil
   gegenüber einfacher Baseline auf unbekannten Daten. Keine LLM-Agentenpflicht.

## 18. Was Claude nicht aus dieser Übergabe ableiten darf

- Kein direkter Server-/GitHub-/Telegramzugang ist mit einem Dokument übertragen.
- Keine aktuelle R2-Datenbank, aktuellen Serverlogs oder heutigen Helius-Credits
  sind enthalten. Diese müssen über den Benutzer/künftigen autorisierten Zugang kommen.
- Keine echten Gewinne oder erfolgreichen Echtgeldtransaktionen sind belegt.
- Gute Datenabdeckung ist keine vollständige Marktabdeckung und keine Handelsreife.
- Ein lokaler Hash beweist Zuordnung/Unverändertheit, nicht dass niemand Daten
  anderweitig angesehen hat oder ein Bericht inhaltlich richtig ist.
- Die Benutzerfreigabe zur Entwicklung ist keine automatische Freigabe für
  Echtgeld, neue kostenpflichtige Dienste oder disruptive Serveränderungen.
- Dieses Paket enthält die aktuelle Codebasis und relevante eingefrorene
  Referenzen, aber nicht jede historische temporäre Datei oder jeden Chatupload.

## 19. Vollständige Dokumentation im Projekt

Die ausführliche Historie liegt in `Projekt/docs/ENTWICKLUNGSVERLAUF.md`.
Sie enthält alte Phasen und Befehle, die nicht als aktuelle Deployment-Anleitung
zu behandeln sind. `Projekt/docs/PROJEKTSTAND.md` ist der veröffentlichte Stand
vom 10. Oktober. Alle weiteren Anleitungen:

- `operations/PHASE7.md`
- `operations/PAPER-SERVICE.md`
- `operations/PAPER-TELEGRAM.md`
- `operations/AUSWERTUNGSBERICHT.md`
- `operations/EINSTIEGSVARIANTEN.md`
- `deploy/TELEGRAM.md`
- `deploy/ANLEITUNG.md`, `UPDATE-R2.md`, `RETRY-R2.md` (historisch)
- `docs/beispiele/`: künstliche HTML-/Telegram-Vorschauen, keine Live-Seiten.

Wenn Beschreibung und Code im Detail voneinander abweichen, die Abweichung
benennen und den tatsächlichen Code/Manifeststand prüfen. Keine Behauptung
still durch Vermutungen ersetzen. Erst lesen und vergleichen, dann ändern.
