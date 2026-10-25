# R3-Test: Statuskontrollen

Nur Technik und Datenabdeckung. Ergebnisse werden erst nach dem Testende
ausgewertet ([R3-PROTOKOLL.md](R3-PROTOKOLL.md)).

## 22.10.2026, rund 20:35 Uhr Schweizer Zeit

Anlass: Der Betreiber vermutete einen Absturz. Befund: kein Absturz.

- VPS läuft seit 18.10. 17:17 (`uptime -s`), also kein Neustart seit der
  Installation.
- Dienst aktiv seit 20.10. 22:01, ein einziger Start im Journal.
- Bericht: 46,74 Stunden aktiv, 0 Ausfälle, 8'454 Runden (im Schnitt alle
  20 Sekunden), 0 Orders und Ausführungen.
- 190 Aufnahmen, 228 geeignete Coins (4,9 pro Stunde), 53'967
  Beobachtungen, 0,9 % mit Datenfehlern.
- RPC: 57'332 Anfragen, davon 56'771 erfolgreich, rund 1'230 pro Stunde.
- Speicher: Der Dienst steht laut systemd bei 1'023 MB, also an der
  weichen Grenze von 1 GB. Sammler und Aufseher selbst haben aber je
  höchstens rund 60 MB belegt (`state.json`). Folgerung: Der Rest ist sehr
  wahrscheinlich Datei-Zwischenspeicher der Datenbank und der stündlichen
  Sicherungen, den Linux bei Bedarf freigibt. Die Runden laufen weiter im
  20-Sekunden-Takt, eine Bremsung ist nicht zu sehen.
- Nachgeprüft mit `memory.stat` (gleicher Abend): `anon` 74,6 MB (Speicher
  der Programme), `file` 977,1 MB (Datei-Zwischenspeicher), `shmem` 0.
  Damit ist belegt: Fast alles ist Zwischenspeicher, die Programme selbst
  brauchen rund 75 MB. Kein Handlungsbedarf.

## 25.10.2026, rund 14:45 Uhr Schweizer Zeit (Winterzeit)

Befund: läuft normal, keine Auffälligkeit, die den Test gefährdet.

- Kein Neustart des VPS seit 18.10. 17:17 (`uptime -s`).
- 113,7 Stunden aktiv, 0 Ausfälle, 20'567 Runden (im Schnitt alle
  19,9 Sekunden), letzte Aufnahme 25.10. 13:41 UTC, also wenige Minuten vor
  der Kontrolle.
- 0 Orders und Ausführungen.
- 428 Aufnahmen, 492 geeignete Coins (4,3 pro Stunde), 123'125
  Beobachtungen, 0,8 % mit Datenfehlern.
- RPC: 131'143 Anfragen, 99,4 % erfolgreich, rund 1'150 pro Stunde,
  höchstens 30'248 an einem Tag (Tageslimit 70'000). Hochgerechnet bis zum
  Sammelende rund 200'000 Anfragen.
- Speicher: Sammler und Aufseher weiterhin höchstens rund 60 MB.
- Längste Pause zwischen zwei Aufnahmen 8'230 Sekunden (2,3 Stunden) ohne
  Ausfall: In dieser Zeit gab es keinen geeigneten Coin. Für die Gültigkeit
  des Tests ist das kein Kriterium.
- `resolve_error` der Raydium-Suche (1'145) und `quote_gap` (60) wie in D3,
  ohne erkennbare Wirkung auf den Takt.
