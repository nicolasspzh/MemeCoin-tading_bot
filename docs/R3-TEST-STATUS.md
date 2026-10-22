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
  Sicherungen, den Linux bei Bedarf freigibt. Belegt ist das erst mit der
  Aufteilung aus `memory.stat`. Die Runden laufen weiter im 20-Sekunden-Takt,
  eine Bremsung ist nicht zu sehen.
