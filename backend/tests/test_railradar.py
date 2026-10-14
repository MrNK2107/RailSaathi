"""RailRadar integration tests. All HTTP is served by httpx.MockTransport; no network or API key.

Fixtures follow the DOCUMENTED response shape (railradar.in/docs/trains-between-stations) and the
error envelopes OBSERVED from api.railradar.in on 2026-10-10 (unauthenticated probes).
"""

from datetime import date, datetime, time, timezone

import httpx
import pytest

from app.clock import FixedClock
from app.config import Settings
from app.container import build_container, build_data_sources
from app.domain.enums import DataMode, Language, RecommendationCategory as Cat
from app.domain.enums import Verification, WorkflowStatus as S
from app.harness.errors import PlannerError
from app.providers.errors import ProviderError, ProviderErrorKind
from app.providers.railradar import RailRadarJourneyProvider
from app.providers.railradar_client import RailRadarClient
from app.providers.railradar_mapper import MappingError, map_live_status, map_train, parse_clock, parse_minutes
from tests.conftest import FIXED_NOW, IST

KEY = "rr_test_key_not_real"
FETCHED_AT = datetime(2026, 10, 10, 4, 30, tzinfo=timezone.utc)  # 10:00 IST


def envelope(data, success=True):
    return {"success": success, "data": data, "meta": {"traceId": "t-1"}}


# Documented item shape.
DOCUMENTED = {"train": {"number": "12676", "name": "Kovai Express", "type": "SF"},
              "from": {"code": "CBE", "name": "Coimbatore Jn", "departure": "15:15"},
              "to": {"code": "MAS", "name": "MGR Chennai Central", "arrival": "23:00"},
              "duration": 465, "distance": 497, "totalHaltsBetween": 6}
# Fallback spellings (kept until a real response is observed) and an unusable record.
FALLBACK = {"train": {"number": "12672", "name": "Nilgiri Express"},
            "from": {"code": "CBE", "departureTime": "21:15"}, "to": {"code": "MAS", "arrivalTime": "05:20"},
            "classes": "SL,3A,2A,1A", "fares": [{"class": "SL", "fare": 315}, {"class": "3A", "fare": 830}]}
BROKEN = {"trainName": "broken record without number or time"}
CBE_MAS = {"from": "CBE", "to": "MAS", "count": 3, "trains": [DOCUMENTED, FALLBACK, BROKEN]}
EMPTY = {"count": 0, "trains": []}


