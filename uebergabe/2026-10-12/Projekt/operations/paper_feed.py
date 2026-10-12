"""Independent Paper market feed. No changes to the frozen R2 collector."""
import time

import aiohttp

from collectors.dexscreener import DexScreener
from collectors.http import DataUnavailable, JsonClient
from collectors.pools import PoolDiscovery
from collectors.schedule import RpcBudget
from collectors.solana import Solana
from data.models import Snapshot, utcnow


def select_pairs(db, settings):
    positions = db.load_wallet().positions
    pending = {order['token']: order['pair'] for order in db.pending_orders()}
    pinned = {**pending, **{token: position.pair for token, position in positions.items()}}
    candidates = list(dict.fromkeys([*settings.watch_tokens, *db.watchlist(utcnow().timestamp(), 100)]))
    candidates = [token for token in candidates if token not in pinned]
    row = db.conn.execute("SELECT value FROM metadata WHERE key='paper_candidate_cursor'").fetchone()
    offset = int(row[0]) % len(candidates) if row and candidates else 0
    slots = max(0, settings.max_watch_tokens - len(pinned))
    selected = (candidates[offset:] + candidates[:offset])[:slots]
    with db.conn:
        db.conn.execute("INSERT OR REPLACE INTO metadata VALUES('paper_candidate_cursor',?)", (str(offset + len(selected)),))
    return {**pinned, **{token: db.preferred_pair(token) for token in selected}}


class MarketFeed:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings
        self.last_discovery = float('-inf')

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20), trust_env=True)
        http = JsonClient(self.session)
        self.dex = DexScreener(http, self.settings.dex_base_url)
        self.budget = RpcBudget(self.db, self.settings.rpc_daily_request_limit, self.settings.rpc_total_request_limit)
        self.solana = Solana(http, self.settings.solana_rpc_url, self.settings.solana_rpc_fallback_urls,
                             cache_seconds=self.settings.rpc_cache_seconds, budget=self.budget, cache_partial=True)
        self.discovery = PoolDiscovery(self.db, self.solana, self.settings)
        return self

    async def __aexit__(self, *args):
        await self.session.close()

    async def cycle(self):
        errors = 0
        if time.monotonic() - self.last_discovery >= self.settings.discovery_poll_seconds:
            self.last_discovery = time.monotonic()
            try:
                tokens = await self.dex.discover()
                with self.db.conn:
                    for token in tokens:
                        self.db.discover(token, utcnow().timestamp(), 'paper-profile-discovery')
            except (DataUnavailable, ValueError, TypeError, KeyError):
                errors += 1
            if self.settings.pool_discovery_enabled:
                await self.discovery.poll()  # same persistent request budget, no background task
        pairs = select_pairs(self.db, self.settings)
        try:
            quotes = await self.dex.snapshots(list(pairs), pairs) if pairs else {}
        except (DataUnavailable, ValueError, TypeError, KeyError):
            quotes, errors = {}, errors + 1
        observations = []
        for token, pair in pairs.items():
            quote = quotes.get(token)
            if pair and (quote is None or quote.price_usd is None):
                try:
                    quote = await self.dex.snapshot(token, pair)
                except (DataUnavailable, ValueError, TypeError, KeyError):
                    quote = None
            if quote is not None and (quote.token != token or (pair and quote.pair != pair)):
                quote = None
            if quote is None:
                errors += 1
                if pair:
                    quote = Snapshot(token=token, pair=pair, source='dexscreener', received_at=utcnow(),
                                     raw={'missing_pair': True})
            with self.db.conn:
                self.db.record_attempt(token, utcnow().timestamp(),
                                       'quote_received' if quote and quote.price_usd is not None else 'quote_missing', pair)
            if quote is None:
                continue
            if quote.price_usd is not None:
                try:
                    quote.mint_risk = await self.solana.mint_risk(token, quote.pair)
                except (DataUnavailable, ValueError, TypeError, KeyError):
                    quote.mint_risk = None
                    errors += 1
            observations.append(quote)
        return observations, {'feed_errors': errors, 'rpc_budget': self.budget.status(),
                              'discovery_errors': self.discovery.errors}
