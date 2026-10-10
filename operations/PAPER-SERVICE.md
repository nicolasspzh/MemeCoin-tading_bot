# Eigenständiger Paper-Dienst

Entwicklungsstand vom 8. Oktober 2026: implementiert und mit synthetischen
Kursen und simulierten API-Antworten geprüft. Auf dem externen VPS ist dieser
Dienst **nicht installiert oder gestartet**. Die v3-Installation bleibt der
Beobachtungsdienst. Die Dateien hier sind kein Ersatz für das v3-Update.

## Funktionsumfang

- Eigene SQLite-Datenbank und virtuelle 50-USD-Wallet. Keine Schlüssel zum
  Signieren von Transaktionen, keine echte Orderausführung.
- Festes Ende innerhalb von maximal 24 Stunden nach Initialisierung. Eine
  automatische Wiederaufnahme setzt weder Zeitraum noch Wallet zurück.
- Gespeicherte Software- und Parameterprüfsummen: geänderte Software oder
  ein geändertes Manifest verhindern den Start mit dieser Sammlung.
- Ein Schreiber pro Datenbank; wiederholte Eingabekurse erzeugen keine
  doppelten Orders. Beobachtungsdatenbanken können nicht übernommen werden.
- Offene Positionen und ausstehende Orders haben Vorrang vor neuen Kandidaten
  und bleiben auf ihrem ursprünglichen Pool. Neue Kandidaten rotieren in den
  verbleibenden Slots. Im Normalfall werden höchstens acht Tokens abgefragt;
  bereits bestehende Positionen/Orders werden auch oberhalb dieser Zahl erhalten.
- Eigenes dauerhaftes RPC-Budget: 70.000 Versuche pro UTC-Tag, 600.000 insgesamt
  je Paper-Sammlung; einschließlich Discovery, Fehlversuchen und Fallbacks.
  Das ist kein gemeinsames Helius-Kontobudget und keine Creditmessung. Andere
  Sammlungen/Projekte sind nicht enthalten; vor einem späteren Parallelbetrieb
  muss das gemeinsame Kontingent geprüft werden.
- Jede Marktdatenrunde ist auf höchstens 60 Sekunden und das verbleibende
  Sammelfenster begrenzt. SIGTERM/SIGINT beendet auch einen ausstehenden
  asynchronen Abruf. Fehlende Kurse erzeugen keine Ausführungen.
- Fünf aufeinanderfolgende Runden ohne neuen frischen numerischen Kurs stoppen
  den Lauf mit `failure_limit`. Fehlerzähler bleiben bei Neustart erhalten.
  Weniger als 2 GiB freier Speicher stoppt vor der nächsten Beobachtung.
- SQLite-Sicherung nach der ersten Runde, danach stündlich und am regulären
  Ende; zwei rotierende Dateien mit Integritätsprüfung. Ein Sicherungsfehler
  bleibt sichtbar, ohne die Wallet zu löschen oder einen Erfolg vorzutäuschen.
- Am Ende bleiben offene Positionen und noch nicht verfallene Orders bestehen.
  Es gibt keine erfundene Schlussliquidation. Im gestoppten Dienst finden keine
  weiteren Bewertungen oder Orderabläufe statt.

## Jetzt ausführbar: kurze synthetische Betriebsprobe

Im bestehenden Projekt mit aktivierter Python-Umgebung; einen neuen Ordner wählen:

```bash
python -m operations.paper_service init --directory runtime/NEUER-PAPER-DEMO --duration 60
python -m operations.paper_service run --directory runtime/NEUER-PAPER-DEMO
python -m operations.paper_service status --directory runtime/NEUER-PAPER-DEMO --human
```

Der Standard ist `demo`, ohne `.env`, RPC- oder Telegram-Abfragen. Die 18
künstlichen Kurse werden mit ihren synthetischen Zeitstempeln verarbeitet.
Nach wenigen Sekunden endet der Lauf mit `source_exhausted`; die 60 Sekunden
sind die maximale Wanduhr-Laufzeit, keine Marktbeobachtungsdauer. Ein erneuter
Aufruf startet diesen abgeschlossenen Lauf nicht neu. Alle virtuellen
Ergebnisse sind ausschließlich Testdaten und keine Renditeprognose.

Für JSON-Ausgabe `--human` weglassen. Der Status öffnet die Datenbank nur lesend,
prüft zusätzlich den tatsächlichen Schreib-Lock und zeigt offene Positionen,
Orderzustände, Buchhaltung, Kursalter und Sicherungsfehler.

Gezielter Stopp eines laufenden Dienstes:

```bash
python -m operations.paper_service stop --directory runtime/NEUER-PAPER-DEMO
```

