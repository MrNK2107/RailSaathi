"""Redis-backed SessionStore. Every key carries a TTL; the lock is a SET NX PX with an owner token."""

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from redis import Redis
from redis.exceptions import WatchError

from app.domain.state import SessionState
from app.sessions.store import SessionNotFoundError


class SessionLockTimeout(Exception):
    pass


class RedisSessionStore:
    def __init__(self, client: Redis, ttl_seconds: int, prefix: str = "rs", lock_ttl_ms: int = 30_000,
                 lock_wait_seconds: float = 10.0) -> None:
        self._r = client
        self._ttl = ttl_seconds
        self._prefix = prefix
        self._lock_ttl_ms = lock_ttl_ms
        self._lock_wait = lock_wait_seconds

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}:session:{session_id}"

    def _lock_key(self, session_id: str) -> str:
        return f"{self._prefix}:lock:{session_id}"

    def create(self, state: SessionState) -> None:
        self._r.set(self._key(state.session_id), state.model_dump_json(), ex=self._ttl)

    def get(self, session_id: str) -> SessionState:
        raw = self._r.get(self._key(session_id))
        if raw is None:
            raise SessionNotFoundError(session_id)
        return SessionState.model_validate_json(raw)

    def save(self, state: SessionState) -> None:
        # xx: never resurrect an expired or unknown session. The TTL is refreshed on every save.
        if not self._r.set(self._key(state.session_id), state.model_dump_json(), ex=self._ttl, xx=True):
            raise SessionNotFoundError(state.session_id)

    @contextmanager
    def lock(self, session_id: str) -> Iterator[None]:
        key = self._lock_key(session_id)
        token = uuid.uuid4().hex
        deadline = time.monotonic() + self._lock_wait
        while not self._r.set(key, token, nx=True, px=self._lock_ttl_ms):
            if time.monotonic() >= deadline:
                raise SessionLockTimeout(session_id)
            time.sleep(0.02)
        try:
            yield
        finally:
            self._release(key, token)

    def _release(self, key: str, token: str) -> None:
        """Delete the lock only if we still own it (it may have expired and been taken by someone else)."""
        with self._r.pipeline() as pipe:
            while True:
                try:
                    pipe.watch(key)
                    if pipe.get(key) == token:
                        pipe.multi()
                        pipe.delete(key)
                        pipe.execute()
                    break
                except WatchError:
                    continue
                finally:
                    pipe.reset()
