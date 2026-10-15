"""Live boards, schedules and running status (api/live.py, providers/live_source.py). No network: RailRadar is
served by httpx.MockTransport and the quota gate is a switchable fake."""

import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.clock import FixedClock
from app.config import Settings
from app.container import build_container, build_live_source
from app.domain.enums import DataMode
from app.main import create_app
from app.providers.base import StationRecord
from app.providers.demo import DemoJourneyProvider
from app.providers.live_source import (
    DemoLiveSource,
    RailRadarLiveSource,
    UnavailableLiveSource,
    UnknownStation,
)
from app.providers.railradar import load_catalogue
from app.providers.railradar_client import RailRadarClient
from app.providers.railradar_shared import InMemoryResponseCache, QuotaDecision
from app.providers.station_directory import StationDirectory
from tests.conftest import FIXED_NOW, IST

KEY = "rr_test_key_not_real"
FETCHED_AT = datetime(2026, 10, 10, 4, 15, tzinfo=timezone.utc)  # 09:45 IST, before FIXED_NOW (10:00 IST)
DAY = FIXED_NOW.date()


class SwitchableQuota:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed

    async def acquire(self) -> QuotaDecision:
        return QuotaDecision(True) if self.allowed else QuotaDecision(False, 30)


def train(no: str, name: str, frm: str, dep: str, to: str, duration: int = 300) -> dict:
    return {"train": {"number": no, "name": name}, "from": {"code": frm, "departure": dep},
            "to": {"code": to, "arrival": "23:00"}, "duration": duration}


# CBE board, 10:00-12:00 IST: 12676 (10:30, to MAS and ED), 12244 (11:00, to ED); 22666 at 13:00 is outside the
# window; 16616 leaves from another station of the pair (PTJ) and is not a CBE departure.
CBE_MAS = {"count": 2, "trains": [train("12676", "Kovai Express", "CBE", "10:30", "MAS"),
                                  train("22666", "Uday Express", "CBE", "13:00", "MAS")]}
CBE_ED = {"count": 3, "trains": [train("12676", "Kovai Express", "CBE", "10:30", "ED", 60),
                                 train("12244", "Shatabdi", "CBE", "11:00", "ED", 50),
                                 train("16616", "Chemmozhi", "PTJ", "10:45", "ED", 70)]}
LIVE_12676 = {"trainNumber": "12676", "status": "RUNNING", "delayMinutes": 12}

# Deterministic neighbours: CBE's two nearest other-city stations are ED then MAS; MS shares MAS's city.
STATIONS = [StationRecord(code=c, name=n, city=city, aliases=[], facilities={})
            for c, n, city in [("CBE", "Coimbatore Jn", "coimbatore"), ("ED", "Erode Jn", "erode"),
                               ("MAS", "Chennai Central", "chennai"), ("MS", "Chennai Egmore", "chennai"),
                               ("XYZ", "Nowhere", "nowhere")]]
COORDS = {"CBE": (11.0, 76.96), "ED": (11.34, 77.72), "MAS": (13.07, 80.26), "MS": (13.08, 80.27)}


def directory() -> StationDirectory:
    return StationDirectory(STATIONS, COORDS)


def transport(routes: dict, calls: list | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request.url.path)
        result = routes.get(request.url.path)
        if isinstance(result, httpx.Response):
            return result
        if result is None:
            return httpx.Response(404, json={"success": False, "error": {"code": "NOT_FOUND", "message": "nope"}})
        return httpx.Response(200, json={"success": True, "data": result})
    return httpx.MockTransport(handler)


def railradar_source(routes, quota=None, calls=None, cache=None, clock_seconds=None, neighbours=2, status_limit=3):
    now = {"t": 1_000_000.0} if clock_seconds is None else clock_seconds
    client = RailRadarClient("https://api.railradar.test", KEY, 5, 300, transport=transport(routes, calls),
                             wall_clock=lambda: FETCHED_AT, quota=quota or SwitchableQuota(),
                             cache=cache or InMemoryResponseCache(21_600, clock=lambda: now["t"]),
                             clock=lambda: now["t"])
    return RailRadarLiveSource(client, directory(), FixedClock(FIXED_NOW), neighbours=neighbours,
                               status_limit=status_limit)


