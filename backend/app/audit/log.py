"""Audit history of important workflow events, kept separate from session state.

Records contain event types, statuses and field *names* only. Passenger
messages and personal details are never stored here.

Best effort and per instance: each replica keeps only the sessions it served, in a bounded LRU whose entries expire
with the session TTL (sliding on every new event). The durable record is the structured `audit` log line."""

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


log = logging.getLogger("railsaathi.audit")


class AuditEvent(BaseModel):
    at: datetime
    session_id: str
    type: str
    from_status: str | None = None
    to_status: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class AuditLog:
    def __init__(self, max_events_per_session: int = 500, max_sessions: int = 5_000,
                 ttl_seconds: float = 7_200, clock: Callable[[], float] = time.monotonic) -> None:
        # session_id -> (expires_at, events), least recently written first
        self._events: OrderedDict[str, tuple[float, list[AuditEvent]]] = OrderedDict()
        self._max = max_events_per_session
        self._max_sessions = max_sessions
        self._ttl = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()

    def _purge(self, now: float) -> None:
        while self._events:
            oldest, (expires_at, _) = next(iter(self._events.items()))
            if expires_at > now and len(self._events) <= self._max_sessions:
                break
            del self._events[oldest]

    def record(self, event: AuditEvent) -> None:
        with self._lock:
            now = self._clock()
            _, events = self._events.pop(event.session_id, (0.0, []))
            self._events[event.session_id] = (now + self._ttl, [*events, event][-self._max:])
            self._purge(now)
        # Same structured-log pipeline as requests (request id and trace are attached by the formatter). Only the
        # event type, statuses and detail field names are logged, never detail values or passenger text.
        log.info("audit", extra={"fields": {
            "audit_type": event.type, "session_id": event.session_id, "from_status": event.from_status,
            "to_status": event.to_status, "detail_fields": sorted(event.detail)}})

    def list(self, session_id: str) -> list[AuditEvent]:
        with self._lock:
            self._purge(self._clock())
            entry = self._events.get(session_id)
            return list(entry[1]) if entry else []

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)
