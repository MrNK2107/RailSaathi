"""Quota gate and response cache for RailRadar, shared by every instance through Redis.

RailRadar allows ~10 requests per minute per API key. With several Cloud Run instances a per-process counter would
multiply that, so the Redis implementations count across all instances (keyed by a hash of the API key, never the
key itself). In-memory implementations serve local development and tests.

Both interfaces are async. The Redis implementations wrap the container's synchronous client with
asyncio.to_thread so a slow Redis never blocks the event loop."""

import asyncio
import hashlib
import json
import logging
import math
import threading
import time
import uuid
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from redis import Redis
from redis.exceptions import RedisError

log = logging.getLogger("railsaathi.railradar")

WINDOW_SECONDS = 60
OUTAGE_RETRY_AFTER = 5  # seconds suggested to callers while the quota store is down


def key_fingerprint(api_key: str) -> str:
    """Stable, non-reversible identifier for the API key used in Redis key names."""
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class QuotaDecision:
    allowed: bool
    retry_after: int = 0  # whole seconds until a slot frees up


@dataclass(frozen=True)
class CacheEntry:
    data: Any
    fetched_at: datetime
    fresh_until: float  # epoch seconds; after this the entry is stale (usable only when quota is exhausted)


class QuotaGate(Protocol):
    async def acquire(self) -> QuotaDecision: ...

    async def remaining(self) -> int:
        """Requests still free in the current window (a peek: consumes nothing)."""
        ...


class ResponseCache(Protocol):
    async def get(self, key: str) -> CacheEntry | None: ...
    async def set(self, key: str, entry: CacheEntry) -> None: ...


class InMemoryQuotaGate:
    """Per-process sliding window of `rpm` requests per minute."""

    def __init__(self, rpm: int = 10, clock: Callable[[], float] = time.time) -> None:
        self._rpm = rpm
        self._clock = clock
        self._sent: deque[float] = deque()
        self._lock = threading.Lock()

    def _expire(self, now: float) -> None:
        while self._sent and now - self._sent[0] >= WINDOW_SECONDS:
            self._sent.popleft()

    async def remaining(self) -> int:
        with self._lock:
            self._expire(self._clock())
            return max(0, self._rpm - len(self._sent))

    async def acquire(self) -> QuotaDecision:
        with self._lock:
            now = self._clock()
            self._expire(now)
            if len(self._sent) >= self._rpm:
                return QuotaDecision(False, max(1, math.ceil(WINDOW_SECONDS - (now - self._sent[0]))))
            self._sent.append(now)
            return QuotaDecision(True)


class InMemoryResponseCache:
    """Bounded per-process cache; entries are kept `stale_seconds` past their freshness for stale serving."""

    def __init__(self, stale_seconds: int = 21_600, max_entries: int = 512,
                 clock: Callable[[], float] = time.time) -> None:
        self._stale = stale_seconds
        self._max = max_entries
        self._clock = clock
        self._items: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.Lock()

    async def get(self, key: str) -> CacheEntry | None:
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return None
            if self._clock() > entry.fresh_until + self._stale:
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return entry

    async def set(self, key: str, entry: CacheEntry) -> None:
        with self._lock:
            self._items[key] = entry
            self._items.move_to_end(key)
            while len(self._items) > self._max:
                self._items.popitem(last=False)


class RedisQuotaGate:
    """Sliding window on a sorted set shared by all instances. If Redis is unreachable it FAILS CLOSED (reports
    the quota as exhausted): a per-process fallback would let N replicas multiply the shared key's budget, so the
    client serves its stale cache or reports the data as unavailable instead."""

    def __init__(self, client: Redis, api_key: str, rpm: int = 10, prefix: str = "rs",
                 clock: Callable[[], float] = time.time) -> None:
        self._r = client
        self._rpm = rpm
        self._key = f"{prefix}:rr:quota:{key_fingerprint(api_key)}"
        self._clock = clock

    def _hit(self) -> QuotaDecision:
        now_ms = int(self._clock() * 1000)
        member = f"{now_ms}-{uuid.uuid4().hex[:8]}"
        pipe = self._r.pipeline(transaction=True)
        pipe.zremrangebyscore(self._key, 0, now_ms - WINDOW_SECONDS * 1000)
        pipe.zadd(self._key, {member: now_ms})
        pipe.zcard(self._key)
        pipe.zrange(self._key, 0, 0, withscores=True)
        pipe.expire(self._key, WINDOW_SECONDS + 1)
        _, _, count, oldest, _ = pipe.execute()
        if count <= self._rpm:
            return QuotaDecision(True)
        self._r.zrem(self._key, member)  # a rejected attempt does not consume quota
        oldest_ms = int(oldest[0][1]) if oldest else now_ms
        return QuotaDecision(False, max(1, math.ceil((oldest_ms + WINDOW_SECONDS * 1000 - now_ms) / 1000)))

    async def acquire(self) -> QuotaDecision:
        try:
            return await asyncio.to_thread(self._hit)
        except RedisError:
            log.warning("RailRadar quota store unavailable; failing closed", exc_info=True)
            return QuotaDecision(False, OUTAGE_RETRY_AFTER)

    def _count(self) -> int:
        now_ms = int(self._clock() * 1000)
        pipe = self._r.pipeline(transaction=True)
        pipe.zremrangebyscore(self._key, 0, now_ms - WINDOW_SECONDS * 1000)
        pipe.zcard(self._key)
        return int(pipe.execute()[1])

    async def remaining(self) -> int:
        try:
            return max(0, self._rpm - await asyncio.to_thread(self._count))
        except RedisError:
            return 0  # fail closed, like acquire()


class RedisResponseCache:
    """JSON entries in Redis. The Redis TTL is the stale window, so old entries remain available when the quota
    is exhausted; the client decides freshness from `fresh_until`. Redis errors behave as a cache miss."""

    def __init__(self, client: Redis, api_key: str, stale_seconds: int = 21_600, prefix: str = "rs",
                 clock: Callable[[], float] = time.time) -> None:
        self._r = client
        self._prefix = f"{prefix}:rr:cache:{key_fingerprint(api_key)}"
        self._stale = stale_seconds
        self._clock = clock

    def _rkey(self, key: str) -> str:
        return f"{self._prefix}:{hashlib.sha256(key.encode()).hexdigest()[:24]}"

    def _get(self, key: str) -> CacheEntry | None:
        raw = self._r.get(self._rkey(key))
        if raw is None:
            return None
        try:
            doc = json.loads(raw)
            return CacheEntry(doc["data"], datetime.fromisoformat(doc["fetched_at"]), float(doc["fresh_until"]))
        except (ValueError, KeyError, TypeError):
            return None

    def _set(self, key: str, entry: CacheEntry) -> None:
        ttl = max(1, math.ceil(entry.fresh_until - self._clock()) + self._stale)
        doc = {"data": entry.data, "fetched_at": entry.fetched_at.isoformat(), "fresh_until": entry.fresh_until}
        self._r.set(self._rkey(key), json.dumps(doc), ex=ttl)

    async def get(self, key: str) -> CacheEntry | None:
        try:
            return await asyncio.to_thread(self._get, key)
        except RedisError:
            log.warning("RailRadar cache unavailable", exc_info=True)
            return None

    async def set(self, key: str, entry: CacheEntry) -> None:
        try:
            await asyncio.to_thread(self._set, key, entry)
        except RedisError:
            log.warning("RailRadar cache unavailable", exc_info=True)
