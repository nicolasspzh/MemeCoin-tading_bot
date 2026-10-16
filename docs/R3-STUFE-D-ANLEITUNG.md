# R3 Stufe D: Probelauf des Sammlers mit Vorfilter

Stand: 16.10.2026. Ziel: messen, ob es mit dem Vorfilter genug geeignete
Coins gibt und ob die Abfragegrenzen eingehalten werden. Das ist **kein
Test** der Strategie. Es gibt keine Orders, kein Gewinn wird berechnet.

## Was der Probelauf macht

- Er sammelt 8 Stunden lang, dann endet er von selbst.
- Er arbeitet wie R2: 8 Plätze, höchstens ein neuer Coin alle 12 Minuten,
  30 Minuten Anfangsphase, danach Nachbeobachtung. Neu ist nur der
  Vorfilter: Aufgenommen wird nur ein Coin mit Raydium CPMM oder PumpSwap,
  Gegenwährung wSOL oder USDC, Kurs und mindestens 10'000 USD Liquidität.
- Neue Coins werden bis etwa 66 Minuten vor dem Ende aufgenommen. Danach
  laufen nur noch die Nachbeobachtungen.
- Er nutzt den Helius-Zugang aus R2 (`/etc/memecoin-collector/collector.env`)
  nur lesend. Ich brauche keinen Schlüssel von dir.

## Was er nicht macht

- An R2 ändert sich nichts: Weder Code noch Dienst noch Daten noch
  Konfiguration werden angefasst. Auf dem VPS wird nichts gelöscht.
- Der Probelauf bekommt eigene Ordner:
  - Code: `/opt/memecoin-collector-r3-probe`
  - Daten: `/var/lib/memecoin-collector-r3/probe-d1`
  - Dienst: `memecoin-collector-r3-probe`
- Der Dienst startet nicht beim Hochfahren. Startet der VPS während des
  Probelaufs neu, endet der Probelauf. Dann sag mir einfach Bescheid.
- Das Installationsskript bricht ab, ohne etwas zu verändern, wenn einer
  dieser Ordner oder der Dienst schon existiert oder wenn der R2-Sammler noch
  läuft.

## Was ich vorher geprüft habe

- 381 Tests bestehen, darunter neue Tests für das Probelauf-Profil und den
  Bericht.
- Die ganze Installation habe ich in der Cloud simuliert, mit umgeleiteten
  Ordnern und Platzhaltern für systemd: Paketprüfung, Python-Umgebung, alle
  Tests, Dienstdatei. Das echte systemd auf dem VPS konnte ich nicht testen.
- Ein echter Kurzlauf in der Cloud mit öffentlichem Solana-Zugang hat
  Vorfilter, Aufnahme, Statusbefehl und Bericht bestätigt. Die Halterprüfung
  konnte ich dort nicht testen, weil die öffentlichen Zugänge die nötige
  Abfrage (`getTokenLargestAccounts`) nicht liefern. Mit Helius hat sie in R2
  funktioniert.
- DEX-Screener-Grenzen laut offizieller API-Beschreibung: Kursabfrage
  (`/tokens/v1/...`) 300 Anfragen pro Minute mit bis zu 30 Adressen,
  Profilliste 60 pro Minute. Der Sammler fragt alle 20 Sekunden ab. Das sind
  pro Minute höchstens etwa 30 Kursabfragen (meist 3 bis 6) und eine
  Profilabfrage.

## Ablauf

"SSH-Konsole" heisst wie bisher: in Windows-PowerShell zuerst
`ssh root@159.195.4.228` eingeben und das Passwort eintippen.

### Schritt 1: Paket herunterladen (Browser)

Auf GitHub im Repository den Branch `claude/zealous-allen-c87upf` öffnen,
dann die Datei
`uebergabe/2026-10-16/R3-Probelauf/memecoin-r3-probe.tar.gz` öffnen und
rechts oben auf „Download raw file" klicken. Die Datei landet in
`Downloads`.

### Schritt 2: Helius-Credits notieren (Browser)

Im Helius-Dashboard den aktuellen Verbrauch notieren. So sehen wir nachher,
was der Probelauf gekostet hat.

