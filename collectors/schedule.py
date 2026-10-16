"""Finite cohorts: dense primary observations, then outcome-only follow-up.

Admission is by discovery time/address, never by later prices or risk results.
All admitted coins retain their slot through the committed observation window,
including missing/disappeared pools. Coverage is a bounded, biased sample.
"""
import json
from datetime import UTC, datetime

from collectors.http import DataUnavailable
from data.database import HORIZONS

FOLLOWUP_SECONDS = int(max(HORIZONS) * 1.1)


WSOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SCREEN_BATCH = 30          # DEX Screener batch size; one request per screening round
SCREEN_FRESH_SECONDS = 120  # a screen older than this cannot admit a coin
RESCREEN_SECONDS = 300      # rejected candidates may be checked again later


def admission_reasons(snapshot, settings):
    """Admission prefilter on facts known at admission time (DEX quote only).

    Pool type and quote asset match what the entry checks can verify; liquidity
    is only a coarse preselection, entries verify it on-chain.
    """
    if snapshot is None:
        return ["no_dex_pair"]
    raw, reasons = snapshot.raw, []
    dex_id, labels = raw.get("dexId"), raw.get("labels") or []
    if not ((dex_id == "raydium" and "CPMM" in labels) or dex_id == "pumpswap"):
        reasons.append("unsupported_dex_pool")
    if (raw.get("quoteToken") or {}).get("address") not in (WSOL_MINT, USDC_MINT):
        reasons.append("unsupported_quote_mint")
    if snapshot.price_usd is None:
        reasons.append("missing_price")
    if snapshot.liquidity_usd is None or snapshot.liquidity_usd < settings.min_liquidity_usd:
        reasons.append("insufficient_or_unknown_liquidity")
    return reasons


