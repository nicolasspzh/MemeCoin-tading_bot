# Telegram für den Paper-Dienst

Entwickelt am 9. Oktober 2026; lokal mit künstlichen Handelsdaten und simulierten
Telegram-Antworten getestet. Kein Versand an den echten Bot wurde durchgeführt.
Die aktive R2-Sammlung und ihre Telegram-Einrichtung auf dem VPS bleiben
unverändert. Diese Ergänzung wird erst mit dem späteren Paper-Dienst installiert.

## Was gemeldet wird

- **Simulierter Kauf/Verkauf** erst nach einer gespeicherten Ausführung: Order,
  Ereigniszeit, Token und Pool, Menge, simulierter Ausführungspreis,
  Cash-Veränderung und Gebühren. Ein Verkauf zeigt das gespeicherte
  Nettoergebnis des Trades einschließlich bereits erfasster Fehlversuchskosten.
- Abgelehnte, fehlgeschlagene, verfallene und stornierte Orders erscheinen als
  **Order ohne Ausführung**, mit den tatsächlich simulierten Kosten.
  Eine vorgemerkte Order allein wird nicht als Kauf oder Verkauf ausgegeben.
- Erster Status, geänderte Betriebszustände, Störungen und Entwarnungen.
- **Tagesbericht beim ersten Prüflauf ab 09:00 Uhr Europe/Zurich**: virtuelle
  Wallet, Reservierungen, verfügbare Mittel, geschätztes Handelsvermögen,
  kumulatives realisiertes Nettoergebnis, Positionen, ausstehende Orders und
  Buchhaltungsstatus. Cash, Handelsvermögen und realisierte Ergebnisse sind
  getrennt beschriftet. Offene Positionen sind nicht realisierter Gewinn.
- Zusätzlich die Käufe, Verkäufe, Orders ohne Ausführung und Summe der
  realisierten Buchungsänderungen des **vollständigen Vortags** in Schweizer
  Zeit. Das berücksichtigt auch 23- bzw. 25-stündige Tage bei Zeitumstellung.
  Bei einem verpassten Tagesbericht wird der letzte vollständige Vortag
  ausgewiesen; nicht jeder verpasste Tag wird einzeln nachgesendet.
- Offene Positionen mit Token, Menge, Einstandskosten und Eröffnungszeit.
  Bei gestopptem Dienst bleiben offene Positionen und Orders ausdrücklich
  sichtbar; es wird keine Schlussliquidation erfunden.

Jede Nachricht trägt **PAPER – NUR VIRTUELLES GELD**. Künstliche Eingaben sind
zusätzlich als **KÜNSTLICHE TESTKURSE** markiert. Demo-Buchungszeiten stammen
aus dem synthetischen Szenario; sie sind kein Handel am heutigen Markttag.

## Störungen

Der Monitor prüft unter anderem fehlenden Prozess/Heartbeat, veraltete
Marktpreise, Laufzeitüberschreitung, Fehlerzustände, gesperrte Wallet,
Buchhaltungsfehler, unsichere Bewertungen, Sicherungsfehler, alten Backupstand,
knappen Speicher und 90 % des RPC-Tages-/Gesamtbudgets. RPC-Anfragen sind keine
Helius-Credits. Unveränderte Störungen werden nicht bei jedem Prüflauf erneut
gemeldet; sie bleiben im Tagesbericht sichtbar.

Bei unzuverlässig lesbaren Daten werden Zustand und Kontostände als unbekannt
gemeldet. Bei Buchhaltungsfehlern werden keine neuen Trade-Meldungen gesendet.
Nach Wiederherstellung lesbarer, unveränderter Daten wird weiter zugestellt.

## Versand und Wiederanlauf

`operations.paper_notify` liest die Paper-Datenbank im SQLite-Lesemodus. Es
verändert weder Trades noch Wallet noch Dienstparameter. Ein eigener
Schreib-Lock und Versandstand liegen **außerhalb** des Paper-Datenverzeichnisses.
Ein bestätigtes Ereignis wird durch seine ID und seinen Inhaltsprüfwert erfasst.

Nach jeder bestätigten Telegram-Antwort wird der Versandstand atomar gespeichert.
Bei einem Teilausfall werden bereits bestätigte Ereignisse übersprungen und die
noch ausstehenden beim nächsten Lauf erneut versucht. Antwortet Telegram nicht
eindeutig, kann eine bereits angenommene Nachricht nochmals gesendet werden;
auch ein Absturz zwischen Annahme und Speicherung kann ein Duplikat erzeugen.
Es gibt keine Garantie einer exakt einmaligen Zustellung.

