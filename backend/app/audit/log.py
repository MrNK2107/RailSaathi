"""Audit history of important workflow events, kept separate from session state.

Records contain event types, statuses and field *names* only. Passenger
messages and personal details are never stored here."""

import logging
import threading
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
    def __init__(self, max_events_per_session: int = 500) -> None:
        self._events: dict[str, list[AuditEvent]] = {}
        self._max = max_events_per_session
        self._lock = threading.Lock()

    def record(self, event: AuditEvent) -> None:
        with self._lock:
            events = self._events.get(event.session_id, [])
            self._events[event.session_id] = [*events, event][-self._max:]
        # Same structured-log pipeline as requests (request id and trace are attached by the formatter). Only the
        # event type, statuses and detail field names are logged, never detail values or passenger text.
        log.info("audit", extra={"fields": {
            "audit_type": event.type, "session_id": event.session_id, "from_status": event.from_status,
            "to_status": event.to_status, "detail_fields": sorted(event.detail)}})

    def list(self, session_id: str) -> list[AuditEvent]:
        with self._lock:
            return list(self._events.get(session_id, []))
