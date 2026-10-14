import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.clock import FixedClock
from app.config import Settings
from app.container import build_container
from app.main import create_app
from app.security.rate_limit import InMemoryRateLimiter, RedisRateLimiter
from tests.conftest import FIXED_NOW

REF = "/api/planner/reference"


def make(redis=None, **overrides) -> TestClient:
    overrides.setdefault("trusted_proxy_hops", 2)
    settings = Settings(_env_file=None, **overrides)
    container = build_container(settings, clock=FixedClock(FIXED_NOW), use_configured_llm=False, redis=redis)
    return TestClient(create_app(settings, container))


def xff(ip):
    return {"X-Forwarded-For": f"{ip}, 10.0.0.1"}


@pytest.fixture(params=["memory", "redis"])
def client_factory(request):
    def factory(**kw):
        redis = fakeredis.FakeStrictRedis(decode_responses=True) if request.param == "redis" else None
        return make(redis=redis, **kw)
    return factory


def test_limit_enforced_with_retry_after(client_factory):
    c = client_factory(rate_limit_per_minute=3)
    codes = [c.get(REF, headers=xff("1.1.1.1")).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    r = c.get(REF, headers=xff("1.1.1.1"))
    assert r.json()["error"]["code"] == "rate_limited" and int(r.headers["Retry-After"]) >= 1


def test_keyed_on_first_forwarded_hop(client_factory):
    c = client_factory(rate_limit_per_minute=2)
    for _ in range(2):
        assert c.get(REF, headers=xff("1.1.1.1")).status_code == 200
    assert c.get(REF, headers=xff("1.1.1.1")).status_code == 429
    assert c.get(REF, headers=xff("2.2.2.2")).status_code == 200
    # Same first hop, different later hops: still the same client.
    assert c.get(REF, headers={"X-Forwarded-For": "1.1.1.1, 9.9.9.9"}).status_code == 429


def test_falls_back_to_client_host(client_factory):
    c = client_factory(rate_limit_per_minute=1)
    assert c.get(REF).status_code == 200
    assert c.get(REF).status_code == 429


def test_health_is_exempt(client_factory):
    c = client_factory(rate_limit_per_minute=1)
    assert all(c.get("/api/health").status_code == 200 for _ in range(5))
    assert c.get(REF).status_code == 200


def test_llm_tier_is_lower(client_factory):
    c = client_factory(rate_limit_per_minute=10, rate_limit_llm_per_minute=2)
    created = c.post("/api/planner/sessions", json={}, headers=xff("3.3.3.3")).json()
    url = f"/api/planner/sessions/{created['session_id']}/messages"
    h = {**xff("3.3.3.3"), "X-Session-Token": created["session_token"]}
    codes = [c.post(url, json={"message": "hello"}, headers=h).status_code for _ in range(4)]
    assert codes == [200, 200, 429, 429]
    # The standard tier for the same client is unaffected.
    assert c.get(REF, headers=xff("3.3.3.3")).status_code == 200
    chat = [c.post("/api/chat", json={"message": "tatkal"}, headers=xff("4.4.4.4")).status_code for _ in range(3)]
    assert chat[2] == 429


def test_session_token_has_its_own_bucket(client_factory):
    c = client_factory(rate_limit_per_minute=3)
    created = c.post("/api/planner/sessions", json={}, headers=xff("5.5.5.5")).json()
    tok = {"X-Session-Token": created["session_token"]}
    # The same session from rotating IPs is still capped.
    codes = [c.get(f"/api/planner/sessions/{created['session_id']}", headers={**xff(f"6.6.6.{i}"), **tok}).status_code
             for i in range(5)]
    assert codes == [200, 200, 200, 429, 429]


def test_forged_token_does_not_bypass_ip_bucket(client_factory):
    c = client_factory(rate_limit_per_minute=2)
    for i in range(2):
        c.get(REF, headers={**xff("7.7.7.7"), "X-Session-Token": f"fake{i}.sig"})
    assert c.get(REF, headers=xff("7.7.7.7")).status_code == 429


def test_in_memory_limiter_is_bounded_and_recovers():
    t = {"now": 0.0}
    lim = InMemoryRateLimiter(max_keys=50, now=lambda: t["now"])
    for i in range(500):
        lim.hit(f"k{i}", 5)
    assert len(lim._hits) <= 50
    assert [lim.hit("a", 2).allowed for _ in range(3)] == [True, True, False]
    t["now"] = 61
    assert lim.hit("a", 2).allowed


def test_redis_limiter_keys_expire_and_rejections_do_not_extend():
    r = fakeredis.FakeStrictRedis(decode_responses=True)
    lim = RedisRateLimiter(r)
    assert [lim.hit("k", 2).allowed for _ in range(5)] == [True, True, False, False, False]
    assert r.zcard("rs:rl:k") == 2
    assert 0 < r.ttl("rs:rl:k") <= 61


def test_spoofed_leading_xff_does_not_change_bucket(client_factory):
    c = client_factory(rate_limit_per_minute=2)
    # Real client 8.8.8.8 (second from right); the attacker rotates the client-controlled leading entries.
    for i in range(2):
        h = {"X-Forwarded-For": f"66.66.66.{i}, 8.8.8.8, 10.0.0.1"}
        assert c.get(REF, headers=h).status_code == 200
    assert c.get(REF, headers={"X-Forwarded-For": "77.7.7.7, 8.8.8.8, 10.0.0.1"}).status_code == 429


def test_zero_hops_ignores_xff(client_factory):
    c = client_factory(rate_limit_per_minute=1, trusted_proxy_hops=0)
    assert c.get(REF, headers=xff("1.1.1.1")).status_code == 200
    assert c.get(REF, headers=xff("2.2.2.2")).status_code == 429


def test_too_few_xff_entries_falls_back_to_peer(client_factory):
    c = client_factory(rate_limit_per_minute=1)
    assert c.get(REF, headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 200
    assert c.get(REF, headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 429


def test_slow_limiter_fails_open():
    import time

    class Slow:
        def hit(self, key, limit, window_seconds=60):
            time.sleep(0.5)
            raise AssertionError("should have been abandoned")

    from app.api.middleware import RateLimitMiddleware

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    from starlette.testclient import TestClient as TC
    mw = RateLimitMiddleware(app, Slow(), 1, 1, limiter_timeout=0.05)
    assert TC(mw).get("/x").status_code == 200