ROUTES = {"/v1/trains/between/CBE/ED": CBE_ED, "/v1/trains/between/CBE/MAS": CBE_MAS,
          "/v1/trains/12676/live": LIVE_12676}


# ---- directory ----------------------------------------------------------------------------------------------

def test_neighbours_are_nearest_other_city_stations_with_coordinates():
    assert [p.code for p in directory().neighbours("CBE", 3)] == ["ED", "MAS"]  # MS is skipped: same city as MAS
    assert [p.code for p in directory().neighbours("MAS", 3)] == ["ED", "CBE"]  # MS is the origin's own city
    assert directory().neighbours("XYZ", 3) == []  # no coordinates


def test_directory_search_and_nearest():
    d = directory()
    assert [p.code for p in d.search("chennai")] == ["MAS", "MS"]
    assert d.search("CBE")[0].code == "CBE"
    point, km = d.nearest(13.07, 80.26)
    assert point.code == "MAS" and km < 1


def test_real_catalogue_has_coordinates_for_the_main_stations():
    _, stations = load_catalogue()
    d = StationDirectory(list(stations.values()))
    for code in ("MAS", "SBC", "CBE", "NDLS", "HWH"):
        assert d.get(code).latitude is not None, code
    assert d.neighbours("MAS", 3)


# ---- RailRadar board ----------------------------------------------------------------------------------------

def test_board_lists_window_departures_from_cached_trains_between_with_live_status():
    calls: list[str] = []
    board = railradar_source(ROUTES, calls=calls).departures("cbe", 2)
    assert board.provenance.mode is DataMode.CACHED
    assert board.provenance.as_of == FETCHED_AT.astimezone(IST)
    assert board.complete and board.reason is None
    assert [d.train_no for d in board.departures] == ["12676", "12244"]
    kovai = board.departures[0]
    assert [t.code for t in kovai.towards] == ["ED", "MAS"]
    assert kovai.scheduled_departure == datetime(2026, 10, 10, 10, 30, tzinfo=IST)
    assert kovai.delay_minutes == 12 and kovai.cancelled is False
    assert board.departures[1].delay_minutes is None  # live status 404 -> unknown, not "on time"
    assert [n.code for n in board.neighbours_checked] == ["ED", "MAS"]
    assert "/v1/trains/22666/live" not in calls  # outside the window, never queried


def test_cache_gives_cached_without_calling_railradar():
    quota = SwitchableQuota()
    calls: list[str] = []
    source = railradar_source(ROUTES, quota=quota, calls=calls)
    source.departures("CBE", 2)
    first_calls = len(calls)
    quota.allowed = False  # quota exhausted: the fresh cache still serves the board
    board = source.departures("CBE", 2)
    assert len(calls) == first_calls
    assert board.provenance.mode is DataMode.CACHED and len(board.departures) == 2
    assert board.provenance.as_of == FETCHED_AT.astimezone(IST)


def test_quota_exhausted_without_cache_gives_unavailable_with_reason():
    calls: list[str] = []
    board = railradar_source(ROUTES, quota=SwitchableQuota(False), calls=calls).departures("CBE", 2)
    assert calls == []
    assert board.provenance.mode is DataMode.UNAVAILABLE
    assert board.departures == [] and board.complete is False
    assert "quota" in board.reason and board.provenance.note == board.reason


def test_quota_exhausted_with_expired_cache_gives_stale():
    clock = {"t": 1_000_000.0}
    quota = SwitchableQuota()
    source = railradar_source(ROUTES, quota=quota, clock_seconds=clock)
    source.departures("CBE", 2)
    clock["t"] += 3600  # past the 300 s freshness, within the stale window
    quota.allowed = False
    board = source.departures("CBE", 2)
    assert board.provenance.mode is DataMode.STALE and board.provenance.note.startswith("STALE")
    assert len(board.departures) == 2


