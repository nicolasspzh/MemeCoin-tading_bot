# Leseanleitung für Claude

Am 12. Oktober 2026 wurde das vollständige entpackte Übergabepaket auf
ausdrücklichen Wunsch des Benutzers in dieses Repository aufgenommen.

## Zuerst lesen

1. [Startauftrag](2026-10-12/START-FUER-CLAUDE.md)
2. [Vollständige Übergabe](2026-10-12/UEBERGABE.md)
3. [Prüfstand des Pakets](2026-10-12/PRUEFUNG.json)
4. [Eingefrorene Parameter](2026-10-12/PARAMETER-R2.json)
5. [Aktuelle Repository-Startseite](../README.md) und
   [letzter bestätigter Betriebsstand vom 10. Oktober](../docs/PROJEKTSTAND.md)
6. Alle Anleitungen, danach Code und Tests im Repository-Hauptverzeichnis.

## Aktuellen Code und historische Kopien unterscheiden

- Die Verzeichnisse `collectors/`, `trading/`, `operations/`, `backtesting/`,
  `config/`, `data/`, `deploy/`, `scripts/`, `tests/` und `docs/` im
  **Repository-Hauptverzeichnis** bilden die weiterzuführende Codebasis.
- `2026-10-12/Projekt/` ist die unveränderte Quellkopie des Commits
  `73fa133e3903628b568532a049253572f61e5297` aus dem ursprünglichen ZIP.
  Sie ist eine Referenz, kein zweites zu pflegendes Projekt.
- `R2-Referenz/development.sqlite3` enthält bekannte eingefrorene
  Entwicklungsbeobachtungen. Es sind **nicht** die laufenden R2-VPS-Testdaten.
- `Historische-Pakete/` enthält alte Installationsartefakte zur Zuordnung.
  Nicht erneut installieren oder alte Dienste starten.
- `SHA256SUMS` belegt die unveränderten Dateien des ursprünglichen Pakets.
  Änderungen an aktuellen Anleitungen außerhalb dieses Ordners verändern
  die eingefrorene Paketkopie nicht.

Hinweise im eingefrorenen Paket wie „nicht im Git-Repository“ oder „nicht
automatisch öffentlich laden“ beschreiben den Stand vor dieser ausdrücklichen
Upload-Anweisung. Nun ist genau dieses Paket vorhanden. Zugangsdaten und die
aktuelle VPS-Datenbank bleiben ausgeschlossen. Der Quellcommit im Paket
beschreibt seine Herkunft und ist nicht automatisch der neueste Repository-Commit.

## Grenzen der Übergabe

Der letzte bestätigte VPS-Status ist vom **10. Oktober 2026, 16:23:16 CEST**.
Ein Dokument beweist keinen heutigen Prozesszustand. Das geplante Sammelende
ist **16. Oktober 2026, 03:06 Uhr Europe/Zurich**. Bestehenden Sammler nicht
ändern, keine vorzeitige Strategieauswertung, keine Echtgeldorders.

Wer nur Browserzugriff hat, kann Binärdaten nicht als Text lesen. Für eine
vollständige Prüfung das Repository klonen/herunterladen, SQLite lesend öffnen
und Archive zunächst auflisten und prüfen. Keine Installationsskripte zum
„Lesen“ ausführen. Nicht behaupten, unzugängliche Dateien geprüft zu haben.
