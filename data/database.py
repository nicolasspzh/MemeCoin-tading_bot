"""SQLite audit trail. Each observation, decision, fill and wallet commit together."""
import sqlite3
from pathlib import Path

from data.models import Snapshot, Wallet

HORIZONS = (30, 60, 120, 300, 900, 3600)


class Database:
    def __init__(self, path: Path, source: str):
        self.source = source
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, started_at REAL NOT NULL, settings TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tokens(
                token TEXT PRIMARY KEY, discovered_at REAL NOT NULL, source TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS snapshots(
                id INTEGER PRIMARY KEY, token TEXT NOT NULL REFERENCES tokens(token),
                pair TEXT NOT NULL, received_at REAL NOT NULL, price TEXT, payload TEXT NOT NULL,
                UNIQUE(token, pair, received_at));
            CREATE INDEX IF NOT EXISTS snapshots_history ON snapshots(token, pair, received_at);
            CREATE TABLE IF NOT EXISTS decisions(
                id INTEGER PRIMARY KEY, snapshot_id INTEGER NOT NULL UNIQUE REFERENCES snapshots(id),
                run_id INTEGER NOT NULL REFERENCES runs(id),
                signal_at REAL NOT NULL, action TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS fills(
                id INTEGER PRIMARY KEY, snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
                payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS wallet(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS outcomes(
                snapshot_id INTEGER NOT NULL REFERENCES snapshots(id), horizon_seconds INTEGER NOT NULL,
                target_at REAL NOT NULL, future_snapshot_id INTEGER REFERENCES snapshots(id),
                delay_seconds REAL, PRIMARY KEY(snapshot_id, horizon_seconds));
            CREATE INDEX IF NOT EXISTS outcomes_pending ON outcomes(target_at) WHERE future_snapshot_id IS NULL;
            CREATE TABLE IF NOT EXISTS chain_scan_state(source TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS chain_transactions(
                signature TEXT PRIMARY KEY, first_seen_at REAL NOT NULL, slot INTEGER NOT NULL,
                chain_time REAL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt REAL NOT NULL DEFAULT 0, last_error TEXT, payload TEXT);
            CREATE TABLE IF NOT EXISTS pool_events(
                pool TEXT PRIMARY KEY, signature TEXT NOT NULL, slot INTEGER NOT NULL,
                chain_time REAL, discovered_at REAL NOT NULL, token_0 TEXT NOT NULL,
                token_1 TEXT NOT NULL, creator TEXT NOT NULL, source TEXT NOT NULL,
                payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS collection_attempts(
                id INTEGER PRIMARY KEY, token TEXT NOT NULL, attempted_at REAL NOT NULL,
                status TEXT NOT NULL, pair TEXT);
            CREATE INDEX IF NOT EXISTS collection_attempts_token ON collection_attempts(token, attempted_at);
            CREATE TABLE IF NOT EXISTS collector_health(
                id INTEGER PRIMARY KEY, source TEXT NOT NULL, observed_at REAL NOT NULL,
                kind TEXT NOT NULL, details TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS risk_evidence(
                sha256 TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS observation_tracks(
                token TEXT PRIMARY KEY REFERENCES tokens(token), pair TEXT,
                admitted_at REAL NOT NULL, primary_until REAL NOT NULL,
                follow_until REAL NOT NULL, last_primary_at REAL, completed_at REAL);
            CREATE TABLE IF NOT EXISTS admission_screens(
                id INTEGER PRIMARY KEY, token TEXT NOT NULL REFERENCES tokens(token),
                screened_at REAL NOT NULL, eligible INTEGER NOT NULL CHECK(eligible IN (0,1)),
                pair TEXT, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS admission_screens_token ON admission_screens(token, screened_at);
            CREATE TABLE IF NOT EXISTS rpc_request_budget(
                utc_day TEXT PRIMARY KEY, requests INTEGER NOT NULL CHECK(requests>=0));
            CREATE TABLE IF NOT EXISTS paper_orders(
                id INTEGER PRIMARY KEY, token TEXT NOT NULL, pair TEXT NOT NULL,
                status TEXT NOT NULL, signal_snapshot_id INTEGER NOT NULL UNIQUE REFERENCES snapshots(id),
                payload TEXT NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS paper_one_pending_per_token
                ON paper_orders(token) WHERE status='pending';
            CREATE TABLE IF NOT EXISTS paper_ledger(
                id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL UNIQUE REFERENCES paper_orders(id),
                snapshot_id INTEGER REFERENCES snapshots(id), payload TEXT NOT NULL);
        """)
        existing = self.conn.execute("SELECT value FROM metadata WHERE key='source'").fetchone()
        if existing and existing[0] != source:
            self.conn.close()
            raise ValueError("Demo and live market data must use separate databases")
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO metadata VALUES ('source', ?)", (source,))
            self.conn.execute("INSERT OR IGNORE INTO metadata VALUES ('schema_version', '1')")

    def close(self):
        self.conn.close()

    def discover(self, token: str, timestamp: float, source: str):
        self.conn.execute("INSERT OR IGNORE INTO tokens VALUES (?, ?, ?)", (token, timestamp, source))

    def latest(self, token: str, pair: str) -> Snapshot | None:
        row = self.conn.execute(
            "SELECT payload FROM snapshots WHERE token=? AND pair=? ORDER BY received_at DESC LIMIT 1",
            (token, pair)).fetchone()
        return Snapshot.model_validate_json(row[0]) if row else None

    def load_wallet(self) -> Wallet:
        row = self.conn.execute("SELECT payload FROM wallet WHERE id=1").fetchone()
        return Wallet.model_validate_json(row[0]) if row else Wallet()

    def save_wallet(self, wallet: Wallet):
        self.conn.execute("INSERT OR REPLACE INTO wallet VALUES (1, ?)", (wallet.model_dump_json(),))

    def add_snapshot(self, snapshot: Snapshot) -> int:
        if snapshot.source != self.source:
            raise ValueError("Observation source does not match database source")
        timestamp = snapshot.received_at.timestamp()
        self.discover(snapshot.token, timestamp, snapshot.source)
        cursor = self.conn.execute(
            "INSERT INTO snapshots(token,pair,received_at,price,payload) VALUES(?,?,?,?,?)",
            (snapshot.token, snapshot.pair, timestamp,
             str(snapshot.price_usd) if snapshot.price_usd is not None else None,
             snapshot.model_dump_json()))
        sid = cursor.lastrowid
        if snapshot.price_usd is not None:
            # Only the first later observation within max(30s, 10% of horizon).
            # Missing windows remain NULL; do not fabricate interpolated prices.
            self.conn.execute("""
                UPDATE outcomes SET future_snapshot_id=?, delay_seconds=?-target_at
                WHERE future_snapshot_id IS NULL AND target_at<=?
                  AND ?-target_at<=max(30, horizon_seconds*0.1)
                  AND snapshot_id IN (SELECT id FROM snapshots WHERE token=? AND pair=? AND id<>?)
            """, (sid, timestamp, timestamp, timestamp, snapshot.token, snapshot.pair, sid))
            if snapshot.observation_phase != "followup":
                self.conn.executemany("INSERT INTO outcomes VALUES (?, ?, ?, NULL, NULL)",
                                      [(sid, horizon, timestamp + horizon) for horizon in HORIZONS])
            if snapshot.observation_phase == "primary":
                # Extend from the LAST primary quote, not first discovery. Tail
                # quotes resolve existing labels but never create an endless tail.
                self.conn.execute("""UPDATE observation_tracks
                    SET last_primary_at=?, follow_until=max(primary_until, ?)
                    WHERE token=? AND completed_at IS NULL""",
                    (timestamp, timestamp + max(HORIZONS) * 1.1, snapshot.token))
        return sid

    def watchlist(self, now: float, limit: int) -> list[str]:
        # Open positions are added separately and never evicted. Keep discovered
        # tokens for at least an hour, plus room for delayed horizon observations.
        return [r[0] for r in self.conn.execute(
            """SELECT t.token FROM tokens t
               WHERE t.discovered_at>=?
               ORDER BY coalesce(
                 (SELECT max(a.attempted_at) FROM collection_attempts a WHERE a.token=t.token),
                 (SELECT max(s.received_at) FROM snapshots s WHERE s.token=t.token)) ASC,
                 t.discovered_at ASC, t.token ASC LIMIT ?""",
            (now - 3960, limit))]

    def preferred_pair(self, token: str) -> str | None:
        row = self.conn.execute(
            "SELECT pair FROM snapshots WHERE token=? ORDER BY received_at DESC LIMIT 1", (token,)).fetchone()
        if row:
            return row[0]
        pool = self.conn.execute("""SELECT pool FROM pool_events WHERE token_0=? OR token_1=?
                                    ORDER BY discovered_at, pool LIMIT 1""", (token, token)).fetchone()
        return pool[0] if pool else None

    def record_attempt(self, token: str, now: float, status: str, pair: str | None = None):
        self.conn.execute("INSERT INTO collection_attempts(token,attempted_at,status,pair) VALUES(?,?,?,?)",
                          (token, now, status, pair))

    def last_quote_at(self, token: str, pair: str) -> float | None:
        return self.conn.execute("""SELECT max(received_at) FROM snapshots
            WHERE token=? AND pair=? AND price IS NOT NULL""", (token, pair)).fetchone()[0]

    def collection_status(self) -> dict:
        return {
            "pool_events": self.conn.execute("SELECT count(*) FROM pool_events").fetchone()[0],
            "pending_transactions": self.conn.execute("SELECT count(*) FROM chain_transactions WHERE status='pending'").fetchone()[0],
            "observed_tokens": self.conn.execute("SELECT count(distinct token) FROM snapshots").fetchone()[0],
            "quote_attempts": self.conn.execute("SELECT count(*) FROM collection_attempts").fetchone()[0],
            "missing_quotes": self.conn.execute("SELECT count(*) FROM collection_attempts WHERE status='quote_missing'").fetchone()[0],
            "recorded_quote_gaps": self.conn.execute("SELECT count(*) FROM collector_health WHERE kind='quote_gap'").fetchone()[0],
        }

    def record_health(self, source: str, now: float, kind: str, details: str):
        self.conn.execute("INSERT INTO collector_health(source,observed_at,kind,details) VALUES(?,?,?,?)",
                          (source, now, kind, details))

    def recent_token_count(self, now: float) -> int:
        return self.conn.execute("SELECT count(*) FROM tokens WHERE discovered_at>=?", (now - 3960,)).fetchone()[0]

    def counts(self) -> dict[str, int]:
        return {table: self.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in ("tokens", "snapshots", "decisions", "fills")}

    def pending_orders(self) -> list[dict]:
        import json
        return [json.loads(row[0]) for row in self.conn.execute(
            "SELECT payload FROM paper_orders WHERE status='pending' ORDER BY id")]

    def save_order(self, order: dict):
        import json
        self.conn.execute("UPDATE paper_orders SET status=?,payload=? WHERE id=?",
                          (order["status"], json.dumps(order, sort_keys=True), order["id"]))