def make_transport(routes: dict[str, object], calls: list[httpx.Request] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        result = routes.get(request.url.path, routes.get("*"))
        if isinstance(result, Exception):
            raise result
        if isinstance(result, httpx.Response):
            return result
        if result is None:
            return httpx.Response(404, json={"success": False, "error": {"code": "NOT_FOUND", "message": "Route not found"}})
        return httpx.Response(200, json=envelope(result))
    return httpx.MockTransport(handler)


def client_for(routes, calls=None, cache_seconds=300) -> RailRadarClient:
    return RailRadarClient("https://api.railradar.test", KEY, 5, cache_seconds,
                           transport=make_transport(routes, calls), wall_clock=lambda: FETCHED_AT)


# ---- client ---------------------------------------------------------------------

def test_client_sends_bearer_key_and_unwraps_envelope():
    calls: list[httpx.Request] = []
    fetched = client_for({"/v1/trains/between/CBE/MAS": CBE_MAS}, calls).trains_between("CBE", "MAS", date(2026, 10, 11))
    assert len(fetched.data) == 3 and fetched.fetched_at == FETCHED_AT
    assert calls[0].headers["Authorization"] == f"Bearer {KEY}"
    assert calls[0].url.path == "/v1/trains/between/CBE/MAS" and calls[0].url.params["date"] == "2026-10-11"


def test_client_caches_identical_requests_and_keeps_original_fetch_time():
    calls: list[httpx.Request] = []
    times = iter([FETCHED_AT, datetime(2026, 10, 10, 5, 0, tzinfo=timezone.utc)])
    client = RailRadarClient("https://x", KEY, 5, 300, transport=make_transport({"*": CBE_MAS}, calls),
                             wall_clock=lambda: next(times))
    first_fetch = client.trains_between("CBE", "MAS", date(2026, 10, 11))
    second_fetch = client.trains_between("CBE", "MAS", date(2026, 10, 11))
    assert len(calls) == 1 and second_fetch.fetched_at == first_fetch.fetched_at == FETCHED_AT


def test_bare_list_payload_also_accepted():
    client = client_for({"*": [DOCUMENTED, FALLBACK]})
    assert len(client.trains_between("CBE", "MAS", date(2026, 10, 11)).data) == 2


def test_empty_result_with_zero_count():
    assert client_for({"*": {"from": "CBE", "to": "KPD", "count": 0}}).trains_between(
        "CBE", "KPD", date(2026, 10, 11)).data == []


def test_unknown_payload_shape_is_an_error_not_empty():
    with pytest.raises(ProviderError) as err:
        client_for({"*": {"something": "else"}}).trains_between("CBE", "MAS", date(2026, 10, 11))
    assert err.value.kind is ProviderErrorKind.BAD_RESPONSE


def test_404_route_not_found_is_an_error_not_no_trains():
    """Observed live: wrong paths return 404 {code: NOT_FOUND, message: Route not found}."""
    with pytest.raises(ProviderError) as err:
        client_for({}).trains_between("CBE", "MAS", date(2026, 10, 11))
    assert err.value.kind is ProviderErrorKind.NOT_FOUND and "Route not found" in err.value.message


def test_observed_unauthorized_envelope_is_reported():
    body = {"success": False, "error": {"code": "UNAUTHORIZED", "message": "Invalid API Key"},
            "meta": {"timestamp": "2026-10-10T14:39:41+05:30", "traceId": "x"}}
    with pytest.raises(ProviderError) as err:
        client_for({"*": httpx.Response(401, json=body)}).trains_between("CBE", "MAS", date(2026, 10, 11))
    assert err.value.kind is ProviderErrorKind.AUTH_FAILED
    assert "UNAUTHORIZED: Invalid API Key" in err.value.message and KEY not in err.value.message


@pytest.mark.parametrize("status,kind", [
    (403, ProviderErrorKind.AUTH_FAILED), (429, ProviderErrorKind.RATE_LIMITED), (400, ProviderErrorKind.BAD_REQUEST),
])
def test_http_errors_are_mapped(status, kind):
    client = client_for({"*": httpx.Response(status, json={"success": False, "error": {"message": "nope"}})})
    with pytest.raises(ProviderError) as err:
        client.trains_between("CBE", "MAS", date(2026, 10, 11))
    assert err.value.kind is kind


def test_server_errors_are_retried_once():
    calls: list[httpx.Request] = []
    with pytest.raises(ProviderError) as err:
        client_for({"*": httpx.Response(503)}, calls).trains_between("CBE", "MAS", date(2026, 10, 11))
    assert err.value.kind is ProviderErrorKind.UNAVAILABLE and len(calls) == 2


def test_timeout_is_mapped():
    with pytest.raises(ProviderError) as err:
        client_for({"*": httpx.ReadTimeout("slow")}).trains_between("CBE", "MAS", date(2026, 10, 11))
    assert err.value.kind is ProviderErrorKind.TIMEOUT


def test_success_false_is_an_error():
    client = client_for({"*": httpx.Response(200, json={"success": False, "error": "invalid station"})})
    with pytest.raises(ProviderError) as err:
        client.trains_between("CBE", "MAS", date(2026, 10, 11))
    assert "invalid station" in err.value.message


def test_missing_key_rejected():
    with pytest.raises(ProviderError) as err:
        RailRadarClient("https://x", "")
    assert err.value.kind is ProviderErrorKind.NOT_CONFIGURED


# ---- mapper ---------------------------------------------------------------------

@pytest.fixture
def provenance():
    return RailRadarJourneyProvider(client_for({})).provenance(FETCHED_AT)


def test_map_documented_record(provenance):
    opt = map_train(DOCUMENTED, "CBE", "MAS", date(2026, 10, 11), IST, provenance, {})
    assert opt.legs[0].train_no == "12676" and opt.legs[0].train_name == "Kovai Express"
    assert opt.departure == datetime(2026, 10, 11, 15, 15, tzinfo=IST)
    assert opt.arrival == datetime(2026, 10, 11, 23, 0, tzinfo=IST)  # departure + documented duration
    assert opt.legs[0].from_name == "Coimbatore Jn" and opt.legs[0].to_code == "MAS"
    assert opt.fares == {} and opt.classes == [] and opt.transfers == 0  # nothing invented


def test_map_fallback_record_overnight_with_fares(provenance):
    opt = map_train(FALLBACK, "CBE", "MAS", date(2026, 10, 11), IST, provenance, {})
    assert opt.arrival == datetime(2026, 10, 12, 5, 20, tzinfo=IST)
    assert {c.value for c in opt.classes} == {"SL", "3A", "2A"}  # 1A unsupported -> dropped
    assert {c.value: v for c, v in opt.fares.items()} == {"SL": 315.0, "3A": 830.0}


def test_map_iso_timestamps_without_duration(provenance):
    raw = {"train": {"number": "12671", "name": "Nilgiri"},
           "from": {"departure": "2026-10-11T21:05:00+05:30"}, "to": {"arrival": "2026-10-12T05:15:00+05:30"}}
    opt = map_train(raw, "MAS", "CBE", date(2026, 10, 11), IST, provenance, {})
    assert opt.arrival == datetime(2026, 10, 12, 5, 15, tzinfo=IST) and opt.duration_minutes == 490


def test_map_rejects_arrival_before_departure(provenance):
    raw = {"train": {"number": "1"}, "from": {"departure": "2026-10-11T21:05:00+05:30"},
           "to": {"arrival": "2026-10-11T20:00:00+05:30"}}
    with pytest.raises(MappingError):
        map_train(raw, "MAS", "CBE", date(2026, 10, 11), IST, provenance, {})


def test_map_rejects_incomplete_record(provenance):
    with pytest.raises(MappingError):
        map_train(BROKEN, "CBE", "MAS", date(2026, 10, 11), IST, provenance, {})


@pytest.mark.parametrize("value,expected", [("15:15", time(15, 15)), ("2026-10-11T21:05:00+05:30", time(21, 5)),
                                            (915, time(15, 15)), ("soon", None)])
def test_parse_clock(value, expected):
    assert parse_clock(value) == expected


@pytest.mark.parametrize("value,expected", [(465, 465), ("465", 465), ("07:45", 465), ("7h 45m", 465), ("x", None)])
def test_parse_minutes(value, expected):
    assert parse_minutes(value) == expected


@pytest.mark.parametrize("payload,expected", [
    ({"delayMinutes": 42, "status": "RUNNING", "lastUpdatedAt": "2026-10-10T10:00:00+05:30"}, (42, False)),
    ({"status": "CANCELLED"}, (None, True)),
    ({"delayMinutes": 0, "status": "RUNNING", "exceptions": [{"type": "CANCELLED_PARTIALLY"}]}, (0, True)),
    ({"currentStatus": {"delay": "1h 5m"}}, (65, False)),
    ({"somethingElse": 1}, (None, False)),
])
def test_map_live_status(payload, expected):
    assert map_live_status(payload) == expected


# ---- provider -------------------------------------------------------------------

def test_provider_searches_every_station_pair_and_skips_bad_records():
    calls: list[httpx.Request] = []
    routes = {"/v1/trains/between/CBE/MAS": CBE_MAS, "/v1/trains/between/CBE/MS": EMPTY}
    options = RailRadarJourneyProvider(client_for(routes, calls)).search(["CBE"], ["MAS", "MS"], [date(2026, 10, 11)])
    assert {o.legs[0].train_no for o in options} == {"12676", "12672"}
    assert len(calls) == 2
    assert all(o.provenance.mode is DataMode.LIVE for o in options)
    assert all(o.provenance.as_of == FETCHED_AT.astimezone(IST) for o in options)  # retrieval time, IST


def test_provider_reports_unreadable_format_instead_of_empty():
    provider = RailRadarJourneyProvider(client_for({"*": {"count": 1, "trains": [{"foo": "bar"}]}}))
    with pytest.raises(ProviderError) as err:
        provider.search(["CBE"], ["MAS"], [date(2026, 10, 11)])
    assert err.value.kind is ProviderErrorKind.BAD_RESPONSE


def test_live_mode_never_claims_station_facilities():
    provider = RailRadarJourneyProvider(client_for({}))
    assert provider.station("MAS").facilities == {}
    assert provider.station("NDLS").name == "New Delhi"


# ---- wiring ---------------------------------------------------------------------

def test_live_mode_without_key_never_falls_back_to_demo():
    provider, source, status = build_data_sources(Settings(_env_file=None, RAILWAY_DATA_MODE="railradar"))
    assert provider.data_mode is DataMode.LIVE
    assert status["configured"] is False and status["reason"] == "railradar_api_key_missing"
    with pytest.raises(ProviderError) as err:
        provider.search(["CBE"], ["MAS"], [date(2026, 10, 11)])
    assert err.value.kind is ProviderErrorKind.NOT_CONFIGURED
    with pytest.raises(ProviderError):
        source.events_for_trains([("12676", date(2026, 10, 11))])


def test_railway_data_mode_env_var_selects_railradar(monkeypatch):
    monkeypatch.setenv("RAILWAY_DATA_MODE", "railradar")
    monkeypatch.setenv("RAILRADAR_API_KEY", KEY)
    provider, source, status = build_data_sources(Settings(_env_file=None))
    assert isinstance(provider, RailRadarJourneyProvider) and status["active"] == "railradar"
    assert hasattr(source, "events_for_trains")


def test_legacy_data_provider_name_still_works():
    provider, _, _ = build_data_sources(Settings(_env_file=None, DATA_PROVIDER="railradar", railradar_api_key=KEY))
    assert isinstance(provider, RailRadarJourneyProvider)


def test_unknown_data_mode_is_rejected():
    with pytest.raises(ValueError):
        build_data_sources(Settings(_env_file=None, RAILWAY_DATA_MODE="fake"))


def test_api_key_never_appears_in_settings_repr():
    assert KEY not in repr(Settings(_env_file=None, railradar_api_key=KEY))


# ---- end-to-end through the planner -------------------------------------------------

def live_planner(routes, key: str | None = KEY):
    container = build_container(Settings(_env_file=None, RAILWAY_DATA_MODE="railradar", railradar_api_key=key),
                                clock=FixedClock(FIXED_NOW), use_configured_llm=False)
    if key:
        client = client_for(routes)
        container.provider._client = client  # swap in the mock transport
        container.planner.disruption._source._client = client
    return container.planner


ROUTES = {"/v1/trains/between/CBE/MAS": CBE_MAS, "/v1/trains/between/CBE/MS": EMPTY}


def plan(planner, text):
    sid = planner.create_session(Language.EN).state.session_id
    return sid, planner.handle_message(sid, text, None)


def test_live_planning_flow_with_missing_fares():
    sid, r = plan(live_planner(ROUTES), "from Coimbatore to Chennai on 2026-10-11, 2 passengers, fastest")
    assert r.state.status is S.PRESENTING_RECOMMENDATIONS and r.state.data_mode is DataMode.LIVE
    assert "live RailRadar data" in r.assistant_message
    recs = r.state.recommendations.recommendations
    kovai = next(x for x in recs if x.option.legs[0].train_no == "12676")
    assert kovai.total_fare is None and kovai.selected_class is None
    assert any("Fare not available" in u for u in kovai.unverified)
    assert Cat.LOWEST_COST not in kovai.labels  # never "cheapest" without a fare
    nilgiri = next(x for x in recs if x.option.legs[0].train_no == "12672")
    assert nilgiri.total_fare == 630 and Cat.LOWEST_COST in nilgiri.labels
    assert any("RailRadar" in lim for lim in r.state.recommendations.limitations)
    assert r.state.recommendations.provenance.as_of == FETCHED_AT.astimezone(IST)


def test_no_fares_at_all_with_cost_priority_is_explained():
    routes = {"/v1/trains/between/CBE/MAS": {"count": 1, "trains": [DOCUMENTED]}, "/v1/trains/between/CBE/MS": EMPTY}
    _, r = plan(live_planner(routes), "from Coimbatore to Chennai on 2026-10-11, 1 passenger, cheapest")
    rs = r.state.recommendations
    assert all(Cat.LOWEST_COST not in x.labels for x in rs.recommendations)
    assert any("cannot be compared" in n for n in rs.notes)
    assert not any("Lower fare prioritised" in m for x in rs.recommendations for m in x.preference_matches)


def test_strict_class_without_class_data_is_unverified_not_met():
    routes = {"/v1/trains/between/CBE/MAS": {"count": 1, "trains": [DOCUMENTED]}, "/v1/trains/between/CBE/MS": EMPTY}
    _, r = plan(live_planner(routes), "from Coimbatore to Chennai on 2026-10-11, 1 passenger, AC chair car only, fastest")
    rec = r.state.recommendations.recommendations[0]
    check = next(c for c in rec.hard_constraints if c.name == "travel_class")
    assert check.status.value == "unverified" and rec.fully_compliant is False


def test_live_assistance_is_always_unverified():
    _, r = plan(live_planner(ROUTES), "from Coimbatore to Chennai on 2026-10-11, I need wheelchair assistance, 1 passenger, fastest")
    statuses = {ns.status for rec in r.state.recommendations.recommendations for ns in rec.need_statuses}
    assert statuses == {Verification.UNKNOWN}


def test_strict_budget_with_unknown_fare_is_unverified_not_excluded():
    _, r = plan(live_planner(ROUTES), "from Coimbatore to Chennai on 2026-10-11, 1 passenger, maximum 1000 rupees")
    rs = r.state.recommendations
    assert rs.eligible_count == 2  # unknown fare is not grounds for exclusion
    assert not any("12676" in e.summary for e in rs.excluded)
    assert [x.option.legs[0].train_no for x in rs.recommendations] == ["12672"]  # fully verified option preferred
    assert rs.recommendations[0].fully_compliant


def test_unconfigured_live_mode_reports_error_and_shows_no_journeys():
    _, r = plan(live_planner({}, key=None), "from Coimbatore to Chennai on 2026-10-11, 1 passenger, fastest")
    assert r.state.status is S.ERROR
    assert r.state.recommendations is None  # no demo/fictional journeys
    assert "not configured" in r.assistant_message


def test_outage_is_reported_and_retry_works():
    routes = {"*": httpx.Response(503)}
    planner = live_planner(routes)
    sid, r = plan(planner, "from Coimbatore to Chennai on 2026-10-11, 1 passenger, fastest")
    assert r.state.status is S.ERROR and r.state.recommendations is None
    assert "Live train data is unavailable" in r.assistant_message
    assert r.state.journey.origin.id == "coimbatore"  # details kept
    routes.clear()
    routes.update(ROUTES)
    assert planner.handle_message(sid, "show options", None).state.status is S.PRESENTING_RECOMMENDATIONS


def test_live_delay_reassessment():
    routes = {**ROUTES, "/v1/trains/12676/live": {"delayMinutes": 0}, "/v1/trains/12672/live": {"delayMinutes": 200}}
    planner = live_planner(routes)
    sid, _ = plan(planner, "from Coimbatore to Chennai, reach before 8 am on 2026-10-12, 1 passenger, fastest")
    nilgiri = next(x for x in planner.get(sid).recommendations.recommendations if x.option.legs[0].train_no == "12672")
    planner.select(sid, nilgiri.option.option_id)
    info = planner.reassess(sid, None).state.reassessment
    assert info.simulated is False and "Live (RailRadar)" in info.event_label
    assert info.original_still_valid is False  # 05:20 + 200 min = 08:40, after the 08:00 deadline


def test_no_live_delays_reported():
    routes = {**ROUTES, "/v1/trains/12676/live": {"delayMinutes": 0}, "/v1/trains/12672/live": {"delayMinutes": 0}}
    planner = live_planner(routes)
    sid, _ = plan(planner, "from Coimbatore to Chennai on 2026-10-11, 1 passenger, fastest")
    with pytest.raises(PlannerError) as err:
        planner.reassess(sid, None)
    assert err.value.code == "no_relevant_event" and "live status" in err.value.message


def test_reassess_outage_maps_to_503():
    routes = {**ROUTES, "/v1/trains/12676/live": httpx.ReadTimeout("slow"), "/v1/trains/12672/live": httpx.ReadTimeout("slow")}
    planner = live_planner(routes)
    sid, _ = plan(planner, "from Coimbatore to Chennai on 2026-10-11, 1 passenger, fastest")
    with pytest.raises(PlannerError) as err:
        planner.reassess(sid, None)
    assert err.value.code == "data_unavailable" and err.value.http_status == 503


def test_api_health_and_messages_label_live_mode():
    from fastapi.testclient import TestClient
    from app.main import create_app
    settings = Settings(_env_file=None, RAILWAY_DATA_MODE="railradar", railradar_api_key=KEY)
    container = build_container(settings, clock=FixedClock(FIXED_NOW), use_configured_llm=False)
    container.provider._client = client_for(ROUTES)
    api = TestClient(create_app(settings, container))
    health = api.get("/api/health").json()
    assert health["data_mode"] == "live" and health["data_provider"]["active"] == "railradar"
    assert KEY not in str(health)
    created = api.post("/api/planner/sessions", json={}).json()
    sid = created["session_id"]
    api.headers["X-Session-Token"] = created["session_token"]
    body = api.post(f"/api/planner/sessions/{sid}/messages",
                    json={"message": "from Coimbatore to Chennai on 2026-10-11, 1 passenger, fastest"}).json()
    assert body["data_mode"] == "live" and body["data_notice"].startswith("LIVE DATA from RailRadar")
    prov = body["state"]["recommendations"]["provenance"]
    assert prov["source"].startswith("RailRadar") and prov["as_of"].startswith("2026-10-10T10:00")


# ---- records OBSERVED from the live API (2026-10-10, date=2026-10-12) ------------------
OBSERVED_OVERNIGHT = {
    "train": {"number": "22640", "name": "Alleppey - Chennai Central SF Exp", "type": "Superfast Express",
              "runDays": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], "runningDaysBitmap": 127},
    "from": {"code": "CBE", "name": "Coimbatore Jn", "city": "Coimbatore", "departure": "21:35", "day": 1, "sequence": 9},
    "to": {"code": "MAS", "name": "MGR Chennai Central", "city": "Chennai", "arrival": "05:15", "day": 2, "sequence": 30},
    "distance": 494, "duration": 460, "totalHaltsBetween": 9,
}
OBSERVED_DAY2_START = {
    "train": {"number": "22208", "name": "Thiruvananthapuram Chennai AC SF Exp", "type": "Superfast Express",
              "runDays": ["wed", "sun"], "runningDaysBitmap": 68},
    "from": {"code": "CBE", "name": "Coimbatore Jn", "city": "Coimbatore", "departure": "02:45", "day": 2, "sequence": 9},
    "to": {"code": "MAS", "name": "MGR Chennai Central", "city": "Chennai", "arrival": "10:25", "day": 2, "sequence": 20},
    "distance": 494, "duration": 460, "totalHaltsBetween": 6,
}


