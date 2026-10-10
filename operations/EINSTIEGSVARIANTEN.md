# Separate Forschung: Anti-FOMO und Positionsgröße

Stand: 10. Oktober 2026. Implementiert als isolierter Entscheidungsvergleich
in `operations.entry_variants`. Keine Änderung am eingefrorenen R2-Kern,
keine Installation auf dem VPS und keine Verbindung zum laufenden Paper-Dienst.
Das Modul erzeugt keine Orders und greift weder auf Datenbanken noch Netzwerk zu.

## Was jetzt ausgeführt werden kann

```bash
python -m operations.entry_variants --out runtime/NEUER-EINSTIEGSTEST
```

Es entstehen `result.json` und `Vorschau.html`. Das Ziel muss neu sein. Die
Kommandozeile akzeptiert bewusst keine Marktdatenbank. Drei künstliche
Kurshistorien prüfen einen ruhigen Anstieg, einen starken Kurssprung und
eine Datenlücke. Verglichen werden vier Entscheidungen auf identischen
Eingaben: bisherige Regeln, Anti-FOMO allein, Risikogröße allein, Kombination.
Das ist **kein Portfolio-Backtest**: Es gibt keine Ausführungen, keine sich
entwickelnden Varianten-Wallets, keine Gewinnzahlen und keine Handelsfreigabe.

## Vorläufige, nicht optimierte Anti-FOMO-Regeln

- Einstieg blockieren bei mehr als 10 % Anstieg über 5 Minuten.
- Einstieg blockieren bei mehr als 25 % Anstieg über 15 Minuten.
- Einstieg blockieren bei mehr als 25 % Abstand zum beobachteten Tief über
  etwa 15 Minuten. Das ist eine messbare Näherung, keine erkannte Chart-Unterstützung.
- Referenzkurs liegt am oder bis zu 30 Sekunden vor dem Fensterbeginn.
  Dazwischen dürfen höchstens 60 Sekunden zwischen Beobachtungen liegen.
  Keine Interpolation. Fehlender Kurs, fehlender Anfang oder Konflikte blockieren.
- Nur bereits verfügbare Daten desselben Tokens, Pools und Quelltyps zählen.
  Weder zukünftige Kurse noch später verfügbare Risikobeobachtungen werden benutzt.
- Bestehende Risikovetos bleiben bestehen. Verkäufe werden nicht blockiert.

Genau auf der Grenze wird noch nicht blockiert. Die Regeln erlauben keine
Ausnahme nach einem subjektiv „sauberen Rücksetzer“ und enthalten keine
KI-Beurteilung, Kerzenmuster oder Volumenexplosionsprüfung. Dafür wären eigene
Definitionen und Prüfungen nötig. Die 15-Minuten-Anforderung kann viele sehr
frühe Einstiege vollständig ausschließen und im 30-Minuten-Beobachtungsfenster
die verfügbare Einstiegszeit stark verkürzen. Auch profitable Trades können
wegfallen. Fehlende Historie muss im späteren Vergleich separat gezählt werden.

## Positionsgröße: Planungsbudget statt garantierter Verlustgrenze

Annahme: höchstens **0,6 % des Handelskapitals** für den geplanten Verlust
inklusive Kostenpuffer. Das ist eine Forschungseinstellung, keine anhand der
laufenden Sammlung ausgewählte Verbesserung. Die bestehende Grenze von
standardmäßig 5 % Kapitaleinsatz, freies Cash und Poolbeteiligungsgrenze
bleiben zusätzliche Obergrenzen. Offene und vorgemerkte Käufe zählen weiterhin.

Für Budget B und beobachtete Liquidität L wird angesetzt:

```
fix = (2 + erlaubte Fehlversuche) × (Fixgebühr + Prioritätsgebühr)
faktor = Stop-Abstand + 2 × (Gebührensatz + Slippage) + Zusatzpuffer
geplanter Verlust = fix + B × faktor + 4 × B² / L
```

Standard: ein zusätzlicher Fehlversuch und 2 % Zusatzpuffer. Die variable
Komponente enthält beide Handelsseiten; der quadratische Term ist eine
vereinfachte Preiseinfluss-Schätzung. Das größte passende Budget wird nach
unten auf 0,000001 USD gerundet. Können bereits die festen Kosten das
Planungsbudget aufbrauchen, wird kein Einstieg vorgeschlagen. Höhere Kosten
oder ein weiterer Stop verringern bei sonst gleichen Eingaben die Größe.

Bei 50 USD ergeben 0,6 % ein Planungsbudget von 0,30 USD. Die neue Berechnung
nutzt den bestehenden Stop-Abstand; sie wählt keinen neuen Stop. In den
synthetischen Beispielen sinkt die vorgeschlagene Position unter die bisherigen
2,50 USD. Das ist keine Aussage über die spätere Rentabilität kleiner Trades.

**Keine garantierte Verlustobergrenze:** Stop-Ausführungen, Marktliquidität,
Kurslücken und wiederholte Fehler können erheblich schlechter ausfallen.
Das Planungsmodell ersetzt weder das bestehende Ausführungsmodell noch dessen
Risikovetos. Es gibt bislang kein gemeinsames Risikobudget für alle Positionen.

## Vor späterer Nutzung noch erforderlich

1. Laufende R2-Sammlung unverändert abschließen und nach Ende bewerten.
2. Die Regeln und Datenanforderungen vor einem neuen Vergleich festlegen.
   R2 kann anschließend Entwicklungsdaten liefern; für daran angepasste
   Varianten ist R2 kein unabhängiger Bestätigungstest mehr.
3. Varianten in einen getrennten Replay-/Paper-Ausführungspfad integrieren.
   Eigene Wallets, reservierte Mittel, Wiedereinstiege und Kosten nach jeder
   Ausführung müssen sich je Variante getrennt entwickeln. Den Größenplan
   vor Ausführung mit dem späteren Kurs erneut prüfen; bei Überschreitung
   blockieren oder neu berechnen. Das ist hier noch nicht implementiert.
4. Baseline, nur Filter, nur Größenberechnung und Kombination unter denselben
   Kosten-/Ausfallannahmen und anschließend in einem neuen zukünftigen
   Testfenster vergleichen. Datenlücken, verworfene Einstiege, Nettoergebnisse
   und Verluste vollständig berichten; nicht nur den besten Seed auswählen.

Die JSON-Vorschau enthält Parameter sowie Hashes des bestehenden Kerns und
des neuen Moduls. Diese dokumentieren den Stand; sie ersetzen noch kein
unabhängiges zukünftiges Variantenprotokoll. Kein LLM-Schlüssel erforderlich.
