"""Station disruption store: in-memory and Redis (fakeredis) behave the same, every Redis key expires, and expired
disruptions disappear."""

from datetime import timedelta

import fakeredis
import pytest

from app.navigation.models.station import DisruptionCreate, Station
from app.navigation.services.disruption_store import (DisruptionTargetNotFound, InMemoryDisruptionStore,
                                                      RedisDisruptionStore, build_disruption_store, new_disruption)
from tests.conftest import FIXED_NOW
from tests.station_fixture import station_raw

STATION = Station.model_validate(station_raw())


class MovingClock:
    def __init__(self) -> None:
        self.at = FIXED_NOW

    def now(self):
        return self.at


@pytest.fixture(params=["memory", "redis"])
def setup(request):
    clock = MovingClock()
    redis = fakeredis.FakeRedis(decode_responses=True)
    store = InMemoryDisruptionStore(clock) if request.param == "memory" else RedisDisruptionStore(redis, clock, "t")
    return store, clock, redis


def make(target_type="edge", target_id="e_ramp", ttl=None, now=FIXED_NOW, **kw):
    req = DisruptionCreate(target_type=target_type, target_id=target_id, reason="Lift under repair",
                           source="station control room", ttl_seconds=ttl, **kw)
    return new_disruption(STATION, req, now, default_ttl_seconds=3600)


def test_new_disruption_checks_the_target_and_sets_kind_and_expiry():
    d = make()
    assert d.kind == "pathway_closure" and d.station_id == "test_station" and d.simulated is False
    assert d.expires_at - d.created_at == timedelta(hours=1)
    assert make("node", "p1", ttl=120).kind == "facility_outage"
    assert make(ttl=120).expires_at == FIXED_NOW + timedelta(seconds=120)
    with pytest.raises(DisruptionTargetNotFound):
        make("edge", "p1")  # a node id is not an edge
    with pytest.raises(DisruptionTargetNotFound):
        make("node", "ghost")


def test_add_list_delete_clear(setup):
    store, _, _ = setup
    first, second = make(), make("node", "hall", now=FIXED_NOW + timedelta(seconds=1))
    store.add(first)
    store.add(second)
    assert [d.id for d in store.list("test_station")] == [first.id, second.id]
    assert store.list("other_station") == []
    assert store.delete("test_station", first.id) is True
    assert store.delete("test_station", first.id) is False
    assert [d.id for d in store.list("test_station")] == [second.id]
    assert store.clear("test_station") == 1
    assert store.list("test_station") == []


def test_disruptions_expire(setup):
    store, clock, _ = setup
    short, long = make(ttl=60), make("node", "hall", ttl=3600)
    store.add(short)
    store.add(long)
    clock.at = FIXED_NOW + timedelta(seconds=61)
    assert [d.id for d in store.list("test_station")] == [long.id]
    clock.at = FIXED_NOW + timedelta(seconds=3601)
    assert store.list("test_station") == []


def test_every_redis_key_has_a_ttl():
    redis = fakeredis.FakeRedis(decode_responses=True)
    clock = MovingClock()
    store = RedisDisruptionStore(redis, clock, "t")
    short = make(ttl=600)
    store.add(short)
    store.add(make("node", "hall", ttl=1200))
    keys = redis.keys("t:navdis:*")
    assert len(keys) == 3  # two disruptions and the station index
    for key in keys:
        assert redis.ttl(key) > 0
    assert 0 < redis.ttl(f"t:navdis:test_station:{short.id}") <= 600
    assert 600 < redis.ttl("t:navdis:test_station") <= 1201  # the index lives as long as its longest member


def test_redis_store_is_shared_between_instances():
    redis = fakeredis.FakeRedis(decode_responses=True)
    a = RedisDisruptionStore(redis, MovingClock(), "t")
    b = RedisDisruptionStore(redis, MovingClock(), "t")
    d = make()
    a.add(d)
    assert [x.id for x in b.list("test_station")] == [d.id]


def test_build_picks_redis_when_available():
    clock = MovingClock()
    assert isinstance(build_disruption_store(clock, None, "t"), InMemoryDisruptionStore)
    assert isinstance(build_disruption_store(clock, fakeredis.FakeRedis(decode_responses=True), "t"),
                      RedisDisruptionStore)
