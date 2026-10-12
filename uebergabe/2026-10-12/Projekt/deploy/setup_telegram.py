"""Interactive VPS-only setup. The bot token stays in a root-only file."""
import getpass
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys

from deploy.telegram_notify import api


ROOT = Path('/opt/memecoin-collector-r2')
CONFIG = Path('/etc/memecoin-collector/telegram.env')
UNITS = Path('/etc/systemd/system')


def pairing_chat(updates, nonce):
    matches = {}
    for update in updates:
        message = update.get('message', {})
        chat = message.get('chat', {})
        if (chat.get('type') == 'private' and message.get('text') == '/start ' + nonce
                and isinstance(chat.get('id'), int) and chat['id'] > 0):
            matches[chat['id']] = chat
    if len(matches) != 1:
        raise ValueError('Noch kein eindeutiger privater Chat mit dem Verbindungscode gefunden')
    return next(iter(matches.values()))


def main(*, app=ROOT, config=CONFIG, units=UNITS,
         campaign=Path('/var/lib/memecoin-collector/campaign-r2')):
    if os.geteuid() != 0 or not sys.stdin.isatty():
        print('Bitte als root in einer interaktiven SSH-Konsole ausführen.', file=sys.stderr)
        return 2
    try:
        for path in [config, *(units / f'memecoin-telegram.{suffix}' for suffix in ('service', 'timer'))]:
            if path.exists() or path.is_symlink():
                raise ValueError('Telegram-Konfiguration existiert bereits; vor einer Änderung prüfen')
        if not (campaign / 'manifest.json').is_file():
            raise ValueError('Zuerst das R2-Sammlerupdate installieren')
        for suffix in ('service', 'timer'):
            subprocess.run(['systemd-analyze', 'verify', str(app / f'deploy/memecoin-telegram.{suffix}')], check=True)
        print('Den Token eines eigenen neuen Bots von @BotFather eingeben. Er wird nicht angezeigt.')
        token = getpass.getpass('Telegram-Bot-Token: ').strip()
        bot = api(token, 'getMe', {})
        username = bot.get('username', '')
        if not bot.get('is_bot') or not re.fullmatch(r'[A-Za-z0-9_]+', username):
            raise ValueError('Bot-Identität konnte nicht geprüft werden')
        nonce = secrets.token_urlsafe(24)
        print('\nDiesen Link privat auf deinem Handy oder PC öffnen und in Telegram auf START drücken:')
        print(f'https://t.me/{username}?start={nonce}')
        chat = None
        for attempt in range(3):
            input('Danach hier Enter drücken: ')
            try:
                chat = pairing_chat(api(token, 'getUpdates', {'timeout': 0, 'limit': 100}), nonce)
                break
            except ValueError:
                print('Verbindungscode noch nicht gefunden. Den obigen Link öffnen und START drücken.')
        if chat is None:
            raise ValueError('Kein passender privater Chat gefunden; nichts aktiviert')
        os.umask(0o077)
        # Validated token alphabet and numeric chat ID cannot inject EnvironmentFile lines.
        with config.open('x') as out:
            out.write(f'TELEGRAM_BOT_TOKEN={token}\nTELEGRAM_CHAT_ID={chat["id"]}\nTELEGRAM_DAILY_REPORT=1\n')
        config.chmod(0o600)
        for suffix in ('service', 'timer'):
            subprocess.run(['install', '-m', '0644', str(app / f'deploy/memecoin-telegram.{suffix}'), str(units)], check=True)
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', 'enable', '--now', 'memecoin-telegram.timer'], check=True)
        subprocess.run(['systemctl', 'start', 'memecoin-telegram.service'], check=True)
        print('Telegram aktiviert. Erste Statusnachricht bestätigt; Tagesbericht ab 09:00 Uhr Schweizer Zeit.')
        print('Störungen werden alle fünf Minuten geprüft. Der Sammler wurde nicht neu gestartet.')
        return 0
    except (Exception, KeyboardInterrupt) as error:
        # Neither tokens nor provider exception URLs belong in terminal/log output.
        print(f'Einrichtung nicht abgeschlossen ({type(error).__name__}). Ausgabe ohne Token zur Prüfung schicken.', file=sys.stderr)
        print('Falls die Konfiguration schon gespeichert wurde, bleibt sie zur Diagnose erhalten.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
