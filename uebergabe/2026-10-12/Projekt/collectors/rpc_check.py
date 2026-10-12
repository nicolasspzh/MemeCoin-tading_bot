"""Read-only RPC acceptance probe; never opens the trading database."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

import aiohttp
from pydantic import ValidationError

from collectors.http import DataUnavailable, JsonClient
from collectors.mint import address_bytes
from collectors.solana import Solana
from config.settings import load_settings
from data.models import utcnow

# Previously observed metadata-only Token-2022 mint; a probe, not a recommendation.
DEFAULT_TOKEN = "3RSAGUGNvL4x27ukwRybPE7WUQMiUCWtgYJezLUgpump"


async def check_rpc(http, settings, tokens, *, rounds=3, interval=10, progress=None):
    if not 1 <= rounds <= 20 or not 0 <= interval <= 60 or not tokens:
        raise ValueError("Invalid probe bounds")
    tokens = list(dict.fromkeys(tokens))
    for token in tokens:
        address_bytes(token)
    # Fresh network evidence in each round; retain normal rate-limit cooldowns.
    rpc = Solana(http, settings.solana_rpc_url, settings.solana_rpc_fallback_urls, cache_seconds=0)
    started, checks, previous_slots = utcnow(), [], {}
    for number in range(1, rounds + 1):
        for token in tokens:
            row = {"round": number, "token": token, "checked_at": utcnow().isoformat()}
            try:
                risk = await rpc.mint_risk(token)
                row.update(mint_slot=risk.mint_slot, concentration_slot=risk.concentration_slot,
                           mint_host=risk.mint_rpc_host, concentration_host=risk.concentration_rpc_host,
                           top10_account_fraction=(str(risk.top10_account_fraction)
                                                   if risk.top10_account_fraction is not None else None))
                if risk.data_errors:
                    row.update(state="incomplete_data", reasons=risk.data_errors)
                elif risk.top10_account_fraction is None:
                    row.update(state="probe_token_rejected", reasons=[
                        "Mint risk gate prevented the holder request; choose another probe token"])
                else:
                    slots = (risk.mint_slot, risk.concentration_slot)
                    previous = previous_slots.get(token)
                    if previous and any(current < old for current, old in zip(slots, previous)):
                        row.update(state="regressing_slots", reasons=["RPC context slots moved backwards"])
                    elif previous and interval >= 5 and any(current == old for current, old in zip(slots, previous)):
                        row.update(state="stalled_slots", reasons=["No new context slot after the probe interval"])
                    else:
                        row.update(state="complete", reasons=[])
                    previous_slots[token] = slots
            except (DataUnavailable, ValidationError, TypeError, KeyError, AttributeError) as exc:
                row.update(state="unavailable", reasons=[str(exc) if isinstance(exc, DataUnavailable)
                                                         else "Malformed RPC data"])
            row["endpoints"] = rpc.endpoint_status()
            checks.append(row)
            if progress:
                progress(number, token, row["state"])
        if number < rounds:
            await asyncio.sleep(interval)
    return {"schema_version": 1, "started_at": started.isoformat(), "finished_at": utcnow().isoformat(),
            "ready_for_sample": all(row["state"] == "complete" for row in checks),
            "rounds": rounds, "interval_seconds": interval, "checks": checks,
            "rpc_totals": dict(rpc.stats), "endpoints": rpc.endpoint_status(),
            "scope": "Read-only point-in-time mint and largest-token-account checks; no trading",
            "limits": ["A successful sample does not establish sustained availability or profitability",
                       "Token-account concentration includes pool vaults and is not unique-holder concentration",
                       "A complete response is not an entry approval; all trading risk gates still apply",
                       "An unused fallback is reported as not_exercised, not verified"]}


async def run(settings, args):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20), trust_env=True) as session:
        return await check_rpc(JsonClient(session), settings, args.token or [DEFAULT_TOKEN],
                               rounds=args.rounds, interval=args.interval,
                               progress=lambda n, token, state: print(
                                   f"RPC check round={n} token={token} state={state}", file=sys.stderr, flush=True))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only Solana RPC acceptance check; no orders or wallet changes")
    parser.add_argument("--token", action="append", help="Probe mint; repeat for multiple mints")
    parser.add_argument("--rounds", type=int, default=3, help="Fresh checks per token (1..20)")
    parser.add_argument("--interval", type=float, default=10, help="Seconds between rounds (0..60)")
    parser.add_argument("--out", type=Path, help="New JSON report file; existing reports are preserved")
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.rounds <= 20 or not 0 <= args.interval <= 60:
            raise ValueError("Invalid probe bounds")
        for token in args.token or [DEFAULT_TOKEN]:
            address_bytes(token)
        if args.out and args.out.exists():
            raise FileExistsError
        settings = load_settings()
        report = asyncio.run(run(settings, args))
        output = json.dumps(report, indent=2, allow_nan=False)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            with args.out.open("x") as target:
                target.write(output + "\n")
        print(output)
        return 0 if report["ready_for_sample"] else 2
    except KeyboardInterrupt:
        print("RPC check stopped", file=sys.stderr)
        return 130
    except (ValueError, OSError, DataUnavailable):
        # Validation messages and OS errors may contain credential-bearing input.
        print("RPC check could not start/save: check settings, arguments and a new output path", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
