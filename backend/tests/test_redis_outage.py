"""A Redis outage on a stateful route is a retryable 503 envelope, never a 500 and never Redis error text."""

import fakeredis
from fastapi.testclient import TestClient

from app.api.internal_auth import require_internal_caller
from app.clock import FixedClock
from app.config import Settings
from app.container import build_container
from app.main import create_app
from tests.conftest import FIXED_NOW


def _client() -> tuple[TestClient, fakeredis.FakeServer]:
    server = fakeredis.FakeServer()
    redis = fakeredis.FakeStrictRedis(server=server, decode_responses=True)
    settings = Settings(_env_file=None)
    container = build_container(settings, clock=FixedClock(FIXED_NOW), use_configured_llm=False, redis=redis)
    app = create_app(settings, container)
    app.dependency_overrides[require_internal_caller] = lambda: "test-caller"
    return TestClient(app, raise_server_exceptions=False), server


def _assert_storage_503(res) -> None:
    assert res.status_code == 503, res.text
    body = res.json()
    assert body["error"]["code"] == "storage_unavailable"
    assert res.headers["Retry-After"]
    assert "redis" not in res.text.lower() and "connection" not in res.text.lower()


def test_planner_session_routes_answer_503_when_redis_is_down():
    c, server = _client()
    created = c.post("/api/planner/sessions", json={}).json()
    server.connected = False
    _assert_storage_503(c.post("/api/planner/sessions", json={}))
    _assert_storage_503(c.get(f"/api/planner/sessions/{created['session_id']}",
                              headers={"X-Session-Token": created["session_token"]}))


def test_goal_plan_store_outage_is_503():
    c, server = _client()
    c.headers["X-Session-Token"] = c.post("/api/planner/sessions", json={}).json()["session_token"]
    server.connected = False
    _assert_storage_503(c.post("/api/journey/plan", json={
        "origin": "Coimbatore", "destination_venue": "Tidel Park", "meeting_date": "2026-10-11",
        "meeting_time": "10:00"}))


def test_internal_disruption_route_outage_is_503():
    c, server = _client()
    server.connected = False
    _assert_storage_503(c.delete("/internal/stations/chennai_central/disruptions"))
