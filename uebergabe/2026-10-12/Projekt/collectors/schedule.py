"""Finite cohorts: dense primary observations, then outcome-only follow-up.

Admission is by discovery time/address, never by later prices or risk results.
All admitted coins retain their slot through the committed observation window,
including missing/disappeared pools. Coverage is a bounded, biased sample.
"""
from datetime import UTC, datetime

from collectors.http import DataUnavailable
from data.database import HORIZONS

FOLLOWUP_SECONDS = int(max(HORIZONS) * 1.1)


class ObservationSchedule:
    def __init__(self, db, settings, feature_until=None):
        self.db, self.settings, self.feature_until = db, settings, feature_until
        if settings.watch_tokens:
            raise ValueError("Cohort collection cannot combine a fixed watchlist")

    def select(self, now):
        with self.db.conn:
            # A missed deadline after downtime remains a gap, never a backfill.
            self.db.conn.execute("""UPDATE observation_tracks SET completed_at=?
                WHERE completed_at IS NULL AND follow_until<?""", (now, now))
            active = self.db.conn.execute("SELECT count(*) FROM observation_tracks WHERE completed_at IS NULL").fetchone()[0]
            capacity = max(0, self.settings.max_watch_tokens - active)
            interval = self.settings.observation_admission_seconds
            if interval:
                last = self.db.conn.execute('SELECT max(admitted_at) FROM observation_tracks').fetchone()[0]
                capacity = min(capacity, 1) if last is None or now - last >= interval else 0
            if capacity and (self.feature_until is None or now < self.feature_until):
                rows = self.db.conn.execute("""SELECT token FROM tokens
                    WHERE discovered_at>=? AND discovered_at<=?
                    AND token NOT IN (SELECT token FROM observation_tracks)
                    ORDER BY discovered_at,token LIMIT ?""", (now - 3960, now, capacity)).fetchall()
                end = min(now + self.settings.observation_primary_seconds,
                          self.feature_until if self.feature_until is not None else float('inf'))
                for row in rows:
                    self.db.conn.execute("INSERT INTO observation_tracks VALUES(?,?,?,?,?,NULL,NULL)",
                        (row[0], self.db.preferred_pair(row[0]), now, end, end))
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