def test_upstream_failure_gives_unavailable_without_leaking_upstream_text():
    secret = "internal stack trace from upstream"
    routes = {"/v1/trains/between/CBE/ED": httpx.Response(500, json={"success": False, "error": secret}),
              "/v1/trains/between/CBE/MAS": httpx.Response(503, text=secret)}
    board = railradar_source(routes).departures("CBE", 2)
    assert board.provenance.mode is DataMode.UNAVAILABLE
    assert board.reason == "The live data provider could not be reached."
    assert secret not in board.model_dump_json()


def test_partial_failure_is_marked_incomplete():
    routes = {**ROUTES, "/v1/trains/between/CBE/MAS": httpx.Response(500, json={})}
    board = railradar_source(routes).departures("CBE", 2)
    assert board.provenance.mode is DataMode.CACHED and board.complete is False
    assert board.provenance.note.startswith("INCOMPLETE")
    assert [d.train_no for d in board.departures] == ["12676", "12244"]


def test_status_limit_caps_live_status_calls():
    calls: list[str] = []
    railradar_source(ROUTES, calls=calls, status_limit=0).departures("CBE", 2)
    assert not any(c.endswith("/live") for c in calls)


def test_unknown_station_raises_and_station_without_neighbours_is_unavailable():
    source = railradar_source(ROUTES)
    with pytest.raises(UnknownStation):
        source.departures("QQQ", 2)
    board = source.departures("XYZ", 2)
    assert board.provenance.mode is DataMode.UNAVAILABLE and "neighbouring" in board.reason


def test_window_is_clipped_at_midnight():
    late = FixedClock(datetime(2026, 10, 10, 23, 0, tzinfo=IST))
    source = DemoLiveSource(directory(), late)
    board = source.departures("CBE", 4)
    assert board.window_end == datetime(2026, 10, 11, 0, 0, tzinfo=IST)


# ---- schedule and running status ----------------------------------------------------------------------------

def test_railradar_schedule_is_unavailable_not_guessed():
    schedule = railradar_source(ROUTES).schedule("12676")
    assert schedule.provenance.mode is DataMode.UNAVAILABLE and schedule.stops == []
    assert "not supported by the live data provider" in schedule.reason


def test_railradar_live_status_is_live_and_quota_gives_unavailable():
    status = railradar_source(ROUTES).live_status("12676", DAY)
    assert status.provenance.mode is DataMode.LIVE and status.delay_minutes == 12 and status.cancelled is False
    blocked = railradar_source(ROUTES, quota=SwitchableQuota(False)).live_status("12676", DAY)
    assert blocked.provenance.mode is DataMode.UNAVAILABLE and "quota" in blocked.reason


# ---- demo and production ------------------------------------------------------------------------------------

EVENING = FixedClock(datetime(2026, 10, 10, 20, 30, tzinfo=IST))  # CBE has night departures in the demo data


def demo_source() -> DemoLiveSource:
    return DemoLiveSource(StationDirectory(DemoJourneyProvider().stations()), EVENING)


def test_demo_source_is_labelled_demo():
    board = demo_source().departures("CBE", 4)
    assert board.provenance.mode is DataMode.DEMO and board.departures
    assert all(EVENING.now() <= d.scheduled_departure <= EVENING.now() + timedelta(hours=4) for d in board.departures)
    assert demo_source().schedule("D101").provenance.mode is DataMode.DEMO
    status = demo_source().live_status("D101", DAY)
    assert status.provenance.mode is DataMode.DEMO and status.delay_minutes == 25
    assert demo_source().live_status("D999", DAY).provenance.mode is DataMode.UNAVAILABLE


def test_demo_refused_in_production():
    settings = Settings(_env_file=None, APP_ENV="production", RAILWAY_DATA_MODE="demo")
    live = build_live_source(settings, DemoJourneyProvider(), FixedClock(FIXED_NOW))
    assert isinstance(live, UnavailableLiveSource)
    board = live.departures("MAS", 2)
    assert board.provenance.mode is DataMode.UNAVAILABLE and "production" in board.reason
    assert live.live_status("D101", DAY).provenance.mode is DataMode.UNAVAILABLE


