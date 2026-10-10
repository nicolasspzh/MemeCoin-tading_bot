"""Bounded, paced, read-only API transport. Error messages omit endpoint secrets."""
import asyncio
import time

import aiohttp


class DataUnavailable(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, retry_after: float = 0):
        super().__init__(message)
        self.status, self.retry_after = status, retry_after


class JsonClient:
    def __init__(self, session: aiohttp.ClientSession, interval: float = 0.35):
        self.session = session
        self.interval = interval
        self._last_request = 0.0
        self._lock = asyncio.Lock()

    async def request(self, method: str, url: str, *, attempts: int = 3, **kwargs):
        for attempt in range(attempts):
            async with self._lock:
                await asyncio.sleep(max(0, self.interval - (time.monotonic() - self._last_request)))
                self._last_request = time.monotonic()
            try:
                async with self.session.request(method, url, **kwargs) as response:
                    if response.status == 429 or response.status >= 500:
                        retry = response.headers.get("Retry-After", "")
                        delay = max(1, float(retry)) if retry.isdigit() else 2 ** attempt
                        if attempt == attempts - 1 or delay > 30:
                            raise DataUnavailable(f"HTTP {response.status} after {attempts} attempts",
                                                  status=response.status, retry_after=delay)
                        await asyncio.sleep(delay)
                        continue
                    if response.status != 200:
                        raise DataUnavailable(f"HTTP {response.status}", status=response.status)
                    try:
                        return await response.json()
                    except (ValueError, aiohttp.ContentTypeError):
                        raise DataUnavailable("Invalid JSON response") from None
            except (aiohttp.ClientError, TimeoutError) as exc:
                if attempt == attempts - 1:
                    raise DataUnavailable(f"Transport failure: {type(exc).__name__}") from None
                await asyncio.sleep(2 ** attempt)
        raise DataUnavailable("Request exhausted")