def test_observed_overnight_record(provenance):
    opt = map_train(OBSERVED_OVERNIGHT, "CBE", "MAS", date(2026, 10, 12), IST, provenance, {})
    assert opt.departure == datetime(2026, 10, 12, 21, 35, tzinfo=IST)
    assert opt.arrival == datetime(2026, 10, 13, 5, 15, tzinfo=IST)
    assert opt.legs[0].to_name == "MGR Chennai Central"


def test_observed_day_offset_used_when_duration_missing(provenance):
    raw = {**OBSERVED_OVERNIGHT}
    raw.pop("duration")
    opt = map_train(raw, "CBE", "MAS", date(2026, 10, 12), IST, provenance, {})
    assert opt.arrival == datetime(2026, 10, 13, 5, 15, tzinfo=IST)  # to.day - from.day = 1


def test_observed_train_starting_previous_day_boards_on_query_date(provenance):
    """22208 starts Sun (runDays wed/sun), reaches CBE on run day 2; RailRadar lists it for Monday."""
    opt = map_train(OBSERVED_DAY2_START, "CBE", "MAS", date(2026, 10, 12), IST, provenance, {})
    assert opt.departure == datetime(2026, 10, 12, 2, 45, tzinfo=IST)
    assert opt.arrival == datetime(2026, 10, 12, 10, 25, tzinfo=IST)


