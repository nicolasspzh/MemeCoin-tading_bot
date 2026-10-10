"""Finalized Raydium CPMM initialize transactions via its creation-fee account.

Source: raydium-io/raydium-cp-swap, programs/cp-swap/src/{lib.rs,
instructions/initialize.rs}. Only the standard initialize instruction is covered.
No claim of all Solana pools, permissioned initialization or lossless RPC history.
"""
import asyncio
import json
import logging
import struct
from contextlib import suppress

from collectors.http import DataUnavailable
from collectors.mint import address_bytes
from data.models import utcnow

PROGRAM = "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"
FEE_ACCOUNT = "DNXgeM9EiiaAbaWvwjHj9fQQLAX5ZsfHyvmYUNRAdNC8"
INITIALIZE = bytes([175, 175, 109, 31, 13, 152, 155, 237])
SOURCE = "raydium-cpmm-finalized"
QUOTE_MINTS = {"So11111111111111111111111111111111111111112",
               "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"}
log = logging.getLogger("memecoin")


def decode58(value):
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    if not isinstance(value, str) or len(value) > 4096:
        raise DataUnavailable("Invalid instruction encoding")
    try:
        number = 0
        for char in value:
            number = number * 58 + alphabet.index(char)
        return b"\0" * (len(value) - len(value.lstrip("1"))) + number.to_bytes((number.bit_length()+7)//8, "big")
    except ValueError:
        raise DataUnavailable("Invalid instruction encoding") from None


def parse_pools(transaction, signature):
    """Verify successful program instructions, including CPI and v0 loaded keys."""
    try:
        meta, tx = transaction["meta"], transaction["transaction"]
        if "err" not in meta or not tx["signatures"] or tx["signatures"][0] != signature:
            raise ValueError
        if meta["err"] is not None:
            return []
        slot = transaction["slot"]
        if type(slot) is not int or slot < 0:
            raise ValueError
        chain_time = transaction.get("blockTime")
        if chain_time is not None and (type(chain_time) is not int or chain_time < 0):
            raise ValueError
        message = tx["message"]
        loaded = meta.get("loadedAddresses") or {}
        keys = message["accountKeys"] + loaded.get("writable", []) + loaded.get("readonly", [])
        instructions = list(message["instructions"])
        for group in meta.get("innerInstructions") or []:
            instructions.extend(group["instructions"])
        pools = {}
        for ix in instructions:
            index = ix["programIdIndex"]
            if type(index) is not int or not 0 <= index < len(keys):
                raise ValueError
            if keys[index] != PROGRAM:
                continue
            raw = decode58(ix["data"])
            if raw[:8] != INITIALIZE:
                continue
            if len(raw) != 32 or len(ix["accounts"]) < 20:
                raise ValueError
            if any(type(i) is not int or not 0 <= i < len(keys) for i in ix["accounts"]):
                raise ValueError
            accounts = [keys[i] for i in ix["accounts"]]
            if accounts[12] != FEE_ACCOUNT:
                raise ValueError
            for key in accounts:
                address_bytes(key)
            if accounts[4] == accounts[5]:
                raise ValueError
            amount_0, amount_1, open_time = struct.unpack_from("<QQQ", raw, 8)
            if not amount_0 or not amount_1:
                raise ValueError
            pools[accounts[3]] = {"pool": accounts[3], "signature": signature, "slot": slot,
                "chain_time": chain_time, "token_0": accounts[4], "token_1": accounts[5],
                "creator": accounts[0], "source": SOURCE,
                "instruction": {"program": PROGRAM, "accounts": accounts, "data": ix["data"],
                                "initial_amount_0": str(amount_0), "initial_amount_1": str(amount_1),
                                "open_time": open_time}}
        return list(pools.values())
    except (KeyError, TypeError, IndexError, ValueError, AttributeError, struct.error):
        raise DataUnavailable("Malformed pool transaction") from None


class PoolDiscovery:
    def __init__(self, db, rpc, settings):
        self.db, self.rpc, self.settings = db, rpc, settings
        self.task = None
        self.errors = 0
        self.last_error = None

    async def __aenter__(self):
        previous = self.db.conn.execute("SELECT max(observed_at) FROM collector_health WHERE source=?", (SOURCE,)).fetchone()[0]
        with self.db.conn:
            self.db.record_health(SOURCE, utcnow().timestamp(), "started",
                json.dumps({"previous_activity_at": previous,
                            "coverage": "Persisted cursor will be used for bounded catch-up; RPC history may be incomplete"}))
        await self.poll()
        self.task = asyncio.create_task(self.run())
        return self

    async def __aexit__(self, *args):
        self.task.cancel()
        with suppress(asyncio.CancelledError):
            await self.task
        with self.db.conn:
            self.db.record_health(SOURCE, utcnow().timestamp(), "stopped", "Cursor and pending transactions retained")

    async def run(self):
        while True:
            await asyncio.sleep(self.settings.discovery_poll_seconds)
            await self.poll()

    def status(self):
        pending = self.db.conn.execute("SELECT count(*) FROM chain_transactions WHERE status='pending'").fetchone()[0]
        state = self.db.conn.execute("SELECT payload FROM chain_scan_state WHERE source=?", (SOURCE,)).fetchone()
        return {"source": SOURCE, "pool_events": self.db.conn.execute("SELECT count(*) FROM pool_events").fetchone()[0],
                "pending_transactions": pending, "catchup_pending": bool(state and json.loads(state[0]).get("before")),
                "errors": self.errors, "last_error": self.last_error}

    async def poll(self):
        errors = []
        for action in (self.scan, self.resolve):
            try:
                await action()
            except (DataUnavailable, TypeError, ValueError, KeyError, AttributeError) as exc:
                self.errors += 1
                reason = str(exc) if isinstance(exc, DataUnavailable) else "Invalid discovery data"
                errors.append(reason)
                with self.db.conn:
                    self.db.record_health(SOURCE, utcnow().timestamp(), action.__name__ + "_error", reason)
                log.warning("Pool discovery incomplete: %s", reason)
        self.last_error = "; ".join(errors) if errors else None

    async def scan(self):
        row = self.db.conn.execute("SELECT payload FROM chain_scan_state WHERE source=?", (SOURCE,)).fetchone()
        state = json.loads(row[0]) if row else {"cursor": None, "before": None, "head": None}
        size = self.settings.discovery_page_size
        for _ in range(self.settings.discovery_pages_per_poll):
            options = {"limit": size, "commitment": "finalized"}
            if state["cursor"]:
                options["until"] = state["cursor"]
            if state["before"]:
                options["before"] = state["before"]
            rows = await self.rpc.rpc("getSignaturesForAddress", [FEE_ACCOUNT, options])
            if not isinstance(rows, list) or len(rows) > size:
                raise DataUnavailable("Invalid signature page")
            for item in rows:
                if (not isinstance(item, dict) or len(decode58(item.get("signature"))) != 64
                        or type(item.get("slot")) is not int or item["slot"] < 0 or "err" not in item
                        or (item.get("blockTime") is not None and type(item["blockTime"]) is not int)):
                    raise DataUnavailable("Invalid signature record")
            if rows and rows[-1]["signature"] == state["before"]:
                raise DataUnavailable("Signature pagination did not advance")
            now = utcnow().timestamp()
            bootstrap = not state["cursor"]
            if rows and not state["head"]:
                state["head"] = rows[0]["signature"]
            complete = bootstrap or len(rows) < size
            with self.db.conn:
                for item in rows:
                    self.db.conn.execute("""INSERT OR IGNORE INTO chain_transactions
                        (signature,first_seen_at,slot,chain_time,status) VALUES(?,?,?,?,?)""",
                        (item["signature"], now, item["slot"], item.get("blockTime"),
                         "pending" if item["err"] is None else "failed_transaction"))
                if bootstrap:
                    self.db.record_health(SOURCE, now, "bootstrap_boundary",
                        "Only the first recent signature page is included; older history is outside coverage")
                if complete:
                    state = {"cursor": state["head"] or state["cursor"], "before": None, "head": None}
                else:
                    state["before"] = rows[-1]["signature"]
                self.db.conn.execute("INSERT OR REPLACE INTO chain_scan_state VALUES(?,?)", (SOURCE, json.dumps(state)))
                self.db.record_health(SOURCE, now, "signature_page",
                    json.dumps({"count": len(rows), "catchup_pending": not complete}))
            if complete:
                break

    async def resolve(self):
        now = utcnow().timestamp()
        rows = self.db.conn.execute("""SELECT signature,slot,first_seen_at,attempts FROM chain_transactions
            WHERE status='pending' AND next_attempt<=? ORDER BY first_seen_at, slot DESC LIMIT ?""",
            (now, self.settings.discovery_transactions_per_poll)).fetchall()
        failed = False
        for signature, slot, seen, attempts in rows:
            try:
                tx = await self.rpc.rpc("getTransaction", [signature,
                    {"encoding": "json", "commitment": "finalized", "maxSupportedTransactionVersion": 0}])
                if tx is None:
                    raise DataUnavailable("Transaction not available yet")
                pools = parse_pools(tx, signature)
                if tx["slot"] != slot:
                    raise DataUnavailable("Transaction slot does not match signature record")
                with self.db.conn:
                    for pool in pools:
                        # Discovery time is local receipt, never backdated to chain time.
                        received = utcnow().timestamp()
                        self.db.conn.execute("""INSERT OR IGNORE INTO pool_events
                            VALUES(?,?,?,?,?,?,?,?,?,?)""", (pool["pool"], signature, slot, pool["chain_time"],
                            received, pool["token_0"], pool["token_1"], pool["creator"], SOURCE, json.dumps(pool)))
                        if pool["chain_time"] is None or received - pool["chain_time"] <= self.settings.max_age_seconds:
                            for token in (pool["token_0"], pool["token_1"]):
                                if token not in QUOTE_MINTS:
                                    self.db.discover(token, received, SOURCE)
                    self.db.conn.execute("""UPDATE chain_transactions SET status=?,attempts=attempts+1,
                        last_error=NULL,payload=? WHERE signature=?""",
                        ("verified_pool" if pools else "not_standard_pool_init", json.dumps(tx), signature))
            except (DataUnavailable, TypeError, KeyError, ValueError) as exc:
                failed = True
                reason = str(exc) if isinstance(exc, DataUnavailable) else "Invalid transaction data"
                with self.db.conn:
                    self.db.conn.execute("""UPDATE chain_transactions SET attempts=attempts+1,
                        next_attempt=?,last_error=? WHERE signature=?""",
                        (utcnow().timestamp() + min(300, 20 * 2**min(attempts, 4)), reason, signature))
        if failed:
            raise DataUnavailable("Some discovery transactions remain pending; retries retained")
