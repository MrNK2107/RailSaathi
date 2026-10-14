import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import fakeredis
import pytest

from app.clock import FixedClock
from app.config import Settings
from app.container import build_container
from app.domain.enums import DataMode, Language
from app.domain.state import SessionState
from app.sessions.redis_store import RedisSessionStore, SessionLockTimeout
from app.sessions.store import InMemorySessionStore, SessionNotFoundError

NOW = datetime(2026, 10, 10, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


def make_state(sid="s1") -> SessionState:
    return SessionState(session_id=sid, language=Language.EN, data_mode=DataMode.DEMO, created_at=NOW, updated_at=NOW)


def raw(server) -> fakeredis.FakeStrictRedis:
    return fakeredis.FakeStrictRedis(server=server, decode_responses=True)


@pytest.fixture
def server():
    return fakeredis.FakeServer()


def store_on(server, **kw) -> RedisSessionStore:
    return RedisSessionStore(raw(server), ttl_seconds=60, **kw)


def test_create_get_save_roundtrip(server):
    store = store_on(server)
    store.create(make_state())
    assert store.get("s1").language == Language.EN
    store.save(make_state().model_copy(update={"language": Language.TA}))
    assert store.get("s1").language == Language.TA


def test_state_visible_across_instances(server):
    store_on(server).create(make_state())
    assert store_on(server).get("s1").session_id == "s1"


def test_unknown_session_raises(server):
    store = store_on(server)
    with pytest.raises(SessionNotFoundError):
        store.get("nope")
    with pytest.raises(SessionNotFoundError):
        store.save(make_state("nope"))


def test_every_key_has_ttl_and_save_refreshes_it(server):
    store = store_on(server)
    r = raw(server)
    store.create(make_state())
    assert 0 < r.ttl("rs:session:s1") <= 60
    r.expire("rs:session:s1", 5)
    store.save(make_state())
    assert r.ttl("rs:session:s1") > 5
    with store.lock("s1"):
        assert 0 < r.pttl("rs:lock:s1") <= 30_000
        assert all(r.pttl(k) > 0 for k in r.keys("*"))


def test_expired_session_is_not_found_and_not_resurrected(server):
    store = store_on(server)
    r = raw(server)
    store.create(make_state())
    r.delete("rs:session:s1")  # the effect of TTL expiry
    with pytest.raises(SessionNotFoundError):
        store.get("s1")
    with pytest.raises(SessionNotFoundError):
        store.save(make_state())
    assert r.exists("rs:session:s1") == 0


def test_lock_is_exclusive_across_store_instances(server):
    a, b = store_on(server), store_on(server, lock_wait_seconds=0.2)
    with a.lock("s1"):
        with pytest.raises(SessionLockTimeout), b.lock("s1"):
            pass
    with b.lock("s1"):  # released, so now free
        pass


def test_lock_serialises_concurrent_critical_sections(server):
    stores = [store_on(server) for _ in range(2)]
    inside = [0]
    overlap = []

    def work(store):
        for _ in range(5):
            with store.lock("s1"):
                inside[0] += 1
                overlap.append(inside[0])
                time.sleep(0.005)
                inside[0] -= 1

    threads = [threading.Thread(target=work, args=(s,)) for s in stores]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert max(overlap) == 1


def test_expired_lock_is_not_released_by_previous_owner(server):
    store = store_on(server)
    r = raw(server)
    with store.lock("s1"):
        r.set("rs:lock:s1", "someone-else", px=30_000)  # our lock expired and another owner took it
    assert r.get("rs:lock:s1") == "someone-else"


def test_lock_released_on_exception(server):
    store = store_on(server)
    with pytest.raises(RuntimeError), store.lock("s1"):
        raise RuntimeError("boom")
    with store.lock("s1"):
        pass


def test_container_picks_store_by_redis_presence(server):
    settings = Settings(_env_file=None)
    assert isinstance(build_container(settings, use_configured_llm=False).planner.store, InMemorySessionStore)
    c = build_container(settings, use_configured_llm=False, redis=raw(server))
    assert isinstance(c.planner.store, RedisSessionStore) and c.redis is not None


def test_in_memory_lock_is_a_context_manager():
    store = InMemorySessionStore(FixedClock(NOW), 10)
    store.create(make_state())
    with store.lock("s1"):
        pass