def test_container_builds_demo_outside_production_and_unavailable_without_key():
    demo = build_container(Settings(_env_file=None), clock=FixedClock(FIXED_NOW), use_configured_llm=False)
    assert isinstance(demo.live, DemoLiveSource)
    keyless = build_container(Settings(_env_file=None, RAILWAY_DATA_MODE="railradar"), clock=FixedClock(FIXED_NOW),
                              use_configured_llm=False)
    assert isinstance(keyless.live, UnavailableLiveSource)
    assert "not configured" in keyless.live.departures("MAS", 2).reason
    live = build_container(Settings(_env_file=None, RAILWAY_DATA_MODE="railradar", railradar_api_key=KEY),
                           clock=FixedClock(FIXED_NOW), use_configured_llm=False)
    assert isinstance(live.live, RailRadarLiveSource)
    assert live.live._client is live.provider.client  # one shared quota and cache


# ---- API ----------------------------------------------------------------------------------------------------

@pytest.fixture
def api() -> TestClient:
    settings = Settings(_env_file=None)
    container = build_container(settings, clock=EVENING, use_configured_llm=False)
    return TestClient(create_app(settings, container))


def test_departures_endpoint_carries_provenance(api):
    body = api.get("/api/live/stations/CBE/departures?hours=4").json()
    assert body["provenance"]["mode"] == "demo" and body["station"]["code"] == "CBE"
    assert {"mode", "source", "as_of", "note"} <= set(body["provenance"])
    assert body["departures"] and "train_no" in body["departures"][0]


def test_unknown_station_is_404_envelope_and_bad_input_is_422(api):
    res = api.get("/api/live/stations/QQQ/departures")
    assert res.status_code == 404 and res.json()["error"]["code"] == "unknown_station"
    assert api.get("/api/live/stations/MA$/departures").status_code in (404, 422)
    assert api.get("/api/live/stations/MAS/departures?hours=9").status_code == 422
    assert api.get("/api/live/trains/12%2F..%2Fx/status").status_code in (404, 422)


def test_schedule_status_search_nearest_carry_provenance(api):
    assert api.get("/api/live/trains/D101/schedule").json()["provenance"]["mode"] == "demo"
    status = api.get("/api/live/trains/D101/status").json()
    assert status["provenance"]["mode"] == "demo" and status["run_date"] == DAY.isoformat()
    assert api.get("/api/live/trains/D101/status?date=2026-12-01").status_code == 422
    search = api.get("/api/live/stations/search?q=chennai").json()
    assert {r["code"] for r in search["results"]} == {"MAS", "MS"} and search["provenance"]["mode"] == "demo"
    nearest = api.get("/api/live/stations/nearest?lat=13.08&lon=80.27").json()
    assert nearest["station"]["code"] == "MAS" and "provenance" in nearest


def test_rake_position_moved_under_api(api):
    assert api.get("/api/trains/rake-position?coach_composition=ENG-A1-B1-SLR&target_coach=B1").status_code == 200


@pytest.mark.parametrize("path", ["/stations/MAS/live", "/stations/search?q=MAS", "/stations/nearest?lat=1&lon=1",
                                  "/trains/12658/schedule", "/plan/journey?from_station=SBC&to_station=MAS",
                                  "/trains/rake-position?coach_composition=ENG", "/predict/delay?train_number=1",
                                  "/stations/MAS/navigation"])
def test_non_api_alias_paths_are_gone(api, path):
    assert api.get(path).status_code == 404


def test_no_mock_data_left_in_the_app():
    app_dir = Path(__file__).resolve().parents[1] / "app"
    offenders = [p for p in app_dir.rglob("*.py") if "MOCK_" in p.read_text(encoding="utf-8")]
    assert offenders == []


def test_api_reports_unavailable_board_in_production_demo():
    # Production demo: the live source refuses rather than serving simulated departures.
    settings = Settings(_env_file=None, APP_ENV="production", RAILWAY_DATA_MODE="demo",
                        session_signing_key="k" * 48)
    container = build_container(settings, clock=FixedClock(FIXED_NOW), use_configured_llm=False)
    body = TestClient(create_app(settings, container)).get("/api/live/stations/MAS/departures").json()
    assert body["provenance"]["mode"] == "unavailable" and body["departures"] == []


_ = (subprocess, date)  # keep imports explicit for readers of the fixtures above
