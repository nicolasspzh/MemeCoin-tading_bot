# R3 Stufe D2: Ergebnis des zweiten Probelaufs

Geplant: 24 Stunden ab 18.10.2026, 09:40 Uhr Schweizer Zeit (07:40 UTC).
Bericht vom Betreiber übermittelt, unverändert abgelegt in
`uebergabe/2026-10-19/probe-d2-bericht.json`.

## Der Lauf endete vorzeitig

Status `stopped_by_request`. Der Lauf hat nach rund 7,5 Stunden aufgehört,
nicht nach 24 Stunden. Belege:

- 1'341 Runden zu je etwa 20 Sekunden ergeben rund 7,45 Stunden.
- Letzte Aufnahme 15:01 UTC; Entdeckungen, geeignete Coins und Aufnahmen
  gibt es nur in den UTC-Stunden 07 bis 15.

Ursache, geprüft am 19.10. mit Angaben des Betreibers vom VPS:

- `state.json`: gestoppt am 18.10. um 15:05:15 UTC (17:05 Uhr Schweizer Zeit).
- `journalctl`: systemd hat den Dienst um 17:05:15 gestoppt, der Dienst hat
  sich sauber beendet (`Deactivated successfully`).
- `uptime -s`: Der VPS läuft seit 18.10. 17:17:02, also 12 Minuten nach dem
  Stopp neu gestartet.

Folgerung: Der VPS wurde heruntergefahren oder neu gestartet. Ob das der
Betreiber, der Anbieter oder etwas anderes ausgelöst hat, ist nicht
bekannt. Der Probelauf-Dienst war absichtlich nicht für den Systemstart
eingerichtet und lief deshalb nicht weiter. Ab Stufe D3 wird er beim Start
fortgesetzt (siehe [R3-STUFE-D3-ANLEITUNG.md](R3-STUFE-D3-ANLEITUNG.md)).
Ein R3-Test über 7 bis 14 Tage muss einen Neustart ohnehin überstehen.

**Fehler in meinem Bericht:** `deploy/probe_report.py` hat bei einem
vorzeitigen Ende trotzdem durch die geplanten 24 Stunden geteilt. Alle
Werte pro Stunde im Bericht sind deshalb rund dreimal zu tief. Behoben am
19.10. mit Test: Der Bericht rechnet jetzt bis zum Stoppzeitpunkt aus
`state.json`. Die korrigierten Werte unten habe ich mit 7,45 Stunden
gerechnet. Laut `state.json` lief der Lauf von 07:40:46 bis 15:05:15 UTC,
also 7,41 Stunden. Die Abweichung zu 7,45 ändert keine Aussage.

## Ergebnis gegen die festgelegten Grenzen

| Prüfung | Grenze | Gemessen | Ergebnis |
| --- | --- | --- | --- |
| Genug geeignete Coins | mindestens 80 % der Abstände höchstens 900 s | 22 von 28, also 78,6 % | knapp **nicht bestanden** |
| Keine Orders | 0 | 0 | bestanden |
| RPC-Verbrauch | unter 2'900 pro Stunde | rund 1'080 pro Stunde (8'054 in 7,45 h), 8'050 erfolgreich | bestanden |
| DEX Screener | Fehler in unter 1 % der Runden | keine erfasst | bestanden |
| Halterprüfung | höchstens 10 % mit Datenfehlern | 40 von 7'582, also 0,5 % | bestanden |

Der Lauf deckt ausserdem nur 07:40 bis etwa 15:10 UTC ab, also fast
dieselben Stunden wie der erste Lauf. Das eigentliche Ziel, den Abend und
die Nacht zu messen, ist nicht erreicht.

## Zahlen

- Aufnahmen: 29. Pro UTC-Stunde 2, 3, 3, 4, 5, 5, 3, 3, 1. Der Höchstwert
  bei 12 Minuten Takt ist 5.
- Geeignete Coins: 35 in rund 7,45 Stunden, also rund 4,7 pro Stunde. Im
  ersten Lauf zu ähnlichen Stunden (Samstag) waren es 2,8 pro Stunde.
  Davon 5 Prüfungen mit Raydium CPMM, der Rest PumpSwap.
- Neue Vorfilter-Sperre: 42 Prüfungen mit Pool älter als 24 Stunden,
  6 mit unbekanntem Alter.
- Nur zur Information: 637 Beobachtungen von 10 Coins bestehen alle
  Einstiegsprüfungen.

## Speicher

`journalctl` meldet für den Dienst einen Höchstwert von 384,3 MB
Arbeitsspeicher. Das entspricht der Grenze `MemoryHigh=384M`. Im Status
nach 17 Minuten waren es 62 MB. Ob der Anstieg vom Programm selbst oder vom
Datei-Zwischenspeicher der Datenbank kommt (den Linux bei Bedarf wieder
freigibt), lässt sich daraus nicht erkennen. R2 lief mit denselben Grenzen
eine Woche. Für Stufe D3 frage ich zusätzlich die Aufteilung ab.

## Offen

- Abend und Nacht sind weiterhin nicht auf dem VPS gemessen.
- Helius-Credits vor und nach dem Lauf.
