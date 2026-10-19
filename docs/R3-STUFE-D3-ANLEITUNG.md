# R3 Stufe D3: dritter Probelauf über 24 Stunden, neustartfest

Stand: 19.10.2026. Warum ein dritter Lauf: Der zweite Lauf endete nach
7,4 Stunden durch einen Neustart des VPS (siehe
[R3-STUFE-D2-ERGEBNIS.md](R3-STUFE-D2-ERGEBNIS.md)). Abend und Nacht sind
deshalb auf dem VPS noch nicht gemessen.

Wie bisher ist das **kein Test** der Strategie. Es gibt keine Orders, und
kein Gewinn wird berechnet.

## Was gegenüber D2 anders ist

- Der Dienst ist für den Systemstart eingerichtet. Startet der VPS neu,
  setzt der Probelauf dieselbe Sammlung fort und endet von selbst zur
  geplanten Zeit. So lief auch R2.
- Der Bericht erkennt Ausfälle (mehr als 300 Sekunden ohne Sammelrunde).
  Werte pro Stunde rechnet er nur über die aktive Zeit. Abstände zwischen
  zwei Aufnahmen, in die ein Ausfall fällt, zählt er nicht mit, weil sie
  die Ausfallzeit messen und nicht das Angebot an Coins. Er weist sie
  getrennt aus.
- Der Bericht rechnet bei einem vorzeitigen Ende nur bis zum Stopp.
- Eigene Ordner und eigener Dienst:
  - Code: `/opt/memecoin-collector-r3-probe-d3`
  - Daten: `/var/lib/memecoin-collector-r3/probe-d3`
  - Dienst: `memecoin-collector-r3-probe-d3`
- D1 und D2 bleiben mit Code und Daten unverändert. Auf dem VPS wird nichts
  gelöscht.

Unverändert: 8 Plätze, ein neuer Coin höchstens alle 12 Minuten,
Vorfilter inklusive Poolalter, nur Profile von DEX Screener, Helius-Zugang
aus R2 nur lesend.

## Was ich vorher geprüft habe

- 389 Tests bestehen, darunter neue Tests für Ausfälle und vorzeitiges Ende.
- Installation simuliert, mit vorhandenen Läufen D1 und D2: D3 landet in
  eigenen Ordnern, der Dienst wird eingeschaltet (`enable --now`).
- Echter Neustart-Test in der Cloud: Probelauf gestartet, nach 90 Sekunden
  wie beim Herunterfahren gestoppt, nach 5,5 Minuten wieder gestartet. Er
  hat dieselbe Sammlung fortgesetzt, und der Bericht zeigte genau einen
  Ausfall von 345 Sekunden. Einen echten Neustart des VPS konnte ich nicht
  testen.

## Ablauf

"SSH-Konsole" heisst: in Windows-PowerShell zuerst
`ssh root@159.195.4.228` eingeben und das Passwort eintippen.

### Schritt 1: Paket herunterladen (Browser)

https://github.com/nicolasspzh/MemeCoin-tading_bot/blob/claude/zealous-allen-c87upf/uebergabe/2026-10-19/R3-Probelauf-D3/memecoin-r3-probe-d3.tar.gz

Rechts oben auf „Download raw file" klicken.

### Schritt 2: Helius-Credits notieren (Browser)

Direkt vor dem Start den Verbrauch im Helius-Dashboard notieren.

### Schritt 3: Paket auf den VPS kopieren (Windows-PowerShell, nicht in SSH)

```powershell
scp "$HOME\Downloads\memecoin-r3-probe-d3.tar.gz" root@159.195.4.228:/root/
```

### Schritt 4: Prüfen und starten (SSH-Konsole)

```bash
sha256sum /root/memecoin-r3-probe-d3.tar.gz
```

Erwartet: `dba44fb38f9962b024331c42505e246d7e0ccea55045175ee50aaaa9cfd826bd`.
Weicht sie ab, hier aufhören.

```bash
mkdir /root/r3-probe-d3
tar -xzf /root/memecoin-r3-probe-d3.tar.gz -C /root/r3-probe-d3
bash /root/r3-probe-d3/deploy/probe_r3.sh d3 24
```

Bitte die letzten etwa 20 Zeilen schicken.

### Schritt 5: Kontrolle nach etwa 15 Minuten (SSH-Konsole)

```bash
cd /opt/memecoin-collector-r3-probe-d3 && .venv/bin/python -m deploy.status --directory /var/lib/memecoin-collector-r3/probe-d3
systemctl is-enabled memecoin-collector-r3-probe-d3
```

Der zweite Befehl muss `enabled` ausgeben.

### Schritt 6: Bericht nach 24 Stunden (SSH-Konsole)

```bash
cd /opt/memecoin-collector-r3-probe-d3 && .venv/bin/python -m deploy.probe_report --directory /var/lib/memecoin-collector-r3/probe-d3
journalctl -u memecoin-collector-r3-probe-d3 --no-pager | tail -n 15
uptime -s
```

Die ganze Ausgabe schicken, dazu die Helius-Credits direkt nach dem Ende.

### Zwischendurch: Speicher ansehen (SSH-Konsole, freiwillig)

```bash
systemctl status memecoin-collector-r3-probe-d3 --no-pager | grep -E "Active|Memory"
grep -E "^(anon|file) " /sys/fs/cgroup/system.slice/memecoin-collector-r3-probe-d3.service/memory.stat
```

`anon` ist Speicher, den das Programm selbst belegt. `file` ist
Zwischenspeicher für Dateien, den Linux bei Bedarf wieder freigibt.

### Vorzeitig beenden (SSH-Konsole)

```bash
systemctl stop memecoin-collector-r3-probe-d3
```

Danach startet er beim nächsten Hochfahren wieder. Soll das nicht
passieren, zusätzlich: `systemctl disable memecoin-collector-r3-probe-d3`.

## Wann Stufe D3 bestanden ist

Dieselben Grenzen wie bei D1 und D2:

| Prüfung | Bestanden, wenn |
| --- | --- |
| Genug geeignete Coins | Mindestens 80 % der Abstände zwischen zwei Aufnahmen sind höchstens 900 Sekunden |
| Keine Orders | Orders und Ausführungen sind 0 |
| RPC-Verbrauch | Unter 2'900 Anfragen pro Stunde |
| DEX Screener | Fehler der Kursabfrage und des Vorfilters zusammen in weniger als 1 % der Runden |
| Halterprüfung | Höchstens 10 % der Beobachtungen mit Datenfehlern |

Neu, vor dem Lauf festgelegt: Abstände mit einem Ausfall darin zählen
nicht zur ersten Prüfung. Fallen mehr als 2 Stunden aus, gilt der Lauf als
unvollständig und wird nicht bewertet.

Zusätzlich werte ich die Stundenzahlen aus, ohne festes Kriterium.

## Grenzen

- Ein einzelner Tag. Wochentage und Wochenende können sich unterscheiden.
- Auch 24 Stunden liefern nur einige Dutzend geeignete Coins.
