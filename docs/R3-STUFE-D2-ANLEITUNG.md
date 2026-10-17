# R3 Stufe D2: zweiter Probelauf über 24 Stunden

Stand: 17.10.2026. Warum ein zweiter Lauf: Der erste Probelauf (8 Stunden
am Tag) fand nur 2,8 geeignete Coins pro Stunde. Eine Messung am Abend
ergab 6,0 pro Stunde. Das Angebot hängt also vermutlich von der Tageszeit
ab. Ein Lauf über 24 Stunden deckt jede Tageszeit einmal ab. Details zum
ersten Lauf: [R3-STUFE-D-ERGEBNIS.md](R3-STUFE-D-ERGEBNIS.md).

Wie beim ersten Lauf ist das **kein Test** der Strategie. Es gibt keine
Orders, und kein Gewinn wird berechnet.

## Was gegenüber dem ersten Lauf anders ist

- Dauer 24 statt 8 Stunden. Neue Coins werden bis etwa 66 Minuten vor dem
  Ende aufgenommen.
- Der Vorfilter nimmt keine Coins mehr auf, deren Pool älter als 24 Stunden
  ist oder deren Poolalter unbekannt ist. Dort sperrt die Einstiegsprüfung
  ohnehin immer.
- Der Bericht zeigt Entdeckungen, geeignete Coins und Aufnahmen pro Stunde
  (in UTC).
- Eigene Ordner und eigener Dienst:
  - Code: `/opt/memecoin-collector-r3-probe-d2`
  - Daten: `/var/lib/memecoin-collector-r3/probe-d2`
  - Dienst: `memecoin-collector-r3-probe-d2`
- Der erste Lauf bleibt mit Code und Daten unverändert erhalten. Auf dem
  VPS wird nichts gelöscht.

Unverändert: 8 Plätze, ein neuer Coin höchstens alle 12 Minuten, nur
Profile von DEX Screener als Liste, Helius-Zugang aus R2 nur lesend.

## Was ich vorher geprüft habe

- 387 Tests bestehen.
- Installation in der Cloud simuliert, mit vorhandenem erstem Lauf: Der
  zweite Lauf landet in eigenen Ordnern, die Daten des ersten bleiben
  unberührt. Das Skript bricht ab, wenn die Ordner schon existieren, wenn
  ein anderer Probelauf noch aktiv ist oder wenn die Angaben fehlen.
- Kurzer echter Lauf in der Cloud mit dem neuen Paket: Vorfilter, Aufnahme
  und Bericht mit Stundenauswertung funktionieren. Die Halterprüfung lässt
  sich dort weiterhin nicht testen (öffentlicher Solana-Zugang).

## Ablauf

### Schritt 1: Paket herunterladen (Browser)

https://github.com/nicolasspzh/MemeCoin-tading_bot/blob/claude/zealous-allen-c87upf/uebergabe/2026-10-17/R3-Probelauf-D2/memecoin-r3-probe-d2.tar.gz

Rechts oben auf „Download raw file" klicken.

### Schritt 2: Helius-Credits notieren (Browser)

Direkt vor dem Start den Verbrauch im Helius-Dashboard notieren.

### Schritt 3: Paket auf den VPS kopieren (Windows-PowerShell, nicht in SSH)

```powershell
scp "$HOME\Downloads\memecoin-r3-probe-d2.tar.gz" root@159.195.4.228:/root/
```

### Schritt 4: Verbinden (Windows-PowerShell)

```powershell
ssh root@159.195.4.228
```

### Schritt 5: Prüfsumme kontrollieren (SSH-Konsole)

```bash
sha256sum /root/memecoin-r3-probe-d2.tar.gz
```

Erwartet: `2047d75417933e09602734de64be50e1b71885766c810400867ea5abc90e84db`.
Weicht sie ab, hier aufhören.

### Schritt 6: Entpacken und starten (SSH-Konsole)

```bash
mkdir /root/r3-probe-d2
tar -xzf /root/memecoin-r3-probe-d2.tar.gz -C /root/r3-probe-d2
bash /root/r3-probe-d2/deploy/probe_r3.sh d2 24
```

`d2` ist die Nummer des Probelaufs, `24` die Dauer in Stunden. Am Ende
steht „Probelauf gestartet" mit der Endzeit in UTC (Schweizer Zeit: plus
2 Stunden). Bitte die letzten etwa 20 Zeilen schicken.

### Schritt 7: Kontrolle nach etwa 15 Minuten (SSH-Konsole)

```bash
cd /opt/memecoin-collector-r3-probe-d2 && .venv/bin/python -m deploy.status --directory /var/lib/memecoin-collector-r3/probe-d2
```

### Schritt 8: Bericht nach 24 Stunden (SSH-Konsole)

```bash
cd /opt/memecoin-collector-r3-probe-d2 && .venv/bin/python -m deploy.probe_report --directory /var/lib/memecoin-collector-r3/probe-d2
```

Die ganze Ausgabe schicken, dazu die Helius-Credits direkt nach dem Ende.

### Vorzeitig beenden (SSH-Konsole)

```bash
systemctl stop memecoin-collector-r3-probe-d2
```

## Wann Stufe D2 bestanden ist

Dieselben Grenzen wie beim ersten Lauf, unverändert:

| Prüfung | Bestanden, wenn |
| --- | --- |
| Genug geeignete Coins | Mindestens 80 % der Abstände zwischen zwei Aufnahmen sind höchstens 900 Sekunden |
| Keine Orders | Orders und Ausführungen sind 0 |
| RPC-Verbrauch | Unter 2'900 Anfragen pro Stunde |
| DEX Screener | Fehler der Kursabfrage und des Vorfilters zusammen in weniger als 1 % der Runden |
| Halterprüfung | Höchstens 10 % der Beobachtungen mit Datenfehlern |

Zusätzlich werte ich die Stundenzahlen aus, ohne festes Kriterium: Gibt es
Tageszeiten, in denen kaum geeignete Coins kommen? Davon hängt ab, wie wir
den Aufnahmetakt für den R3-Test festlegen.

## Grenzen

- Ein einzelner Tag. Wochentage und Wochenende können sich unterscheiden.
- Auch 24 Stunden liefern nur einige Dutzend geeignete Coins. Die Zahlen
  pro Stunde bleiben unsicher.
