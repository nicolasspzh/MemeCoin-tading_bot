"""Read-only data-flow check; no provider secret or strategy performance output."""
import json
from pathlib import Path
import sys

from operations.campaign import status


def ready(result):
    data = result.get('data', {})
    age = data.get('last_quote_age_seconds')
    return bool(result.get('supervisor_running') and data.get('cycles', 0) >= 1
                and data.get('priced_snapshots', 0) > 0 and age is not None and 0 <= age < 120
                and data.get('orders') == data.get('fills') == 0)


if __name__ == '__main__':
    try:
        result = status(Path(sys.argv[1]).resolve())
        if not ready(result):
            raise SystemExit(1)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, KeyError):
        raise SystemExit(1)