@pytest.mark.parametrize("payload", [
    {"trainNumber": "12696", "trainName": "x", "startDate": "2026-10-10", "isLive": True, "trackingMode": "x",
     "status": "RUNNING", "delayMinutes": 0, "lastUpdatedAt": "2026-10-10T15:00:00+05:30",
     "currentLocation": {}, "nextHalt": {}, "route": []},
])
def test_observed_live_status_fields(payload):
    assert map_live_status(payload) == (0, False)


def test_local_rate_limit_fails_fast_with_wait_time():
    clock = {"t": 1000.0}
    calls: list[httpx.Request] = []
    client = RailRadarClient("https://x", KEY, 5, 0, transport=make_transport({"*": CBE_MAS}, calls),
                             monotonic=lambda: clock["t"], requests_per_minute=2)
    client.trains_between("CBE", "MAS", date(2026, 10, 11))
    clock["t"] += 10
    client.trains_between("CBE", "MS", date(2026, 10, 11))
    with pytest.raises(ProviderError) as err:
        client.trains_between("CBE", "SBC", date(2026, 10, 11))
    assert err.value.kind is ProviderErrorKind.RATE_LIMITED and "try again in 50 s" in err.value.message
    assert len(calls) == 2  # the third request never reached RailRadar
    clock["t"] += 51
    client.trains_between("CBE", "SBC", date(2026, 10, 11))  # window has moved on
    assert len(calls) == 3


