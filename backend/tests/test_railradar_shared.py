"""RailRadar quota and cache shared through Redis (fakeredis) and their in-memory twins."""

import asyncio
from datetime import date, datetime, timezone

import fakeredis
import httpx
import pytest

from app.domain.enums import DataMode
from app.providers.errors import ProviderError, ProviderErrorKind
from app.providers.railradar import RailRadarJourneyProvider
from app.providers.railradar_client import RailRadarClient
from app.providers.railradar_shared import (
    InMemoryQuotaGate,
    RedisQuotaGate,
    RedisResponseCache,
    key_fingerprint,
)

KEY = "rr_shared_test_key"
DAY = date(2026, 10, 11)
FETCHED = datetime(2026, 10, 10, 4, 30, tzinfo=timezone.utc)
TRAIN = {"train": {"number": "12676", "name": "Kovai Express"},
         "from": {"code": "CBE", "name": "Coimbatore Jn", "departure": "15:15"},
         "to": {"code": "MAS", "name": "MGR Chennai Central", "arrival": "23:00"}, "duration": 465}


def transport(calls: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"success": True, "data": {"count": 1, "trains": [TRAIN]}})
    return httpx.MockTransport(handler)


def redis_client(server: fakeredis.FakeServer) -> fakeredis.FakeStrictRedis:
    return fakeredis.FakeStrictRedis(server=server, decode_responses=True)


def make_client(redis, calls, clock, rpm=10, cache_seconds=300) -> RailRadarClient:
    return RailRadarClient("https://rr.test", KEY, 5, cache_seconds, transport=transport(calls),
                           wall_clock=lambda: FETCHED, clock=clock, stale_seconds=3600,
                           quota=RedisQuotaGate(redis, KEY, rpm, "t", clock),
                           cache=RedisResponseCache(redis, KEY, 3600, "t", clock))


def test_two_clients_sharing_redis_never_exceed_the_quota():
    server, calls, now = fakeredis.FakeServer(), [], lambda: 1000.0
    a = make_client(redis_client(server), calls, now)
    b = make_client(redis_client(server), calls, now)

    async def hammer():
        stations = [f"S{i:02d}" for i in range(30)]
        jobs = [(a if i % 2 else b).trains_between("CBE", s, DAY) for i, s in enumerate(stations)]
        return await asyncio.gather(*jobs, return_exceptions=True)

    results = asyncio.run(hammer())
    assert len(calls) == 10  # exactly the shared budget, however the 30 requests were spread
    ok = [r for r in results if not isinstance(r, Exception)]
    denied = [r for r in results if isinstance(r, ProviderError)]
    assert len(ok) == 10 and len(denied) == 20
    assert all(d.kind is ProviderErrorKind.RATE_LIMITED for d in denied)


def test_quota_window_moves_on_and_key_is_hashed():
    server, t = fakeredis.FakeServer(), {"now": 1000.0}
    r = redis_client(server)
    gate = RedisQuotaGate(r, KEY, 2, "t", lambda: t["now"])

    async def go():
        first = [await gate.acquire() for _ in range(3)]
        t["now"] += 61
        return first, await gate.acquire()

    first, later = asyncio.run(go())
    assert [d.allowed for d in first] == [True, True, False] and first[2].retry_after >= 1
    assert later.allowed
    assert all(KEY not in k for k in r.keys("*")) and key_fingerprint(KEY) in r.keys("*")[0]


def test_stale_cache_served_when_quota_exhausted_then_label_reaches_provenance():
    server, calls, t = fakeredis.FakeServer(), [], {"now": 0.0}
    client = make_client(redis_client(server), calls, lambda: t["now"], rpm=1, cache_seconds=50)

    async def go():
        first = await client.trains_between("CBE", "MAS", DAY)  # uses the only slot at t=0, cached 50 s
        t["now"] = 90.0
        await client.trains_between("CBE", "SBC", DAY)  # slot of t=0 expired; this one takes the slot
        t["now"] = 100.0  # first entry is stale (fresh until 50), quota exhausted by the t=90 call
        stale = await client.trains_between("CBE", "MAS", DAY)
        with pytest.raises(ProviderError) as err:
            await client.trains_between("CBE", "UNCACHED", DAY)  # nothing cached to fall back on
        return first, stale, err.value

    first, stale, err = asyncio.run(go())
    assert first.mode is DataMode.LIVE
    assert stale.mode is DataMode.STALE and stale.data == first.data and stale.fetched_at == first.fetched_at
    assert err.kind is ProviderErrorKind.RATE_LIMITED
    assert len(calls) == 2  # the stale read never reached RailRadar

    provider = RailRadarJourneyProvider(client)
    options = provider.search(["CBE"], ["MAS"], [DAY])
    assert options and all(o.provenance.mode is DataMode.STALE and "STALE" in o.provenance.note for o in options)


def test_fresh_entry_is_shared_between_instances():
    server, calls, now = fakeredis.FakeServer(), [], lambda: 5.0
    a = make_client(redis_client(server), calls, now)
    b = make_client(redis_client(server), calls, now)

    async def go():
        return await a.trains_between("CBE", "MAS", DAY), await b.trains_between("CBE", "MAS", DAY)

    first, second = asyncio.run(go())
    assert len(calls) == 1 and second.data == first.data and second.mode is DataMode.LIVE


def test_redis_outage_falls_back_to_a_local_window_and_cache_miss():
    server, calls = fakeredis.FakeServer(), []
    server.connected = False
    client = make_client(redis_client(server), calls, lambda: 1.0, rpm=2)

    async def go():
        got = [await client.trains_between("CBE", s, DAY) for s in ("A", "B")]
        with pytest.raises(ProviderError) as err:
            await client.trains_between("CBE", "C", DAY)
        return got, err.value

    got, err = asyncio.run(go())
    assert len(got) == 2 and err.kind is ProviderErrorKind.RATE_LIMITED and len(calls) == 2


def test_in_memory_gate_limits_and_reports_wait():
    t = {"now": 100.0}
    gate = InMemoryQuotaGate(1, lambda: t["now"])

    async def go():
        a = await gate.acquire()
        t["now"] += 10
        return a, await gate.acquire()

    a, b = asyncio.run(go())
    assert a.allowed and not b.allowed and b.retry_after == 50
