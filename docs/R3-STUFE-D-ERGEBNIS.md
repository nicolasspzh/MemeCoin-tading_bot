# R3 Stufe D: Ergebnis des Probelaufs

Probelauf auf dem VPS am 17.10.2026, 10:07 bis 18:07 Uhr Schweizer Zeit
(08:07 bis 16:07 UTC). Bericht vom Betreiber übermittelt, unverändert
abgelegt in `uebergabe/2026-10-17/probe-d1-bericht.json`. Anleitung und
Grenzen: [R3-STUFE-D-ANLEITUNG.md](R3-STUFE-D-ANLEITUNG.md).

## Ergebnis gegen die vorher festgelegten Grenzen

| Prüfung | Grenze | Gemessen | Ergebnis |
| --- | --- | --- | --- |
| Genug geeignete Coins | mindestens 80 % der Aufnahmeabstände höchstens 900 s | 12 von 19 Abständen, also 63 % | **nicht bestanden** |
| Keine Orders | 0 | 0 Orders, 0 Ausführungen | bestanden |
| RPC-Verbrauch | unter 2'900 pro Stunde | 768 pro Stunde, alle 6'144 Anfragen erfolgreich | bestanden |
| DEX Screener | Fehler in unter 1 % der Runden | keine Fehler der Kursabfrage oder des Vorfilters erfasst | bestanden |
| Halterprüfung | höchstens 10 % mit Datenfehlern | 0 von 5'713 | bestanden |

**Stufe D ist damit nicht bestanden.** Technik und Abfragegrenzen
funktionieren. Es gibt aber zu wenige geeignete Coins für den Takt von
einem neuen Coin alle 12 Minuten.

## Zahlen zur Aufnahme

- Aufnahmefenster: 08:07 bis 14:52 UTC, rund 6,7 Stunden. Im Takt von
  12 Minuten wären darin rund 33 Aufnahmen möglich gewesen. Es waren 20.
- Median des Abstands: 728 Sekunden. Längster Abstand: 4'320 Sekunden
  (72 Minuten). 7 Abstände lagen über 900 Sekunden.
- Entdeckt: 173 Coins in 8 Stunden (124 über DEX-Screener-Profile, 49 über
  die on-chain Suche nach neuen Raydium-CPMM-Pools).
- Vom Vorfilter geprüft: 147 Coins, davon 22 geeignet (15 %), alle auf
  PumpSwap. Das sind 2,8 geeignete Coins pro Stunde. Für den 12-Minuten-Takt
  bräuchte es 5.
- Häufigste Ablehnungsgründe (je Prüfung, Coins werden mehrmals geprüft):
  zu wenig Liquidität 940, nicht unterstützter Pool 528, fremde
  Gegenwährung 159, kein Kurs 30, kein Paar 6.

Folgerung: Der Engpass ist die Zahl entdeckter Coins, nicht der Vorfilter
und nicht der Takt. Von 22 geeigneten Coins wurden 20 aufgenommen.

## Weitere Befunde

- Alle 5'713 Beobachtungen haben einen Kurs und eine vollständige
  Halterprüfung. In R2 hatten rund 4 % Datenfehler.
- Nur zur Information, kein Kriterium: 505 Beobachtungen von 10 der 20
  aufgenommenen Coins bestehen alle Einstiegsprüfungen.
- `data_degraded` steht auf `true`. Die Ursache geht aus dem Bericht nicht
  hervor. Fehler der Kursabfrage, des Vorfilters oder der On-Chain-Prüfung
  sind im Bericht keine erfasst.
- `scheduler:capacity_deferred` erscheint in jeder Runde. Das war in R2
  gleich: Die Meldung zählt wartende Kandidaten und ist kein Fehler.
- Helius-Credits nach dem Probelauf: 284'261 von 1'000'000 (Angabe des
  Betreibers vom 17.10.). Ein Stand direkt vor dem Probelauf fehlt. Der
  letzte bekannte Stand ist 212'398 vom 13.10. Die Differenz von 71'863
  enthält die letzten drei Tage von R2 und den Probelauf. Der Anteil des
  Probelaufs lässt sich daraus nicht bestimmen. Gezählt wurden im Probelauf
  6'144 RPC-Anfragen.

## Grenzen

- 8 Stunden an einem Samstag zwischen 10 und 18 Uhr Schweizer Zeit. Andere
  Tageszeiten und Wochentage können mehr oder weniger Coins liefern.
- Die Zahl geeigneter Coins pro Stunde stammt aus 22 Coins. Sie ist
  entsprechend unsicher.
