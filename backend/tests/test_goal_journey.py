"""Goal-based journey planner: provider-sourced trains only, honest provenance, session-bound plan ids."""

import fakeredis
import pytest

from app.domain.enums import DataMode
from app.journey.plan_store import InMemoryPlanStore, RedisPlanStore
from app.journey.venues import VenueDirectory, load_venues
from tests.test_rate_limit import make

PLAN = "/api/journey/plan"
REFINE = "/api/journey/refine"
# conftest FIXED_NOW is Saturday 10 Oct 2026, 10:00 IST.
BASE = {"origin": "Coimbatore", "destination_venue": "Tidel Park", "meeting_date": "2026-10-11",
        "meeting_time": "10:00"}


def token(c) -> str:
    return c.post("/api/planner/sessions", json={}).json()["session_token"]


@pytest.fixture(params=["memory", "redis"])
def client(request):
    redis = fakeredis.FakeStrictRedis(decode_responses=True) if request.param == "redis" else None
    c = make(redis=redis)
    c.headers["X-Session-Token"] = token(c)
    return c


def trains(body) -> set[str]:
    evs = ([body["best_match"]] if body["best_match"] else []) + body["feasible_alternatives"]
    return {e["candidate"]["train_number"] for e in evs}


def test_plan_returns_only_provider_trains_with_provenance(client):
    res = client.post(PLAN, json=BASE)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "answered" and body["plan_id"].startswith("plan_")
    assert body["provenance"]["mode"] == DataMode.DEMO
    every = trains(body) | {e["candidate"]["train_number"] for e in body["infeasible_options"]}
    assert every and all(t.startswith("D1") for t in every)  # demo provider trains, nothing hard-coded
    for ev in [body["best_match"], *body["feasible_alternatives"], *body["infeasible_options"]]:
        assert ev["candidate"]["provenance"]["mode"] == "demo"
    assert body["sources"][0]["title"] == body["provenance"]["source"]


def test_feasibility_respects_meeting_deadline_and_last_mile(client):
    body = client.post(PLAN, json=BASE).json()
    feasible = trains(body)
    # D101 (05:20) and D103 (06:45) reach Chennai Central in time; D105 reaches Egmore 09:40 -> too late.
    assert {"D101", "D103"} <= feasible and "D105" not in feasible
    best = body["best_match"]
    assert best["last_mile_duration_minutes"] > 0 and best["last_mile_mode"] == "cab"
    assert best["actual_arrival_buffer_minutes"] >= 45
    late = next(e for e in body["infeasible_options"] if e["candidate"]["train_number"] == "D105")
    assert late["hard_constraint_violations"]


def test_already_departed_trains_are_infeasible(client):
    body = client.post(PLAN, json=BASE).json()
    departed = [e for e in body["infeasible_options"] if e["candidate"]["option_id"] == "CBE-MAS-D107@2026-10-10"]
    assert departed and "already departed" in " ".join(departed[0]["hard_constraint_violations"])


def test_buffer_changes_feasibility(client):
    body = client.post(PLAN, json={**BASE, "required_arrival_buffer_minutes": 200}).json()
    feasible = trains(body)
    assert "D103" not in feasible  # 06:45 + last mile no longer leaves 200 minutes
    assert "D101" in feasible


def test_past_meeting_is_rejected(client):
    res = client.post(PLAN, json={**BASE, "meeting_date": "2026-10-09"})
    assert res.status_code == 422 and res.json()["error"]["code"] == "meeting_in_past"
    earlier_today = client.post(PLAN, json={**BASE, "meeting_date": "2026-10-10", "meeting_time": "09:00"})
    assert earlier_today.status_code == 422


def test_meeting_beyond_planning_window_is_rejected(client):
    res = client.post(PLAN, json={**BASE, "meeting_date": "2027-12-01"})
    assert res.status_code == 422 and res.json()["error"]["code"] == "date_out_of_range"


def test_missing_required_fields_ask_instead_of_defaulting(client):
    body = client.post(PLAN, json={"destination_venue": "Tidel Park"}).json()
    assert body["status"] == "clarification_required" and body["plan_id"] is None
    assert set(body["missing_fields"]) == {"origin", "meeting_date", "meeting_time"}
    assert body["provenance"]["mode"]


def test_unknown_venue_asks_for_the_station(client):
    body = client.post(PLAN, json={**BASE, "destination_venue": "Some Unknown Office Park"}).json()
    assert body["status"] == "clarification_required"
    assert body["missing_fields"] == ["destination_station"]
    assert "station" in body["clarification_question"].lower()
    answered = client.post(PLAN, json={**BASE, "destination_venue": "Some Unknown Office Park",
                                       "destination_station": "Chennai Central"}).json()
    assert answered["status"] == "answered"
    assert answered["best_match"]["last_mile_duration_minutes"] is None  # unknown, never invented