Pro Prüflauf kommen höchstens fünf Ereignisse plus ein Statusbericht. Zwischen
Nachrichten liegt mindestens etwa eine Sekunde. Die separate Timer-Vorlage prüft
eine Minute nach dem Ende des vorherigen Laufs. Es handelt sich um regelmäßige
Abfragen, nicht um sofortige Push-Meldungen bei jeder Order. Ein Rückstand wird
schrittweise aufgeholt; jede Ereignismeldung zeigt die originale Ereigniszeit.
Bei der ersten Aktivierung werden auch bereits gespeicherte Ereignisse
nachgesendet, begrenzt auf fünf je Lauf; sie werden nicht als neue Live-Trades
ausgegeben.

Der Versandstand ist an Paper-Verzeichnis, Laufmanifest und privaten Chat
gebunden. Andere Empfänger dürfen nicht versehentlich denselben Stand verwenden.
Bei neuer Sammlung, Wiederherstellung oder geändertem bereits gemeldetem
Historienpunkt muss die Zuordnung geprüft und ein bewusst gewählter separater
Versandstand verwendet werden. Alte Meldungen können dann erneut erscheinen.
Versandstände oder Datenbanken nicht einfach löschen, um Warnungen zu beseitigen.

Ein kaputter Versandstand oder fehlende/beschädigte Zugangsdaten werden im
Dienstjournal gemeldet. Ohne funktionierenden Versand kann der Monitor diese
Probleme nicht selbst per Telegram melden. Ebenso kann er bei vollständigem
VPS- oder Internetausfall keine Warnung senden. Tagesberichte laufen auch nach
dem Paper-Ende weiter, bis der Timer ausgeschaltet wird; so bleiben offene
Positionen sichtbar.

## Jetzt lokal prüfen – ohne Telegram-Zugang

Im Projektverzeichnis nach einer synthetischen Paper-Betriebsprobe:

```bash
python -m operations.paper_notify \
  --directory runtime/MEIN-PAPER-DEMO \
  --state runtime/MEIN-PAPER-VERSAND/state.json
```

Ohne `--send` entsteht ausschließlich eine Vorschau in der Konsole. Es werden
keine Nachrichten gesendet und keine Zustellfortschritte gespeichert. Ein
separates Lock-Verzeichnis kann dafür angelegt werden. Den State-Pfad immer
außerhalb von `MEIN-PAPER-DEMO` wählen. Ein bestehender Zustand kann zum Anzeigen
der noch ausstehenden Meldungen verwendet werden.

Die geprüfte Beispielvorschau liegt unter
`runtime/paper-telegram-preview-20261009/messages.md` im Entwicklungsprojekt.

## Spätere VPS-Einrichtung

Die Vorlagen `operations/memecoin-paper-telegram.service` und `.timer` sind
vorbereitet, **nicht installiert**. Sie sind vom bestehenden
`memecoin-telegram.timer` des Sammlers getrennt. Voraussetzung sind der
eingerichtete Benutzer und die Installation des eigenständigen Paper-Dienstes.

Die Vorlage liest die bereits vorhandene, nur für root lesbare Konfiguration
`/etc/memecoin-collector/telegram.env` über systemd. Dadurch lässt sich derselbe
gepaarte private Bot nutzen, ohne den Token nochmals im Chat einzutragen.
Das sendende Programm läuft als `memecoin-paper`, liest den Paper-Datenbestand
unter `/var/lib/memecoin-paper/run` und speichert nur seinen Versandstand unter
`/var/lib/memecoin-paper-notifier`. Die Vorlage verwendet ausdrücklich `--send`.

Vor der späteren Aktivierung müssen auf dem VPS Benutzer-/Pfadrechte,
Telegram-Zustellung und gleichzeitiger Betrieb mit dem Sammler geprüft werden.
Diese Arbeiten und ein echter Zustelltest stehen noch aus. Es gibt keine
Telegram-Befehle zum Kaufen, Verkaufen oder Steuern der Dienste. Der Monitor
benötigt weder Wallet-Schlüssel noch zusätzliche Helius-Anfragen.
