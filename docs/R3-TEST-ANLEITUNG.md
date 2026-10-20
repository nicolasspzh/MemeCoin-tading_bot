# R3-Test: Installation und Betrieb

Stand: 20.10.2026. Regeln und Testfenster: [R3-PROTOKOLL.md](R3-PROTOKOLL.md).

**Wichtig:** Die Installation muss vor dem Teststart abgeschlossen sein,
also vor dem **21.10. um 02:00 Uhr Schweizer Zeit**. Danach verweigert die
Prüfung im Installationsskript den Start, und es braucht ein neues
Protokoll.

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

Erwartet: `94dc986d6b3fd0496d4e7d3f40842dc7de74b6b985512deb3e9ba00c5ea63654`.
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

### 7. Nach dem 28.10. um 03:06 Uhr Schweizer Zeit

Dann ist auch die Nachbeobachtung vorbei. Ich schreibe dafür eine eigene
Anleitung: Datenbank sichern, kopieren und auswerten, wie bei R2.

## Was nicht zu tun ist

- Den Dienst während des Tests nicht stoppen und nichts am Code ändern.
- Keine Probeläufe parallel starten.
- Auf dem VPS nichts löschen.
