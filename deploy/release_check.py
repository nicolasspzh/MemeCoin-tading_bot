"""Validate deployment plan before stopping any existing VPS service."""
import json
from pathlib import Path

from backtesting.evaluation import EXCLUDED_SETTINGS, load_protocol, utc
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
    for key in ('test_start_utc', 'test_end_exclusive_utc'):
        if key in config and utc(config[key]) != utc(plan[key]):
            raise ValueError('Release window differs from the frozen protocol')
    if config.get('unit'):
        # The service must collect with exactly the profile, folder and deadline the protocol assumes.
        from operations.service import collection_settings
        unit = (root / 'deploy' / config['unit']).read_text()
        expected = f"--directory {config['campaign_path']} --until {config['until']} --profile {config['profile']}"
        if expected not in unit or f"WorkingDirectory={config['app_path']}" not in unit:
            raise ValueError('Service unit differs from the release plan')
        current = collection_settings(config['profile']).model_dump(mode='json', exclude=EXCLUDED_SETTINGS)
        if current != plan['scenario_definitions']['baseline']['settings']:
            raise ValueError('Collection settings differ from the frozen protocol')
    return config


if __name__ == '__main__':
    config = validate_release()
    print('Neues Testfenster und unverändertes Protokoll geprüft.')
