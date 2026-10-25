# R3-Test: Installation und Betrieb

Stand: 20.10.2026. Regeln und Testfenster: [R3-PROTOKOLL.md](R3-PROTOKOLL.md).

**Wichtig:** Die Installation muss vor dem Teststart abgeschlossen sein,
also vor dem **21.10. um 02:00 Uhr Schweizer Zeit**. Danach verweigert die
Prüfung im Installationsskript den Start, und es braucht ein neues
Protokoll.

## Korrektur am 20.10. abends

Der erste Installationsversuch brach ab: Das Skript prüfte die Dienstdatei,
bevor der Code an seinem endgültigen Ort lag (`Command ... is not
executable`). Es wurde nichts installiert. Das Skript prüft die
Dienstdatei jetzt gegen die Zwischenkopie. Meine Simulation hatte das
nicht bemerkt, weil systemd dort nur ein Platzhalter war; der Platzhalter
prüft jetzt, ob das Programm existiert, und zeigt mit dem alten Skript
genau den Fehler vom VPS. Protokoll und Code-Fingerprint sind unverändert.

## Was ich vorher geprüft habe

- 397 Tests bestehen.
- Installation simuliert, mit vorhandenem Probelauf D3: Paketprüfung,
  Python-Umgebung, alle Tests, Prüfung von Protokoll, Code-Fingerprint,
  Testfenster, Dienstdatei und Sammeleinstellungen. Der Dienst wird
  eingeschaltet.
- Das installierte Paket lief in der Cloud kurz echt, mit dem R3-Profil und
  der echten Endzeit: Die Sammlung hat dasselbe Profil, denselben
  Code-Fingerprint und genau die Einstellungen des Protokolls. Speicher
  wird mitgeschrieben.
- Nicht getestet: echtes systemd auf dem VPS und die Halterprüfung mit
  Helius. Beides lief in den Probeläufen auf dem VPS.

## Schritte

"SSH-Konsole" heisst: in Windows-PowerShell zuerst
`ssh root@159.195.4.228` eingeben und das Passwort eintippen.

### 1. Paket herunterladen (Browser)

https://github.com/nicolasspzh/MemeCoin-tading_bot/blob/claude/zealous-allen-c87upf/uebergabe/2026-10-20/R3-Test/memecoin-r3-test.tar.gz

Rechts oben auf „Download raw file" klicken.

### 2. Helius-Credits notieren (Browser)

### 3. Paket kopieren (Windows-PowerShell, nicht in SSH)

```powershell
scp "$HOME\Downloads\memecoin-r3-test.tar.gz" root@159.195.4.228:/root/
```

### 4. Prüfen und installieren (SSH-Konsole)

```bash
sha256sum /root/memecoin-r3-test.tar.gz
```

Erwartet: `d6192bc624f45efab80954baa4a735efb34d74afbb81939f2a10cb08d5f29435`.
Weicht sie ab, hier aufhören.

```bash
mkdir /root/r3-test
tar -xzf /root/memecoin-r3-test.tar.gz -C /root/r3-test
bash /root/r3-test/deploy/install_r3.sh
```

Am Ende steht „R3-Test gestartet". Bitte die letzten etwa 20 Zeilen
schicken.

### 5. Kontrolle nach etwa 15 Minuten (SSH-Konsole)

```bash
cd /opt/memecoin-collector-r3 && .venv/bin/python -m deploy.status --directory /var/lib/memecoin-collector-r3/campaign-r3
```

### 6. Während des Tests (SSH-Konsole, etwa einmal am Tag)

Derselbe Statusbefehl wie in Schritt 5. Er zeigt nur Technik und
Datenabdeckung, keine Ergebnisse.

### 7. Nach dem 28.10. um 02:06 Uhr Schweizer Zeit (Winterzeit)

Dann ist auch die Nachbeobachtung vorbei. Weiter mit
[NACH-R3-ENDE.md](NACH-R3-ENDE.md): Datenbank sichern, kopieren und
auswerten, wie bei R2.

## Was nicht zu tun ist

- Den Dienst während des Tests nicht stoppen und nichts am Code ändern.
- Keine Probeläufe parallel starten.
- Auf dem VPS nichts löschen.
