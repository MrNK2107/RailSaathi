import uuid

import pytest
from fastapi.testclient import TestClient

from app.clock import FixedClock
from app.config import Settings
from app.container import build_container
from app.main import create_app
from tests.conftest import FIXED_NOW


def make_client(**overrides) -> TestClient:
    settings = Settings(_env_file=None, **overrides)
    container = build_container(settings, clock=FixedClock(FIXED_NOW), use_configured_llm=False)
    return TestClient(create_app(settings, container))


@pytest.fixture
def client():
    return make_client()


def new_session(client, lang="en") -> str:
    r = client.post("/api/planner/sessions", json={"language": lang})
    assert r.status_code == 201
    return r.json()["session_id"]


def msg(client, sid, text, **extra):
    r = client.post(f"/api/planner/sessions/{sid}/messages", json={"message": text, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_health_reports_mode_without_secrets():
    c = make_client(llm_provider="bedrock", aws_region="us-east-1")
    body = c.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["data_mode"] == "demo"
    assert body["ai"]["bedrock_configured"] is False
    assert body["ai"]["fallback"] == "rule_based_extractor"
    assert "secret" not in str(body).lower() and "key" not in str(body).lower()


def test_session_creation_returns_initial_state(client):
    r = client.post("/api/planner/sessions", json={})
    body = r.json()
    assert body["status"] == "collecting_details"
    assert body["data_mode"] == "demo" and "DEMO DATA" in body["data_notice"]
    assert set(body["missing_fields"]) == {"origin", "destination", "journey_date", "passenger_count"}


def test_full_planning_flow_to_handoff(client):
    sid = new_session(client)
    body = msg(client, sid, "I need to reach Chennai before 9 AM tomorrow")
    assert body["missing_fields"] == ["origin", "passenger_count"]
    msg(client, sid, "from Coimbatore")
    body = msg(client, sid, "2 passengers, cheapest please")
    assert body["recommendations_ready"] is True
    option_id = body["state"]["recommendations"]["recommendations"][0]["option"]["option_id"]
    r = client.post(f"/api/planner/sessions/{sid}/select", json={"option_id": option_id})
    assert r.json()["confirmation_required"] is True
    r = client.post(f"/api/planner/sessions/{sid}/confirm", json={"option_id": option_id})
    body = r.json()
    assert body["status"] == "confirmed"
    assert body["handoff"]["selected_option"]["option_id"] == option_id
    h = client.get(f"/api/planner/sessions/{sid}/handoff").json()
    assert h["module"] == "smart_passenger_planner" and h["verification"]["seat_availability_checked"] is False


def test_recommendations_endpoint_requires_valid_details(client):
    sid = new_session(client)
    msg(client, sid, "to Chennai")
    r = client.post(f"/api/planner/sessions/{sid}/recommendations")
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "not_ready" and "origin" in err["details"]["missing_fields"]


def test_patch_journey_and_explicit_recommendations(client):
    sid = new_session(client)
    r = client.patch(f"/api/planner/sessions/{sid}/journey", json={
        "origin": "Coimbatore", "destination": "Bengaluru", "journey_date": "2026-10-11", "passenger_count": 1})
    assert r.status_code == 200
    assert r.json()["state"]["journey"]["destination"]["id"] == "bengaluru"
    r = client.post(f"/api/planner/sessions/{sid}/recommendations")
    assert r.json()["status"] == "presenting_recommendations"


def test_patch_rejects_invalid_values(client):
    sid = new_session(client)
    r = client.patch(f"/api/planner/sessions/{sid}/journey", json={"passenger_count": 0})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"
    r = client.patch(f"/api/planner/sessions/{sid}/journey", json={"unknown_field": 1})
    assert r.status_code == 422


def test_reassess_endpoint(client):
    sid = new_session(client)
    body = msg(client, sid, "from Coimbatore to Chennai, cheapest, must reach before 9 am tomorrow, 2 passengers")
    d103 = next(r["option"]["option_id"] for r in body["state"]["recommendations"]["recommendations"]
                if r["option"]["legs"][0]["train_no"] == "D103")
    client.post(f"/api/planner/sessions/{sid}/select", json={"option_id": d103})
    client.post(f"/api/planner/sessions/{sid}/confirm", json={})
    r = client.post(f"/api/planner/sessions/{sid}/reassess", json={"event_id": "SIM-DELAY-D103"})
    body = r.json()
    assert body["state"]["reassessment"]["original_still_valid"] is False
    assert body["state"]["reassessment"]["simulated"] is True
    assert body["confirmation_required"] is False and body["status"] == "presenting_recommendations"


def test_errors_are_structured(client):
    missing = str(uuid.uuid4())
    r = client.post(f"/api/planner/sessions/{missing}/messages", json={"message": "hi"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "session_not_found"
    r = client.post("/api/planner/sessions/not-a-uuid/messages", json={"message": "hi"})
    assert r.status_code == 422
    sid = new_session(client)
    r = client.post(f"/api/planner/sessions/{sid}/messages", json={"message": ""})
    assert r.status_code == 422
    r = client.post(f"/api/planner/sessions/{sid}/confirm", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_ready"


def test_body_size_limit():
    c = make_client(max_body_bytes=1024)
    sid = new_session(c)
    r = c.post(f"/api/planner/sessions/{sid}/messages", json={"message": "x" * 999, "language": "en", "pad": "y" * 2000})
    assert r.status_code == 413


def test_rate_limit():
    c = make_client(rate_limit_per_minute=3)
    codes = [c.post("/api/planner/sessions", json={}).status_code for _ in range(5)]
    assert codes[:3] == [201, 201, 201] and 429 in codes[3:]


def test_cors_allows_configured_origin_only(client):
    ok = client.options("/api/health", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    bad = client.options("/api/health", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in bad.headers


def test_cancel_endpoint_and_audit(client):
    sid = new_session(client)
    r = client.post(f"/api/planner/sessions/{sid}/cancel")
    assert r.json()["status"] == "cancelled"
    events = client.get(f"/api/planner/sessions/{sid}/audit").json()
    assert events[-1]["to_status"] == "cancelled"


def test_reference_data(client):
    ref = client.get("/api/planner/reference").json()
    assert any(p["id"] == "chennai" for p in ref["places"])
    assert all(e["simulated"] for e in ref["disruption_events"])


def test_openapi_available(client):
    spec = client.get("/openapi.json").json()
    assert "/api/planner/sessions/{session_id}/messages" in spec["paths"]
