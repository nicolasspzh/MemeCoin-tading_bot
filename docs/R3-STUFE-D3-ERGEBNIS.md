# R3 Stufe D3: Ergebnis des dritten Probelaufs

Lauf auf dem VPS vom 19.10.2026, 20:13 Uhr, bis 20.10.2026, 20:13 Uhr
Schweizer Zeit (18:13 bis 18:13 UTC). Bericht, `journalctl` und
`uptime -s` vom Betreiber übermittelt. Der Bericht liegt unverändert in
`uebergabe/2026-10-19/probe-d3-bericht.json`.

Der Lauf ist vollständig: Status `completed_scheduled_window`, 24,0 aktive
Stunden, keine Ausfälle, kein Neustart des VPS (läuft seit 18.10. 17:17).

## Ergebnis gegen die vorher festgelegten Grenzen

| Prüfung | Grenze | Gemessen | Ergebnis |
| --- | --- | --- | --- |
| Genug geeignete Coins | mindestens 80 % der Abstände höchstens 900 s | 83 von 98, also 84,7 % | bestanden |
| Keine Orders | 0 | 0 Orders, 0 Ausführungen | bestanden |
| RPC-Verbrauch | unter 2'900 pro Stunde | 1'266 pro Stunde (30'393 Anfragen, 30'377 erfolgreich) | bestanden |
| DEX Screener | Fehler in unter 1 % der Runden | keine Fehler der Kursabfrage oder des Vorfilters erfasst | bestanden |
| Halterprüfung | höchstens 10 % mit Datenfehlern | 164 von 28'570, also 0,6 % | bestanden |
| Vollständigkeit | höchstens 2 Stunden Ausfall | 0 | bestanden |

**Stufe D ist mit D3 bestanden.**

## Zahlen

- 99 Aufnahmen. Median des Abstands 727 Sekunden, längster 2'557 Sekunden.
- 628 Coins entdeckt (520 über Profile, 108 über die on-chain Suche nach
  Raydium-CPMM-Pools), 580 geprüft, 126 geeignet. Das sind 5,3 pro Stunde.
- Geeignete Coins pro UTC-Stunde: am wenigsten um 10 Uhr (1) sowie um 05,
  07, 12 und 17 Uhr (je 2); am meisten zwischen 18 und 23 Uhr (6 bis 11).
  Der Abend in Europa, also der Tag in den USA, liefert die meisten Coins.
  Das bestätigt die Vermutung aus D1 und der Cloud-Messung.
- Aufnahmen pro UTC-Stunde: in 13 von 24 Stunden das Maximum von 5.
- Pooltypen der geeigneten Prüfungen: 203 PumpSwap, 18 Raydium CPMM.
- Nur zur Information, kein Kriterium: 2'402 Beobachtungen von 40 der 99
  aufgenommenen Coins bestehen alle Einstiegsprüfungen. Zum Vergleich: In
  den ganzen sieben R2-Tagen waren es mit R3-Regeln 41 Coins (Stufe C).

## Auffälligkeiten

- **Speicher:** `journalctl` meldet 385,9 MB Höchstwert (Grenze
  `MemoryHigh=384M`) und 29,7 MB ausgelagerten Speicher. Ausgelagert wird
  nur Speicher, den Linux nicht einfach verwerfen kann. Reiner
  Datei-Zwischenspeicher würde verworfen statt ausgelagert. Das spricht
  dafür, dass das Programm selbst oder temporäre Dateien im
  Arbeitsspeicher an die Grenze kommen. Das ist eine Folgerung, kein
  Beleg. Welcher Prozess (Aufseher oder Sammler) wie viel braucht, ist
  unbekannt. Vor einem Test über 7 Tage muss das geklärt werden, sonst
  droht bei `MemoryMax=512M` ein Abbruch.
- **On-chain-Suche nach Raydium-Pools:** 437 Meldungen `resolve_error`.
  Diese Suche ist eine von zwei Quellen und lief trotzdem weiter. Sie
  setzt vermutlich auch `data_degraded=true`. Die Gründe stehen in der
  Datenbank und sind noch nicht ausgelesen.
- **Helius-Credits:** noch nicht übermittelt. Hochgerechnet aus den
  gezählten Anfragen bräuchte ein 7-Tage-Test rund 213'000 Anfragen,
  ein 14-Tage-Test rund 425'000. Wie viele Credits das sind, ist offen.

## Grenzen

- Ein einzelner Tag, Montag auf Dienstag. Das Wochenende kann anders sein.
- 126 geeignete Coins sind mehr als in D1 und D2, aber immer noch wenige.
