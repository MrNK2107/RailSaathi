"""Sliding-window rate limiters behind one interface: Redis (shared across instances) and a bounded in-memory one."""

import logging
import threading
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Protocol

from redis import Redis
from redis.exceptions import RedisError

log = logging.getLogger("railsaathi.ratelimit")


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after: int = 0  # whole seconds


class RateLimiter(Protocol):
    def hit(self, key: str, limit: int, window_seconds: int = 60) -> Decision: ...


class InMemoryRateLimiter:
    """Per-process sliding window. Bounded: at most `max_keys` keys (least recently used evicted)."""

    def __init__(self, max_keys: int = 10_000, now=time.monotonic) -> None:
        self._max_keys = max_keys
        self._now = now
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_seconds: int = 60) -> Decision:
        now = self._now()
        with self._lock:
            q = self._hits.pop(key, None)
            if q is None:
                q = deque()
            while q and q[0] <= now - window_seconds:
                q.popleft()
            allowed = len(q) < limit
            if allowed:
                q.append(now)
            retry = 0 if allowed else max(1, int(q[0] + window_seconds - now) + 1)
            self._hits[key] = q  # most recently used goes last
            while len(self._hits) > self._max_keys:
                self._hits.popitem(last=False)
            return Decision(allowed, retry)


class RedisRateLimiter:
    """Sliding window on a sorted set per key; every key expires with its window. Fails open if Redis is down."""

    def __init__(self, client: Redis, prefix: str = "rs") -> None:
        self._r = client
        self._prefix = prefix

    def hit(self, key: str, limit: int, window_seconds: int = 60) -> Decision:
        rkey = f"{self._prefix}:rl:{key}"
        now_ms = int(time.time() * 1000)
        member = f"{now_ms}-{uuid.uuid4().hex[:8]}"
        try:
            pipe = self._r.pipeline()
            pipe.zremrangebyscore(rkey, 0, now_ms - window_seconds * 1000)
            pipe.zadd(rkey, {member: now_ms})
            pipe.zcard(rkey)
            pipe.zrange(rkey, 0, 0, withscores=True)
            pipe.expire(rkey, window_seconds + 1)
            _, _, count, oldest, _ = pipe.execute()
            if count <= limit:
                return Decision(True)
            self._r.zrem(rkey, member)  # rejected hits do not extend the window
            oldest_ms = int(oldest[0][1]) if oldest else now_ms
            return Decision(False, max(1, (oldest_ms + window_seconds * 1000 - now_ms) // 1000 + 1))
        except RedisError:
            log.warning("rate limiter unavailable; failing open", exc_info=True)
            return Decision(True)
