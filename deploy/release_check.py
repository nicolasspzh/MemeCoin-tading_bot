"""Validate deployment plan before stopping any existing VPS service."""
import json
from pathlib import Path

from backtesting.evaluation import load_protocol, utc
from data.models import utcnow

ROOT = Path(__file__).resolve().parents[1]


def validate_release(root=ROOT, *, now=None):
    config = json.loads((root / 'deploy/release.json').read_text())
    plan = load_protocol(root / config['protocol'])['plan']
    now = now or utcnow()
    if now >= utc(plan['test_start_utc']):
        raise ValueError('The future test window has already started; prepare a new future release')
    if (utc(config['until']) - utc(plan['test_end_exclusive_utc'])).total_seconds() != 3960:
        raise ValueError('Missing full follow-up allowance')
    return config


if __name__ == '__main__':
    config = validate_release()
    print('Neues Testfenster und unverändertes Protokoll geprüft.')
