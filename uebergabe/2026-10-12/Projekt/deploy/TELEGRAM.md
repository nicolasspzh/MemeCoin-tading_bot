# Telegram für den Sammler

Optionaler Zusatz zum Updatepaket `memecoin-update-20261008-v3.tar.gz`.
Telegram wird erst durch die folgenden Schritte auf dem VPS aktiviert.
Ein eigener Timer liest alle fünf Minuten den lokalen Status. Er sendet einen
Tagesbericht beim ersten Prüflauf ab **09:00 Uhr Europe/Zurich** sowie Meldungen
bei geänderten Betriebsstörungen, Entwarnungen und beim geplanten Sammelende.
Es werden keine Telegram-Befehle zum Kaufen, Verkaufen oder Ändern des Sammlers
angenommen. Das eingefrorene Testprotokoll bleibt unverändert.

## Einrichtung zu Hause

1. Zuerst das Sammlerupdate gemäß [UPDATE-R2.md](UPDATE-R2.md) installieren.
2. In Telegram den offiziellen **@BotFather** öffnen, `/newbot` senden und
   einen eigenen neuen Bot erstellen. BotFather fragt einen Anzeigenamen und
   einen freien Benutzernamen, der auf `bot` endet. Den erhaltenen **Token
   privat halten**, nicht in Chat, Screenshot oder Quellcode einfügen.
3. In der root-SSH-Konsole:

```bash
cd /opt/memecoin-collector-r2
.venv/bin/python -m deploy.setup_telegram
```

4. Den Bot-Token an der unsichtbaren Eingabe einfügen und Enter drücken.
   Auch Sternchen werden nicht angezeigt. Das Programm prüft den Bot und zeigt
   einen persönlichen Telegram-Link mit einem zufälligen Verbindungscode.
5. Diesen Link öffnen, beim Bot auf **START** drücken und anschließend in der
   SSH-Konsole Enter drücken. Nur der private Chat mit diesem Verbindungscode
   wird verwendet; Gruppenchats und fremde Startnachrichten werden ignoriert.
6. Die erste Statusnachricht sollte in Telegram ankommen. Bei einem Fehler
   die Ausgabe ohne Zugangsdaten zur Diagnose weitergeben.

Der Token und die ermittelte Chat-ID liegen anschließend ausschließlich in
`/etc/memecoin-collector/telegram.env` (root, Modus 0600). Der Sammler wird dabei
nicht neu gestartet. Eine bestehende Telegram-Konfiguration wird nicht
automatisch überschrieben. Für das Einrichten benötigt der Bot keinen Webhook,
keine offene Server-Portfreigabe und keinen Zugriff auf eine Wallet.

## Meldungen

- Kein aktiver Sammler, fehlendes Lebenszeichen oder fünf Minuten ohne frischen Kurs.
- Mindestens 90 % des Tages- oder Gesamtbudgets für RPC-Anfragen verbraucht.
- Weniger als 2 GiB freier Speicher, fehlende aktuelle Sicherung nach zwei
  Stunden Laufzeit oder eine Sicherung ohne bestätigte Integritätsprüfung.
- Unerwartete Orders oder Ausführungen im Beobachtungsmodus.
- Nicht lesbarer Sammlerstatus, Änderungen dieser Hinweise und geplantes Ende.

Unveränderte Störungen erzeugen keine neue Warnung alle fünf Minuten. Sie stehen
weiterhin im Tagesbericht. Fehlgeschlagene Telegram-Zustellungen werden beim
nächsten Prüflauf wieder versucht. Bei einem Absturz direkt nach dem Versand
kann eine Nachricht doppelt eintreffen. Neue oder verschwundene Hinweise werden
gemeinsam mit dem aktuellen Status gemeldet. Die erste Nachricht kurz nach
dem Start kann noch fehlende Kurse oder Lebenszeichen melden.

Der Tagesbericht zeigt Beobachtungen, Kurslücken, Folgekurse, Anfragebudget und
Sicherungsstatus. Er enthält keine Zugangsdaten, Wallet-Schlüssel oder
Gewinnauswertung. Helius-Credits werden **nicht** aus RPC-Anfragen abgeleitet;
den tatsächlichen Verbrauch weiterhin im Helius-Dashboard prüfen.

Die Überwachung läuft auf demselben VPS. Bei komplettem Server- oder
Internetausfall kann sie selbst keine Warnung verschicken. Ein unabhängiger
externer Verfügbarkeitsmonitor ist hier nicht enthalten. Bei kaputtem Token,
blockiertem Bot oder Telegram-Ausfall fehlt ebenfalls die Zustellung; dann
steht der Fehler im Dienstjournal. Ein ausbleibender Tagesbericht ist daher
ein Anlass, den Serverstatus zu prüfen.

## Prüfen oder ausschalten

```bash
systemctl status memecoin-telegram.timer --no-pager
journalctl -u memecoin-telegram.service -n 20 --no-pager
```

Nur Telegram ausschalten (die Datensammlung läuft weiter):

```bash
systemctl disable --now memecoin-telegram.timer
systemctl stop memecoin-telegram.service
```

Netzziel: `api.telegram.org:443`. Die Cloud-Entwicklungsumgebung benötigt diesen
Zugang und den Token nicht: Dort werden ausschließlich simulierte Antworten
getestet. Auf dem VPS müssen normale ausgehende HTTPS-Verbindungen erlaubt sein.
