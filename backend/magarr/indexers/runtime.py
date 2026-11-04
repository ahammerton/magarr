"""Process-wide indexer plumbing: shared HTTP client, per-indexer rate limiting, query cache."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from magarr import APP_NAME, __version__

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
CACHE_TTL_SECONDS = 15 * 60
CACHE_MAX_ENTRIES = 500


class RateLimiter:
    """Serializes requests per key and keeps at least ``interval`` seconds between them."""

    def __init__(self, clock=time.monotonic, sleep=asyncio.sleep) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}
        self._clock = clock
        self._sleep = sleep

    @asynccontextmanager
    async def slot(self, key: str, interval: float) -> AsyncIterator[None]:
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            wait = self._last.get(key, float("-inf")) + interval - self._clock()
            if wait > 0:
                await self._sleep(wait)
            try:
                yield
            finally:
                self._last[key] = self._clock()


class TtlCache:
    """Small LRU cache of raw responses so repeated searches don't hammer indexers."""

    def __init__(
        self,
        ttl: float = CACHE_TTL_SECONDS,
        max_entries: int = CACHE_MAX_ENTRIES,
        clock=time.monotonic,
    ) -> None:
        self._data: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
        self._ttl = ttl
        self._max = max_entries
        self._clock = clock

    def get(self, key: str) -> bytes | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        expires, value = entry
        if expires < self._clock():
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return value

    def set(self, key: str, value: bytes) -> None:
        self._data[key] = (self._clock() + self._ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()


class ReleaseCache:
    """Recent search results, so a grab can be made by (indexer, guid) without the browser
    ever seeing download URLs (they embed indexer API keys)."""

    def __init__(self, ttl: float = 60 * 60, max_entries: int = 5000, clock=time.monotonic) -> None:
        self._data: OrderedDict[tuple[int | None, str], tuple[float, object]] = OrderedDict()
        self._ttl, self._max, self._clock = ttl, max_entries, clock

    def put(self, indexer_id: int | None, guid: str, release: object) -> None:
        key = (indexer_id, guid)
        self._data[key] = (self._clock() + self._ttl, release)
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def get(self, indexer_id: int | None, guid: str) -> object | None:
        entry = self._data.get((indexer_id, guid))
        if entry is None or entry[0] < self._clock():
            return None
        return entry[1]


class IndexerRuntime:
    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self.http = http or httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": f"{APP_NAME}/{__version__}"},
        )
        self.limiter = RateLimiter()
        self.cache = TtlCache()
        self.releases = ReleaseCache()
        # One grab at a time per issue (parallel RSS + backlog must not double-grab).
        self.issue_locks: dict[int, asyncio.Lock] = {}
        # RSS sync: guids already evaluated, per indexer, so each sync only looks at new ones.
        self.rss_seen: dict[int, dict[str, None]] = {}

    def issue_lock(self, issue_id: int) -> asyncio.Lock:
        return self.issue_locks.setdefault(issue_id, asyncio.Lock())

    async def aclose(self) -> None:
        await self.http.aclose()