def test_observed_429_body_is_reported():
    body = {"success": False, "error": {"code": "TOO_MANY_REQUESTS",
                                        "message": "Rate limit exceeded. Maximum 10 requests per minute."}}
    with pytest.raises(ProviderError) as err:
        client_for({"*": httpx.Response(429, json=body)}).trains_between("CBE", "MAS", date(2026, 10, 11))
    assert err.value.kind is ProviderErrorKind.RATE_LIMITED and "Maximum 10 requests per minute" in err.value.message


def test_missing_fare_does_not_trigger_assistance_message():
    """Regression (seen live 2026-10-10): 'Assistance is requested…' appeared when nobody asked for it."""
    _, r = plan(live_planner(ROUTES), "from Coimbatore to Chennai on 2026-10-11, 1 passenger, fastest")
    assert "Assistance" not in r.assistant_message
    _, r = plan(live_planner(ROUTES), "from Coimbatore to Chennai on 2026-10-11, 1 passenger, fastest, I need assistance")
    assert "Assistance is requested but not verified" in r.assistant_message


def test_up_to_three_real_options_shown_when_categories_collapse():
    """Seen live: 5 eligible trains but only 1 card (best == fastest, no fares). Fill to 3, honestly labelled."""
    routes = {"/v1/trains/between/CBE/MAS": {"count": 3, "trains": [DOCUMENTED, OBSERVED_OVERNIGHT, OBSERVED_DAY2_START]},
              "/v1/trains/between/CBE/MS": EMPTY}
    _, r = plan(live_planner(routes), "from Coimbatore to Chennai on 2026-10-12, 1 passenger, fastest")
    recs = r.state.recommendations.recommendations
    assert len(recs) == 3 and len({x.option.option_id for x in recs}) == 3
    unlabeled = [x for x in recs if not x.labels]
    assert unlabeled and all(x.explanation.startswith("Also eligible") for x in unlabeled)
    assert all(x.total_fare is None for x in recs)