Ein manueller Stopp bleibt über Neustarts erhalten. Die Stop-Datei wird nicht
automatisch entfernt. Bei einem abrupten Prozessabbruch ohne Stoppmarker kann
`run` innerhalb der unveränderten Frist fortsetzen. Der angezeigte letzte
Zustand `running` allein beweist keinen lebenden Prozess.

## Sicherung wiederherstellen

Erst den bisherigen Dienst stoppen. Dann eine seiner geprüften SQLite-
Sicherungen in einen **neuen** Ordner zurückspielen:

```bash
python -m operations.paper_service restore \
  --from-directory runtime/NEUER-PAPER-DEMO \
  --backup runtime/NEUER-PAPER-DEMO/backups/paper-0.sqlite3 \
  --directory runtime/NEUE-PAPER-WIEDERHERSTELLUNG
```

Das verweigert einen noch aktiven Schreiber, prüft Datenbankzuordnung,
Integrität und Buchhaltung und setzt am ursprünglichen Verzeichnis einen
Stoppmarker. Originaldaten bleiben erhalten. Die neue Kopie startet nicht
automatisch und behält das ursprüngliche Laufzeitende. Daten nach dem gewählten
Sicherungszeitpunkt sind nicht wiederhergestellt. Gleichzeitiger Betrieb zweier
Kopien derselben virtuellen Wallet soll damit vermieden werden; manuell
entfernte Stoppmarker oder kopierte Verzeichnisse umgehen diesen Schutz.

## Späterer Einsatz mit Marktdaten

`init --source market` benötigt ausdrücklich `--protocol` und
`--reviewed-evaluation`. Vor dem Ende des passenden Phase-6-Fensters plus
66 Minuten Nachbeobachtung wird die Ergebnisdatei nicht einmal geöffnet.
Danach müssen Protokoll-/Codeprüfsummen, Szenariodefinitionen, echte Datenquelle
und der Status `REVIEWABLE_HOLDOUT` zusammenpassen. Diese Prüfung ersetzt
keine inhaltliche Bewertung: lokale Ergebnisdateien sind keine signierten
Atteste, und `REVIEWABLE_HOLDOUT` bedeutet keine Profitabilitätsfreigabe.

Der Betreiber muss den Ergebnisbericht zuvor tatsächlich prüfen. Eine
unpassende oder unzureichende Auswertung wird abgelehnt. Die späteren konkreten
Startparameter legen wir erst nach der Auswertung fest. Momentan wird kein
Paper-Dienst gegen echte Marktdaten gestartet.

Die Risikound Kostenparameter stammen aus dem geprüften Basisszenario.
Der eigenständige Paper-Datenabruf nutzt **keine** R2-Kohorten; er reserviert
Abfrageplätze für Positionen und Orders. Betriebsparameter (acht Slots,
Discovery alle 120 Sekunden, vier Transaktionen pro Discovery-Runde,
Anfragebudget) werden separat im Paper-Manifest festgehalten. Dadurch ist dies
ein neuer Paper-Betriebstest und keine identische Fortsetzung des Phase-6-Replays.
Der öffentliche Discovery-Feed ist weiterhin unvollständig; Pool- und
Token-Erweiterungen bleiben entsprechend den vorhandenen Risikoprüfungen
gesperrt. Kein Filter wurde gelockert, um mehr Trades zu erzeugen.

## Dienstvorlage und noch ausstehende VPS-Abnahme

`operations/memecoin-paper.service` ist eine noch nicht installierte Vorlage:
eigener Benutzer `memecoin-paper`, Programm unter `/opt/memecoin-paper`, Daten
unter `/var/lib/memecoin-paper/run`. Sie begrenzt CPU auf 25 % eines Kerns,
Speicher auf 512 MiB und Neustarts auf fünf in zehn Minuten. Die bestehende
MemeCoin-Sammlung und Velincoin-Dienste werden nicht verändert.

Vor einer späteren Installation müssen Programm, virtuelle Umgebung, Benutzer,
private RPC-Konfiguration und das bewertete Paper-Manifest eingerichtet sowie
Netzzugriff und Ressourcennutzung auf dem tatsächlichen VPS überprüft werden.
Es gibt noch keine Abnahme dieses neuen Dienstes auf Debian/systemd. Die
Vorlage allein installiert oder startet nichts.

Telegram aus dem v3-Paket überwacht derzeit ausschließlich den Beobachtungsdienst.
Die [Paper-spezifischen Telegram-Meldungen](PAPER-TELEGRAM.md) sind inzwischen
entwickelt und lokal mit simulierten Antworten geprüft, aber noch nicht auf dem
VPS aktiviert. Ein externer Ausfallmonitor und die Lastmessung zusammen mit dem
anderen VPS-Projekt sind noch ausstehend.
Sicherungen auf derselben Festplatte schützen nicht vor Verlust des ganzen VPS.
