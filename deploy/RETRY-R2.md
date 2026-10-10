# R2 nach dem v3-Rollback erneut starten

> Historischer Ablauf. R2 ist bereits eingerichtet und sammelt. Nicht erneut installieren oder starten; siehe [aktueller Projektstand](../docs/PROJEKTSTAND.md).

Die VPS-Ausgabe vom 8. Oktober bestätigt: R2 hat sieben Runden abgeschlossen,
aber der zuerst zugelassene Coin hatte keinen DEX-Kurs. Der nächste Coin wird
erst nach zwölf Minuten zugelassen. Der v3-Installer hatte bereits nach zwei
Minuten ohne Kurs zurückgeschaltet. Das war eine unpassend kurze Startprüfung,
kein Beleg dafür, dass der neue Prozess nicht startete. R1 wurde wieder gestartet.

`retry_r2.sh` ist ein einmaliger Wiederholungsversuch für genau diese bereits
installierte, unveränderte v3-Version. Das ursprüngliche `upgrade.sh` nicht erneut
ausführen, keine Verzeichnisse löschen und keine Manifestprüfsummen ändern.

Die ausgelieferte Datei heißt `memecoin-r2-retry.sh`. Mit WinSCP nach `/root/`
kopieren, dann in der root-SSH-Konsole:

```bash
bash /root/memecoin-r2-retry.sh
```

Das Skript startet einen eigenen temporären systemd-Dienst. Die SSH-Konsole
kann geschlossen werden. Nach dem Start zeigt folgender Befehl den Fortschritt:

```bash
journalctl -u memecoin-r2-retry -n 25 --no-pager
```

Die Startprüfung selbst dauert höchstens ungefähr 40 Minuten; Vorprüfungen und
Sicherungen kommen hinzu. Eine zusätzliche systemd-Grenze beendet den Versuch
nach spätestens 55 Minuten. Ein vollständiger VPS-Ausfall ist damit nicht
abgesichert. Der Versuch verlangt mindestens 45 Minuten bis zum festgelegten
Testbeginn am 9. Oktober 02:00 Uhr Schweizer Zeit.

Vor der Umschaltung prüft er installierte SHA256SUMS, altes Dienstlayout,
R2-Manifest, Code-/Serviceprüfsummen, Speicher und das zukünftige Testfenster.
Er stoppt nur den MemeCoin-Dienst, sichert R1 und R2 mit SQLite und prüft deren
Integrität. Die bisherige Sicherung `upgrade-r2` wird nicht überschrieben.
Alle neuen Nachweise liegen in einem neuen `upgrade-r2-retry-*`-Verzeichnis.

R2 wird mit seinem bestehenden Datenbestand und unveränderten Parametern
fortgesetzt. Erfolg erfordert zwei verschiedene frische Kurszeitpunkte nach
dem Startversuch, einen laufenden Supervisor und weiterhin null Orders/Fills.
Kein Coin wird anhand späteren Erfolgs ausgetauscht; der Aufnahmeplan bleibt
unverändert. Ist die Prüfung erfolglos oder wird der Helfer regulär beendet,
versucht er die alte Dienstkonfiguration wiederherzustellen und R1 zu starten.
Bei fehlgeschlagenem Wiederstart meldet er den Fehler ausdrücklich. Ein
erfolgreicher Startbefehl allein bestätigt noch keinen frischen R1-Datenfluss.

Der Helfer ist mit simulierten systemd-/Provider-Antworten und echten SQLite-
Sicherungen geprüft: sofortige/verzögerte Kurse, dauerhaft fehlende Kurse,
wiederholter identischer Kurs und Vorprüfungsfehler. Er ist noch nicht auf dem
externen VPS ausgeführt. Weitere API-Ausfälle und unzureichende Datenabdeckung
können weiterhin auftreten; auch die längere Prüfzeit garantiert keinen Kurs.

Bei `ERFOLGREICH` anschließend den aktuellen R2-Status prüfen:

```bash
cd /opt/memecoin-collector-r2
.venv/bin/python -m deploy.status
```

Erst nach bestätigtem R2-Datenfluss Telegram einrichten. Ein weiterer Versuch
nach erneutem Fehler muss anhand seiner Ausgabe geprüft werden; der Helfer
ersetzt keine Diagnose wiederholter Ausfälle.
