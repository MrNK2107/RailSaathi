"""Session persistence behind an interface (in-memory implementation for the prototype)."""

import threading
from datetime import datetime, timedelta
from typing import Protocol

from app.clock import Clock
from app.domain.state import SessionState


class SessionNotFoundError(Exception):
    pass


class SessionExpiredError(Exception):
    pass


class SessionStore(Protocol):
    def create(self, state: SessionState) -> None: ...

    def get(self, session_id: str) -> SessionState: ...

    def save(self, state: SessionState) -> None: ...

    def lock(self, session_id: str) -> threading.Lock: ...


class InMemorySessionStore:
    """Thread-safe, TTL-based store. Swap for Redis/Postgres via the SessionStore protocol."""

    def __init__(self, clock: Clock, ttl_minutes: int) -> None:
        self._clock = clock
        self._ttl = timedelta(minutes=ttl_minutes)
        self._data: dict[str, SessionState] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def create(self, state: SessionState) -> None:
        with self._guard:
            self._purge_expired(self._clock.now())
            self._data[state.session_id] = state
            self._locks[state.session_id] = threading.Lock()

    def get(self, session_id: str) -> SessionState:
        with self._guard:
            state = self._data.get(session_id)
            if state is None:
                raise SessionNotFoundError(session_id)
            if self._clock.now() - state.updated_at > self._ttl:
                self._drop(session_id)
                raise SessionExpiredError(session_id)
            return state

    def save(self, state: SessionState) -> None:
        with self._guard:
            if state.session_id not in self._data:
                raise SessionNotFoundError(state.session_id)
            self._data[state.session_id] = state

    def lock(self, session_id: str) -> threading.Lock:
        with self._guard:
            if session_id not in self._locks:
                raise SessionNotFoundError(session_id)
            return self._locks[session_id]

    def _purge_expired(self, now: datetime) -> None:
        expired = [sid for sid, s in self._data.items() if now - s.updated_at > self._ttl]
        for sid in expired:
            self._drop(sid)

    def _drop(self, session_id: str) -> None:
        self._data.pop(session_id, None)
        self._locks.pop(session_id, None)
