# Vorschauen mit künstlichen Daten

- [Telegram-Nachrichten](paper-telegram.md): Tagesbericht, simulierter Kauf/Verkauf.
- [Auswertungsbericht](auswertung.html): sechs Simulationsläufe und offene Anforderungen.
- [Einstiegsvarianten](einstiegsvarianten.html): bisherige Regeln, Anti-FOMO,
  Risikogröße und Kombination auf drei künstlichen Testfällen.

HTML zeigt GitHub zunächst als Quelltext. Das Repository über **Code > Download
ZIP** herunterladen, entpacken und die gewünschte HTML-Datei in diesem Ordner
mit Doppelklick im Browser öffnen. Keine Installation und keine Internetverbindung
zum Ansehen erforderlich.

Die Dateien sind gespeicherte Vorschauen, keine Live-Anzeige. Sie senden keine
Nachrichten und erzeugen keine echten Trades. Ihre Geldbeträge sind künstlich
und keine Renditeprognose. Die Einstiegsvarianten berechnen überhaupt keine Gewinne.

Reproduzierbare neue Einstiegsprobe im eingerichteten Projekt:
`python -m operations.entry_variants --out runtime/NEUE-PROBE`.
Weitere Erläuterungen stehen unter `operations/` und im aktuellen Projektstand.
