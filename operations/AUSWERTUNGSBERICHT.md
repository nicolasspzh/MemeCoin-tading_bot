# Lesbarer Bericht zur späteren Auswertung

Stand: 9. Oktober 2026. Der Bericht ist eine zusätzliche Darstellung der
vorhandenen Phase-6-Ergebnisse. Er verändert keine Auswertung, Parameter,
Risikoregeln oder Datenbanken und ruft keine Marktdaten ab.

## Jetzt: ausschließlich künstliche Vorschau

Der Bericht kann offline im Browser gelesen werden, auch auf Windows ohne
Python. Die separat erzeugte Vorschau verwendet die 18 künstlichen
Demo-Beobachtungen und die unveränderten Standardparameter. Fehlende
Risikobelege oder null Trades bleiben sichtbar. Testdaten sind keine
Marktergebnisse. Alle sechs Kostenvarianten (baseline/stress, jeweils drei
Seeds) erscheinen; es wird kein bester Lauf ausgewählt.

## Nach dem Sammelende

1. R2 sammelt einschließlich Nachbeobachtung bis **16. Oktober 2026,
   03:06 Uhr Schweizer Zeit**. Vorher keine Strategieergebnisse aus den
   laufenden Testdaten ableiten oder Parameter daran anpassen.
2. Nach dem Ende den Dienststatus prüfen und eine konsistente SQLite-Sicherung
   erstellen. Nicht einfach eine laufende SQLite-Datei ohne ihre WAL-Datei
   kopieren. Die bestehende Sammlung aufbewahren.
3. Mit dem eingefrorenen R2-Code und dem passenden R2-Protokoll die bereits
   vorhandene `backtesting.evaluation evaluate`-Funktion auf der Sicherung
   ausführen. Einen neuen Ausgabeordner wählen. Das ergibt `result.json`.
4. Auf der Entwicklungsmaschine aus dieser Datei den Bericht erstellen:

   ```bash
   python -m operations.evaluation_report \
     --result runtime/MEINE-AUSWERTUNG/result.json \
     --out runtime/MEINE-AUSWERTUNG/bericht.html
   ```

5. `bericht.html` im Browser öffnen und gemeinsam prüfen. Der Renderer
   nimmt keine Marktfreigabe vor und prüft die Protokollherkunft nicht selbst.
   Er zeigt den Status ausdrücklich als Angabe aus der Ergebnisdatei.
   Die Ergebnisdatei bleibt unverändert; ihr SHA-256 steht im Bericht.

Es gibt keinen neuen Dienst und nichts zusätzlich auf dem VPS zu installieren.
Bestehende Ausgabedateien werden nicht überschrieben. Für eine korrigierte
Darstellung einen neuen Dateinamen wählen. Eine noch gesperrte Auswertung
erscheint als Wartehinweis, ohne Simulationswerte.

## Was die Zahlen bedeuten

- Netto realisiert: bereits erfasste simulierte Ergebnisse nach Modellkosten.
- Geschätztes Gesamtvermögen: beinhaltet Bewertungen offener Positionen und
  Reserven; kein garantierter Verkaufserlös.
- Größter Rückgang: nur an gespeicherten Messpunkten sichtbar, kein Beleg für
  den maximalen zwischenzeitlichen Marktverlust.
- Prioritätsgebühren sind bereits enthalten. Slippage und Preiseinfluss
  stecken bereits in Ausführungspreisen; Kosten nicht doppelt abziehen.
- Seeds sind Varianten desselben Datensatzes, keine unabhängigen Tests.
- Fehlende Messwerte heißen „nicht verfügbar“, nicht null.
- Viele Folgekurse bedeuten keine vollständige Marktabdeckung. Der bekannte
  Kapazitätsengpass und unvollständige Discovery bleiben Einschränkungen;
  diese Ergebnisdatei quantifiziert die ausgelassenen Coins nicht.
- `REVIEWABLE_HOLDOUT` erlaubt die inhaltliche Prüfung. Es bedeutet weder
  Profitabilität noch eine Freigabe für echtes Geld.

Der Bericht verwendet nur ausgewählte Felder. Rohdaten, lokale Eingabepfade
und RPC-Endpunkte werden nicht vollständig hineinkopiert. Unbekannte
Blocker bleiben unter ihrem technischen Namen sichtbar.