class ObservationSchedule:
    def __init__(self, db, settings, feature_until=None):
        self.db, self.settings, self.feature_until = db, settings, feature_until
        if settings.watch_tokens:
            raise ValueError("Cohort collection cannot combine a fixed watchlist")

    def _capacity(self, now):
        # A missed deadline after downtime remains a gap, never a backfill.
        self.db.conn.execute("""UPDATE observation_tracks SET completed_at=?
            WHERE completed_at IS NULL AND follow_until<?""", (now, now))
        active = self.db.conn.execute("SELECT count(*) FROM observation_tracks WHERE completed_at IS NULL").fetchone()[0]
        capacity = max(0, self.settings.max_watch_tokens - active)
        interval = self.settings.observation_admission_seconds
        if interval:
            last = self.db.conn.execute('SELECT max(admitted_at) FROM observation_tracks').fetchone()[0]
            capacity = min(capacity, 1) if last is None or now - last >= interval else 0
        return capacity if self.feature_until is None or now < self.feature_until else 0

    def admission_due(self, now):
        with self.db.conn:
            return self._capacity(now) > 0

    def screen_candidates(self, now):
        """Oldest discovered, untracked candidates without a recent screen."""
        return [row[0] for row in self.db.conn.execute("""SELECT t.token FROM tokens t
            WHERE t.discovered_at>=? AND t.discovered_at<=?
            AND t.token NOT IN (SELECT token FROM observation_tracks)
            AND NOT EXISTS (SELECT 1 FROM admission_screens s WHERE s.token=t.token AND s.screened_at>?)
            ORDER BY t.discovered_at,t.token LIMIT ?""", (now - 3960, now, now - RESCREEN_SECONDS, SCREEN_BATCH))]

    def record_screens(self, now, quotes):
        with self.db.conn:
            for token, snapshot in quotes.items():
                reasons = admission_reasons(snapshot, self.settings)
                raw = snapshot.raw if snapshot is not None else {}
                self.db.conn.execute("""INSERT INTO admission_screens(token,screened_at,eligible,pair,payload)
                    VALUES(?,?,?,?,?)""", (token, now, int(not reasons), snapshot.pair if snapshot else None,
                    json.dumps({"reasons": reasons, "dex_id": raw.get("dexId"), "labels": raw.get("labels"),
                                "quote_mint": (raw.get("quoteToken") or {}).get("address"),
                                "liquidity_usd": str(snapshot.liquidity_usd) if snapshot else None}, sort_keys=True)))

    def select(self, now):
        with self.db.conn:
            capacity = self._capacity(now)
            if capacity:
                end = min(now + self.settings.observation_primary_seconds,
                          self.feature_until if self.feature_until is not None else float('inf'))
                if self.settings.admission_prefilter:
                    # Only a fresh eligible screen admits, with exactly the screened pool.
                    rows = self.db.conn.execute("""SELECT t.token,s.pair FROM tokens t
                        JOIN admission_screens s ON s.token=t.token
                        WHERE t.discovered_at>=? AND t.discovered_at<=?
                        AND t.token NOT IN (SELECT token FROM observation_tracks)
                        AND s.eligible=1 AND s.screened_at>=? AND s.screened_at<=?
                        AND s.id=(SELECT max(id) FROM admission_screens WHERE token=t.token)
                        ORDER BY t.discovered_at,t.token LIMIT ?""",
                        (now - 3960, now, now - SCREEN_FRESH_SECONDS, now, capacity)).fetchall()
                else:
                    rows = [(row[0], self.db.preferred_pair(row[0])) for row in self.db.conn.execute(
                        """SELECT token FROM tokens
                        WHERE discovered_at>=? AND discovered_at<=?
                        AND token NOT IN (SELECT token FROM observation_tracks)
                        ORDER BY discovered_at,token LIMIT ?""", (now - 3960, now, capacity))]
                for token, pair in rows:
                    self.db.conn.execute("INSERT INTO observation_tracks VALUES(?,?,?,?,?,NULL,NULL)",
                        (token, pair, now, end, end))
            return [row[0] for row in self.db.conn.execute("""SELECT token FROM observation_tracks
                WHERE completed_at IS NULL ORDER BY admitted_at,token""")]

    def preferred_pair(self, token):
        return self.db.conn.execute("SELECT pair FROM observation_tracks WHERE token=?", (token,)).fetchone()[0]

    def decorate(self, snapshot):
        row = self.db.conn.execute("SELECT * FROM observation_tracks WHERE token=?", (snapshot.token,)).fetchone()
        if row is None or row['completed_at'] is not None:
            raise ValueError("Observation outside admitted cohort")
        if row['pair'] is not None and row['pair'] != snapshot.pair:
            raise ValueError("Cohort pool cannot change")
        if row['pair'] is None:
            with self.db.conn:
                self.db.conn.execute("UPDATE observation_tracks SET pair=? WHERE token=?", (snapshot.pair, snapshot.token))
        snapshot.observation_phase = ('primary' if snapshot.received_at.timestamp() < row['primary_until'] else 'followup')
        return snapshot

    def status(self, now):
        counts = dict(self.db.conn.execute("""SELECT CASE WHEN completed_at IS NOT NULL THEN 'completed'
            WHEN primary_until>? THEN 'primary' ELSE 'followup' END,count(*)
            FROM observation_tracks GROUP BY 1""", (now,)))
        return {'mode': 'finite_cohorts', 'slots': self.settings.max_watch_tokens,
                'primary_seconds': self.settings.observation_primary_seconds, **counts,
                'admission_interval_seconds': self.settings.observation_admission_seconds,
                'admission_prefilter': self.settings.admission_prefilter,
                'screens_last_hour': dict(self.db.conn.execute(
                    "SELECT CASE eligible WHEN 1 THEN 'eligible' ELSE 'rejected' END,count(*) FROM admission_screens "
                    "WHERE screened_at>=? GROUP BY 1", (now - 3600,))),
                'feature_until': self.feature_until}


class RpcBudget:
    """Counts attempted RPC requests, NOT provider credits; persist before send."""
    def __init__(self, db, daily, total):
        self.db, self.daily, self.total = db, daily, total

    def reserve(self, now=None):
        day = (now or datetime.now(UTC)).astimezone(UTC).date().isoformat()
        with self.db.conn:
            self.db.conn.execute('BEGIN IMMEDIATE')
            total = self.db.conn.execute('SELECT coalesce(sum(requests),0) FROM rpc_request_budget').fetchone()[0]
            row = self.db.conn.execute('SELECT requests FROM rpc_request_budget WHERE utc_day=?', (day,)).fetchone()
            used = row[0] if row else 0
            if total >= self.total or used >= self.daily:
                raise DataUnavailable('RPC request budget exhausted; checks remain incomplete')
            self.db.conn.execute('''INSERT INTO rpc_request_budget VALUES(?,1)
                ON CONFLICT(utc_day) DO UPDATE SET requests=requests+1''', (day,))

    def status(self, now=None):
        day = (now or datetime.now(UTC)).astimezone(UTC).date().isoformat()
        counts = dict(self.db.conn.execute('SELECT utc_day,requests FROM rpc_request_budget'))
        return {'unit': 'attempted_requests_not_credits', 'utc_day': day, 'today': counts.get(day, 0),
                'total': sum(counts.values()), 'daily_limit': self.daily, 'total_limit': self.total}
