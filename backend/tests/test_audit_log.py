"""The per-instance audit history is bounded: an LRU over sessions whose entries expire with the session TTL."""

from datetime import datetime, timezone

from app.audit.log import AuditEvent, AuditLog


def _event(session_id: str, kind: str = "transition") -> AuditEvent:
    return AuditEvent(at=datetime.now(timezone.utc), session_id=session_id, type=kind)


class Tick:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_least_recently_written_sessions_are_evicted_past_the_bound():
    log = AuditLog(max_sessions=3, clock=Tick())
    for sid in ("a", "b", "c"):
        log.record(_event(sid))
    log.record(_event("a"))  # "a" is now the most recently written
    log.record(_event("d"))
    assert len(log) == 3
    assert log.list("b") == []
    assert [e.session_id for e in log.list("a")] == ["a", "a"]


def test_entries_expire_with_the_session_ttl_and_writes_slide_it():
    clock = Tick()
    log = AuditLog(ttl_seconds=100, clock=clock)
    log.record(_event("old"))
    clock.now = 60
    log.record(_event("kept"))
    clock.now = 101
    assert log.list("old") == []
    assert len(log.list("kept")) == 1
    log.record(_event("kept"))  # slides "kept" to 201
    clock.now = 200
    assert len(log.list("kept")) == 2
    clock.now = 202
    assert log.list("kept") == [] and len(log) == 0


def test_events_per_session_are_still_capped():
    log = AuditLog(max_events_per_session=2, clock=Tick())
    for kind in ("one", "two", "three"):
        log.record(_event("s", kind))
    assert [e.type for e in log.list("s")] == ["two", "three"]