### Schritt 3: Paket auf den VPS kopieren (Windows-PowerShell, nicht in SSH)

```powershell
scp "$HOME\Downloads\memecoin-r3-probe.tar.gz" root@159.195.4.228:/root/
```

Passwort wie bei SSH. Alternativ mit WinSCP nach `/root/` ziehen.

### Schritt 4: Prüfen und installieren (SSH-Konsole)

Zuerst prüfen, dass R2 nicht mehr läuft:

```bash
systemctl is-active memecoin-collector
```

Erwartet: `inactive`. Bei jeder anderen Ausgabe hier aufhören und mir die
Ausgabe schicken.

Dann die Prüfsumme des Pakets:

```bash
sha256sum /root/memecoin-r3-probe.tar.gz
```

Erwartet: `f90ecadf0791e3234ff48e9c343050a3570e7753d4173dd7443383a67e310972`.
Weicht sie ab, hier aufhören.

Dann entpacken und installieren:

```bash
mkdir /root/r3-probe
tar -xzf /root/memecoin-r3-probe.tar.gz -C /root/r3-probe
bash /root/r3-probe/deploy/probe_r3.sh
```

Das dauert einige Minuten (Python-Pakete laden, 381 Tests). Am Ende steht
„Probelauf gestartet" mit der Endzeit in UTC. Schweizer Zeit ist zurzeit
UTC plus 2 Stunden. Bitte schick mir die letzten etwa 20 Zeilen der Ausgabe.

### Schritt 5: Kontrolle nach etwa 15 Minuten (SSH-Konsole)

```bash
cd /opt/memecoin-collector-r3-probe && .venv/bin/python -m deploy.status --directory /var/lib/memecoin-collector-r3/probe-d1
```

Erwartet: „Sammler-Prozess: aktiv", ein Lebenszeichen vor wenigen Sekunden,
Orders und Ausführungen 0. Bitte schick mir die Ausgabe.

Falls etwas nicht stimmt, zusätzlich:

```bash
journalctl -u memecoin-collector-r3-probe -n 30 --no-pager
```

### Schritt 6: Bericht nach dem Ende (SSH-Konsole)

Nach den 8 Stunden:

```bash
cd /opt/memecoin-collector-r3-probe && .venv/bin/python -m deploy.probe_report --directory /var/lib/memecoin-collector-r3/probe-d1
```

Bitte die ganze Ausgabe schicken, inklusive des JSON-Teils, und dazu den
neuen Stand der Helius-Credits.

Den Bericht kannst du auch zwischendurch abrufen. Er liest nur und stört den
Probelauf nicht.

### Vorzeitig beenden (SSH-Konsole)

```bash
systemctl stop memecoin-collector-r3-probe
```

Die Daten bleiben erhalten.

## Wann Stufe D bestanden ist

Diese Grenzen lege ich jetzt fest, bevor es Daten gibt:

| Prüfung | Bestanden, wenn |
| --- | --- |
| Genug geeignete Coins | Mindestens 80 % der Abstände zwischen zwei Aufnahmen sind höchstens 900 Sekunden (geplant: 720) |
| Keine Orders | Orders und Ausführungen sind 0 |
| RPC-Verbrauch | Hochgerechnet auf 24 Stunden unter dem Tageslimit von 70'000 Anfragen, also unter 2'900 pro Stunde |
| DEX Screener | Fehler der Kursabfrage und des Vorfilters zusammen in weniger als 1 % der Runden |
| Halterprüfung | Höchstens 10 % der Beobachtungen mit Datenfehlern (R2: rund 4 %) |

Nur zur Information, kein Kriterium: wie viele Beobachtungen alle
Einstiegsprüfungen bestehen. Diese Zahl wird nicht verwendet, um Regeln
anzupassen.

## Grenzen

- 8 Stunden zu einer Tageszeit sind nicht repräsentativ für eine ganze Woche.
- Der Vorfilter prüft nur, wenn eine Aufnahme fällig ist. Er zeigt also, ob
  es genug Coins für den geplanten Takt gibt, nicht wie viele es insgesamt
  gibt.
- Helius-Credits und Anfragen sind verschiedene Einheiten. Den Verbrauch an
  Credits sehen wir nur im Dashboard.
