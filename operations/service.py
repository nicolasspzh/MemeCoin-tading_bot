"""Foreground entry point for a finite campaign managed by systemd."""
import argparse
import fcntl
import hashlib
import os
from pathlib import Path
import sys

from backtesting.evaluation import digest, utc
from config.settings import Settings, load_settings
from data.models import utcnow
from operations.campaign import atomic_json, initialize, load_manifest, read_json, supervise


def collection_settings():
    return Settings.model_validate(load_settings().model_copy(update={
        'max_watch_tokens': 8, 'discovery_poll_seconds': 120, 'discovery_transactions_per_poll': 4,
        'observation_cohorts': True, 'observation_primary_seconds': 1800,
        'observation_admission_seconds': 720,
        'rpc_daily_request_limit': 70000, 'rpc_total_request_limit': 600000,
        'rpc_cache_seconds': 60, 'watch_tokens': []}).model_dump())


def service_digest():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def run(directory, until):
    # The parent directory is provisioned by the installer/systemd. Acquire a
    # separate provisioning lock before creating the campaign directory.
    with (directory.parent / "service.lock").open("a") as provision:
        fcntl.flock(provision, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not directory.exists():
            if utcnow() >= utc(until):
                print("Collection window has ended; no new campaign created.", flush=True)
                return 0
            settings = collection_settings()
            manifest = initialize(directory, until, settings)
            # This is a new manifest, never a rewrite of an existing campaign.
            manifest.update(service_sha256=service_digest(),
                            hosting="systemd on VPS; restart on boot within the finite collection window")
            atomic_json(directory / "manifest.json", {"manifest": manifest, "sha256": digest(manifest)})
        manifest = load_manifest(directory)
        if manifest.get("service_sha256") != service_digest():
            raise ValueError("Service software changed or campaign not provisioned by this service")
        if utc(manifest["until"]) != utc(until):
            raise ValueError("Existing campaign deadline differs from service configuration")
        if (directory / "stop.request").exists() or utcnow() >= utc(manifest["until"]):
            print("Campaign manually stopped or deadline reached; no worker started.", flush=True)
            return 0
        with (directory / "supervisor.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            print("Starting observation-only collection; no trading orders.", flush=True)
            supervise(directory, os.dup(lock.fileno()))
        state = read_json(directory / "state.json", {})
        result = state.get("status", "unknown")
        print(f"Campaign finished: {result}", flush=True)
        return 0 if result in ("completed_scheduled_window", "stopped_by_request") else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--until", required=True)
    args = parser.parse_args()
    try:
        return run(args.directory.resolve(), args.until)
    except Exception as error:
        # Configuration errors may contain endpoint input; never log its value.
        print(f"Collection service failed: {type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
