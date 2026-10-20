"""Freeze the R3 test protocol: future 7-day window, current code, R3 collection settings.

All development data known when R3 was designed is bound by SHA-256, row count and
time range. Run once, before installation; a changed core file needs a new protocol.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtesting.evaluation import prepare_references  # noqa: E402
from operations.service import collection_settings  # noqa: E402

REFERENCES = [
    {"name": "r2-final", "sha256": "c270356bf1cdb20b1bd6912be8f639f345b22e489b08a97aa1f0d0ebe7b3d763",
     "rows": 244693, "first_utc": "2026-10-08T14:58:45.017232+00:00", "last_utc": "2026-10-16T01:05:39.351042+00:00",
     "location": "Finale R2-Datenbank (Datei-Hash), Kopien auf PC, NAS und in Google Drive"},
    {"name": "probe-d1", "sha256": "f5ef2dfe9b79b6dfd5ff6add9a0ab467e6694be2b90209af7e1fba4ffd6e3be4",
     "rows": 5713, "first_utc": "2026-10-17T08:07:12.415699+00:00", "last_utc": "2026-10-17T16:07:11+00:00",
     "location": "Bericht uebergabe/2026-10-17/probe-d1-bericht.json; Daten auf dem VPS unter probe-d1"},
    {"name": "supply-sampler", "sha256": "c13010bb78eac97d46c18ab991028188e73146b0abc6ef5d24617139bf39e951",
     "rows": 2140, "first_utc": "2026-10-17T16:12:28.007996+00:00", "last_utc": "2026-10-17T19:11:34.240870+00:00",
     "location": "uebergabe/2026-10-17/supply-sampler-log.jsonl"},
    {"name": "probe-d2", "sha256": "686d10a057142cf1c159a1e65302aefc8ce4a4986e553866b0ad3888d2147897",
     "rows": 7582, "first_utc": "2026-10-18T07:40:46.485733+00:00", "last_utc": "2026-10-18T15:05:15.908302+00:00",
     "location": "Bericht uebergabe/2026-10-19/probe-d2-bericht.json; Daten auf dem VPS unter probe-d2"},
    {"name": "cloud-dry-runs", "sha256": "a7d470e4f73a6c9163ea2f163a4e24d61f69110e48672fc5b189bc0b05c14249",
     "rows": 73, "first_utc": "2026-10-16T21:38:57.381600+00:00", "last_utc": "2026-10-19T18:09:19.527189+00:00",
     "location": "uebergabe/2026-10-20/cloud-dry-runs.json"},
    {"name": "probe-d3", "sha256": "a58dd9afaa73a8527968915faef5c1948d4346fc6fcbdc13dc06679ea93a05bd",
     "rows": 28570, "first_utc": "2026-10-19T18:13:55.695190+00:00", "last_utc": "2026-10-20T18:13:54.162069+00:00",
     "location": "Bericht uebergabe/2026-10-19/probe-d3-bericht.json; Daten auf dem VPS unter probe-d3"},
]

if __name__ == "__main__":
    release = json.loads((ROOT / "deploy/release.json").read_text())
    out = (ROOT / release["protocol"]).parent
    envelope = prepare_references(REFERENCES, out, collection_settings(release["profile"]),
                                  start=release["test_start_utc"], days=7)
    print(json.dumps({"protocol_sha256": envelope["sha256"], "code_sha256": envelope["plan"]["code_sha256"],
                      "test_start_utc": envelope["plan"]["test_start_utc"],
                      "test_end_exclusive_utc": envelope["plan"]["test_end_exclusive_utc"]}, indent=1))
