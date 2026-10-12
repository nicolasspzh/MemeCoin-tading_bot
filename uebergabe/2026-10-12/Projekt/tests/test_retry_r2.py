"""Retry shell integration: fake systemd/providers, real SQLite preservation."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from data.database import Database

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('mode', ['success', 'delayed', 'no_quotes', 'preflight_fail', 'same_quote'])
def test_retry_preserves_both_databases_and_rolls_back_unconfirmed_data(tmp_path, quote, mode):
    opt, base, etc, commands = [tmp_path / name for name in ('opt', 'state', 'etc', 'bin')]
    commands.mkdir()
    old, new = opt / 'memecoin-collector', opt / 'memecoin-collector-r2'
    for app in (old, new):
        (app / '.venv/bin').mkdir(parents=True)
    for name in ('campaign', 'campaign-r2'):
        directory = base / name
        directory.mkdir(parents=True)
        (directory / 'manifest.json').write_text('{}')
        db = Database(directory / 'observations.sqlite3', 'dexscreener')
        with db.conn:
            db.add_snapshot(quote(source='dexscreener'))
        db.close()
    before = {name: (base/name/'observations.sqlite3').read_bytes() for name in ('campaign','campaign-r2')}
    (base / 'upgrade-r2').mkdir()
    (base / 'upgrade-r2/service.before').write_text('OLD UNIT\n')
    unit = etc / 'systemd/system/memecoin-collector.service'
    unit.parent.mkdir(parents=True)
    unit.write_text('OLD UNIT\n')
    (new / 'deploy').mkdir()
    (new / 'deploy/memecoin-collector-r2.service').write_text('R2 UNIT\n')
    (new / 'SHA256SUMS').write_text(hashlib.sha256(b'R2 UNIT\n').hexdigest()+'  deploy/memecoin-collector-r2.service\n')
    script = (ROOT / 'deploy/retry_r2.sh').read_text()
    script = script.replace('/opt', str(opt)).replace('/var/lib/memecoin-collector', str(base)).replace('/etc', str(etc))
    script = script.replace('/run/lock/memecoin-r2-retry.lock', str(tmp_path / 'retry.lock'))
    target = tmp_path / 'retry.sh'
    target.write_text(script)
    calls, checks = tmp_path / 'calls', tmp_path / 'checks'
    def executable(name, content):
        path = commands / name
        path.write_text(content)
        path.chmod(0o755)
    executable('id', '#!/bin/sh\necho 0\n')
    executable('systemctl', f'#!/bin/sh\necho "$*" >> "{calls}"\nexit 0\n')
    executable('systemd-analyze', '#!/bin/sh\nexit 0\n')
    executable('sleep', '#!/bin/sh\nexit 0\n')
    executable('seq', '#!/bin/sh\necho "1 2 3 4 5 6 7 8 9 10"\n')
    wrapper = f'''#!{sys.executable}
import datetime,json,os,pathlib,sys
a=sys.argv[1:]
mode=os.environ['RETRY_TEST_MODE']
if a[:2]==['-m','deploy.release_check']: raise SystemExit(1 if mode=='preflight_fail' else 0)
if a[:2]==['-m','deploy.status']:
    print('FAKE status, not a real VPS probe'); raise SystemExit(0)
if a[:2]==['-m','deploy.check_ready']:
    p=pathlib.Path({str(checks)!r}); count=int(p.read_text())+1 if p.exists() else 1; p.write_text(str(count))
    if mode=='no_quotes' or (mode=='delayed' and count<=7): raise SystemExit(1)
    stamp=pathlib.Path({str(tmp_path / 'quote-time')!r})
    value=stamp.read_text() if mode=='same_quote' and stamp.exists() else datetime.datetime.now(datetime.UTC).isoformat()
    stamp.write_text(value)
    print(json.dumps({{'data':{{'last_quote_at':value}}}})); raise SystemExit(0)
if a[:2]==['-', {str(unit)!r}]: raise SystemExit(0) # installed-release preflight is mocked
os.execv({sys.executable!r},[{sys.executable!r},*a])
'''
    executable('python-wrapper', wrapper)
    for app in (old, new):
        (app / '.venv/bin/python').symlink_to(commands / 'python-wrapper')
    env = dict(os.environ, PATH=str(commands)+':'+os.environ['PATH'], PYTHONPATH=str(ROOT), RETRY_TEST_MODE=mode)
    result = subprocess.run(['bash',str(target),'--worker'], env=env, capture_output=True, text=True, timeout=20)
    success = mode in {'success','delayed'}
    assert result.returncode == (0 if success else 1), result.stdout + result.stderr
    assert unit.read_text() == ('R2 UNIT\n' if success else 'OLD UNIT\n')
    for name, content in before.items():
        assert (base/name/'observations.sqlite3').read_bytes() == content
    assert (base/'upgrade-r2/service.before').read_text() == 'OLD UNIT\n'
    log = calls.read_text() if calls.exists() else ''
    attempts = list(base.glob('upgrade-r2-retry-*'))
    if mode == 'preflight_fail':
        assert 'stop ' not in log and not attempts
    else:
        assert len(attempts) == 1
        assert (attempts[0]/'r1.before.sqlite3').exists()
        assert (attempts[0]/'r2.before.sqlite3').exists()
        assert (attempts[0]/'completed-at').exists() == success
        if success:
            assert int(checks.read_text()) >= 2
        else:
            assert (attempts[0]/'rollback-at').exists()
            assert log.count('start memecoin-collector') == 2
