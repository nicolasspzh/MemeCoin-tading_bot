"""Exercise upgrade ordering/recovery in a private filesystem with fake systemd.

Package installation and systemd are stubbed; SQLite preservation and shell
control flow are real. Network/data-flow behavior is tested separately.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from data.database import Database
from deploy.check_ready import ready

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('mode', ['success', 'tests_fail', 'readiness_fail'])
def test_upgrade_keeps_old_data_and_rolls_back_after_failed_cutover(tmp_path, quote, mode):
    opt, state, etc, commands, bundle = [tmp_path / name for name in ('opt', 'state', 'etc', 'bin', 'bundle')]
    for p in (opt, state, etc, commands, bundle / 'deploy'):
        p.mkdir(parents=True)
    old = opt / 'memecoin-collector'
    (old / '.venv/bin').mkdir(parents=True)
    (old / '.venv/bin/python').write_text('old executable')
    old_data = state / 'campaign'
    old_data.mkdir()
    (old_data / 'manifest.json').write_text('{}')
    (old_data / 'state.json').write_text('{}')
    db = Database(old_data / 'observations.sqlite3', 'dexscreener')
    with db.conn:
        db.add_snapshot(quote(source='dexscreener'))
    db.close()
    before = (old_data / 'observations.sqlite3').read_bytes()
    unit = etc / 'systemd/system/memecoin-collector.service'
    unit.parent.mkdir(parents=True)
    unit.write_text('ORIGINAL UNIT\n')
    (etc / 'memecoin-collector').mkdir()
    secret = etc / 'memecoin-collector/collector.env'
    secret.write_text('TEST_ONLY=untouched\n')
    (bundle / 'deploy/memecoin-collector-r2.service').write_text('NEW UNIT\n')
    (bundle / 'deploy/release.json').write_text(json.dumps({'previous_unit_sha256': hashlib.sha256(unit.read_bytes()).hexdigest()}))
    (bundle / 'requirements.txt').write_text('')
    script = (ROOT / 'deploy/upgrade.sh').read_text()
    script = script.replace('/opt', str(opt)).replace('/var/lib/memecoin-collector', str(state)).replace('/etc', str(etc))
    script = script.replace('> 5*1024**3', '> 0')  # host capacity is not this test's input
    (bundle / 'deploy/upgrade.sh').write_text(script)
    sums = ''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(bundle)}\n'
                   for p in sorted(bundle.rglob('*')) if p.is_file())
    (bundle / 'SHA256SUMS').write_text(sums)
    calls = tmp_path / 'systemctl-calls'
    def executable(name, text):
        path = commands / name
        path.write_text(text)
        path.chmod(0o755)
    executable('id', '#!/bin/sh\necho 0\n')
    executable('getent', '#!/bin/sh\nexit 0\n')
    executable('systemd-analyze', '#!/bin/sh\nexit 0\n')
    executable('sleep', '#!/bin/sh\nexit 0\n')
    executable('cat', '#!/bin/sh\nif [ "$1" = /proc/1/comm ]; then echo systemd; else /bin/cat "$@"; fi\n')
    executable('systemctl', f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{calls}"\nexit 0\n')
    wrapper = f'''#!{sys.executable}
import os,pathlib,sys
a=sys.argv[1:]
if a[:2]==['-m','venv']:
    p=pathlib.Path(a[2])/'bin'; p.mkdir(parents=True)
    (p/'python').symlink_to({str(commands / 'python3')!r})
    raise SystemExit(0)
if a[:2]==['-m','pip']: raise SystemExit(0)
if a[:2]==['-m','pytest']: raise SystemExit(1 if os.environ['UPGRADE_TEST_MODE']=='tests_fail' else 0)
if a[:2]==['-m','deploy.release_check']: raise SystemExit(0)
if a[:2]==['-m','deploy.check_ready']:
    if os.environ['UPGRADE_TEST_MODE']=='readiness_fail': raise SystemExit(1)
    print('{{"test":"readiness stub; not a real VPS result"}}')
    raise SystemExit(0)
os.execv({sys.executable!r},[{sys.executable!r},*a])
'''
    executable('python3', wrapper)
    env = dict(os.environ, PATH=str(commands)+':'+os.environ['PATH'], PYTHONPATH=str(ROOT), UPGRADE_TEST_MODE=mode)
    result = subprocess.run(['bash', str(bundle / 'deploy/upgrade.sh')], env=env, capture_output=True, text=True)
    assert result.returncode == (0 if mode == 'success' else 1), result.stdout + result.stderr
    assert (old_data / 'observations.sqlite3').read_bytes() == before
    assert secret.read_text() == 'TEST_ONLY=untouched\n'
    assert (old / '.venv/bin/python').read_text() == 'old executable'
    command_log = calls.read_text() if calls.exists() else ''
    if mode == 'success':
        assert unit.read_text() == 'NEW UNIT\n'
        assert (state / 'upgrade-r2/backup-check.json').exists()
        assert (state / 'upgrade-r2/completed-at').exists()
    else:
        assert unit.read_text() == 'ORIGINAL UNIT\n'
        if mode == 'tests_fail':
            assert 'stop ' not in command_log
            assert not (state / 'upgrade-r2').exists()
        else:
            assert command_log.count('start memecoin-collector') == 2
            assert not (state / 'upgrade-r2/completed-at').exists()


def test_readiness_needs_actual_prices_and_no_orders():
    value = {'supervisor_running': True, 'data': {'cycles': 1, 'priced_snapshots': 1,
              'last_quote_age_seconds': 5, 'orders': 0, 'fills': 0}}
    assert ready(value)
    for field, invalid in [('cycles', 0), ('priced_snapshots', 0), ('last_quote_age_seconds', 180), ('orders', 1)]:
        bad = {**value, 'data': {**value['data'], field: invalid}}
        assert not ready(bad)