def test_prompt_is_parsed_without_hidden_defaults(client):
    body = client.post(PLAN, json={"prompt": "Meeting at Tidel Park on 11 October at 10 am, from Coimbatore"}).json()
    assert body["status"] == "answered"
    req = body["trip_requirements"]
    assert req["meeting_date"] == "2026-10-11" and req["meeting_time"] == "10:00" and req["origin"] == "Coimbatore"
    vague = client.post(PLAN, json={"prompt": "I need to reach a meeting"}).json()
    assert vague["status"] == "clarification_required" and "origin" in vague["missing_fields"]


def test_plan_requires_a_session_token():
    c = make()
    res = c.post(PLAN, json=BASE)
    assert res.status_code == 401 and res.json()["error"]["code"] == "invalid_session_token"


def test_refine_replans_the_owned_plan(client):
    plan = client.post(PLAN, json=BASE).json()
    res = client.post(REFINE, json={"plan_id": plan["plan_id"], "required_arrival_buffer_minutes": 200})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["plan_id"] == plan["plan_id"] and body["trip_requirements"]["required_arrival_buffer_minutes"] == 200
    assert "D103" not in trains(body)
    assert client.get(f"/api/journey/options/{plan['plan_id']}").json()["trip_requirements"][
        "required_arrival_buffer_minutes"] == 200


def test_refine_rejects_foreign_and_unknown_plan_ids(client):
    plan = client.post(PLAN, json=BASE).json()
    client.headers["X-Session-Token"] = token(client)  # a different session
    for path, payload in ((REFINE, {"plan_id": plan["plan_id"], "meeting_time": "11:00"}),
                          (REFINE, {"plan_id": "plan_doesnotexist", "meeting_time": "11:00"})):
        res = client.post(path, json=payload)
        assert res.status_code == 404 and res.json()["error"]["code"] == "plan_not_found"
    assert client.get(f"/api/journey/options/{plan['plan_id']}").status_code == 404


def test_refine_schema_is_strict(client):
    plan = client.post(PLAN, json=BASE).json()
    assert client.post(REFINE, json={"plan_id": plan["plan_id"], "requirements": {"origin": "x"}}).status_code == 422
    assert client.post(REFINE, json={"plan_id": plan["plan_id"], "preferred_class": "XYZ"}).status_code == 422
    assert client.post(REFINE, json={"plan_id": plan["plan_id"],
                                     "required_arrival_buffer_minutes": 5000}).status_code == 422
    assert client.post(REFINE, json={"plan_id": "bad id!", "meeting_time": "11:00"}).status_code == 422
    past = client.post(REFINE, json={"plan_id": plan["plan_id"], "meeting_date": "2026-10-01"})
    assert past.status_code == 422 and past.json()["error"]["code"] == "meeting_in_past"


def test_provider_outage_is_reported_as_unavailable():
    c = make(RAILWAY_DATA_MODE="railradar")  # live mode without a key: searches fail, never demo data
    c.headers["X-Session-Token"] = token(c)
    body = c.post(PLAN, json={**BASE, "destination_venue": None, "destination_station": "Chennai Central"}).json()
    assert body["status"] == "provider_unavailable"
    assert body["provenance"]["mode"] == "unavailable" and body["provenance"]["note"]
    assert body["best_match"] is None and body["feasible_alternatives"] == []


def test_plan_store_ttl_and_redis_roundtrip():
    from tests.conftest import FIXED_NOW  # noqa: F401 - documents the clock used by make()
    mem = InMemoryPlanStore(ttl_seconds=60, max_entries=2)
    for i in range(3):
        mem.save(f"p{i}", "owner", {"x": i})
    assert mem.load("p0") is None and mem.load("p2") == ("owner", {"x": 2})  # bounded
    r = fakeredis.FakeStrictRedis(decode_responses=True)
    store = RedisPlanStore(r, ttl_seconds=60, prefix="t")
    store.save("p1", "owner", {"x": 1})
    assert store.load("p1") == ("owner", {"x": 1}) and 0 < r.ttl("t:plan:p1") <= 60
    assert store.load("missing") is None


def test_venues_file_is_validated():
    directory = load_venues()
    assert isinstance(directory, VenueDirectory) and directory.find("tidel park").id == "tidel-park"
    assert directory.find("Tidel Park, Taramani") is not None and directory.find("nowhere") is None
    with pytest.raises(ValueError):
        VenueDirectory.model_validate({"venues": [{"id": "x", "name": "X", "aliases": [], "city": "c",
                                                    "access_stations": [], "unexpected": 1}]})


def test_agent_journey_tool_uses_the_same_provider():
    """The guidance agent's journey tool goes through the same GoalPlanner (no second timetable)."""
    c = make()
    res = c.post("/api/chat", json={"message": "Meeting at Tidel Park on 11 October at 10 am, from Coimbatore"})
    assert res.status_code == 200, res.text
    answer = res.json()["answer"]
    assert "D101" in answer or "D103" in answer
    assert "demo" in answer.lower()  # provenance is stated


def test_options_path_rejects_malformed_plan_ids(client):
    assert client.get("/api/journey/options/" + "x" * 300).status_code == 422
