"""NTES through the unofficial ntes-client (providers/ntes*.py, NtesLiveSource, container, readiness). No network:
the synchronous client is tests/ntes_fixture.FakeNTES, built from shapes observed live."""

import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.clock import FixedClock
from app.config import Settings
from app.container import build_container
from app.domain.enums import DataMode, TravelClass
from app.journey.provider_adapter import ProviderJourneyAdapter
from app.main import create_app
from app.providers import ntes_client
from app.providers.errors import ProviderError, ProviderErrorKind
from app.providers.live_source import REASONS, NtesLiveSource
from app.providers.ntes import NtesDisruptionSource, NtesJourneyProvider
from app.providers.ntes_client import SOURCE, NtesAlert, NtesClient, map_error, ntes_date
from app.providers.ntes_mapper import parse_board_time, parse_delay, runs_on
from app.providers.railradar_shared import QuotaDecision, RedisQuotaGate
from app.providers.station_directory import StationDirectory
from tests.conftest import FIXED_NOW, IST
from tests.ntes_fixture import (LIVE_12658, LIVE_LATE, MAS_BOARD, MAS_SBC, SCHEDULE_12658, FakeNTES, NTESCryptoError,
                                NTESError)

SUNDAY = date(2026, 10, 11)
FETCHED_AT = datetime(2026, 10, 10, 4, 25, tzinfo=timezone.utc)  # 09:55 IST
BOARD_NOW = datetime(2026, 10, 17, 2, 50, tzinfo=IST)
CHENNAI, BENGALURU = ["MAS", "MS"], ["SBC", "BNC", "YPR"]
UPSTREAM_DOWN = NTESError("request failed: HTTPSConnectionPool(host='enquiry.indianrail.gov.in', port=443): "
                          "Max retries exceeded (Caused by SSLError('handshake failure'))")


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


class Quota:
    def __init__(self, free: int = 20) -> None:
        self.free = free

    async def acquire(self) -> QuotaDecision:
        if self.free <= 0:
            return QuotaDecision(False, 30)
        self.free -= 1
        return QuotaDecision(True)

    async def remaining(self) -> int:
        return max(self.free, 0)


def between_for_pair(frm, to, _type):
    return MAS_SBC if (frm, to) == ("MAS", "SBC") else {**MAS_SBC, "Trains": []}


def gateway(fake: FakeNTES, quota: Quota | None = None, clock: Clock | None = None) -> NtesClient:
    return NtesClient(factory=lambda: fake, quota=quota or Quota(), clock=clock or Clock(),
                      wall_clock=lambda: FETCHED_AT, cache_seconds=300)


def provider(fake: FakeNTES, **kw) -> NtesJourneyProvider:
    return NtesJourneyProvider(gateway(fake, **kw), "Asia/Kolkata")


def live(fake: FakeNTES, now: datetime = BOARD_NOW, **kw) -> NtesLiveSource:
    p = provider(fake, **kw)
    return NtesLiveSource(p.client, StationDirectory(p.stations()), FixedClock(now))


# --- journey search ------------------------------------------------------------------------------------------------

def test_search_maps_ntes_trains_to_options_without_fares():
    fake = FakeNTES({"trains_between": between_for_pair})
    options = provider(fake).search(CHENNAI, BENGALURU, [SUNDAY])
    assert [o.legs[0].train_no for o in options] == ["20607", "12007", "12657"]
    mail = options[-1]
    leg = mail.legs[0]
    assert mail.option_id == "NTES-12657-MAS-SBC@2026-10-11"
    assert leg.departure == datetime(2026, 10, 11, 22, 50, tzinfo=IST)
    assert leg.arrival == datetime(2026, 10, 12, 4, 35, tzinfo=IST) and mail.duration_minutes == 345
    assert (leg.from_name, leg.to_name) == ("Chennai Central", "KSR Bengaluru")  # catalogue names, not NTES's
    assert mail.fares == {} and TravelClass.SL in mail.classes and TravelClass.THREE_A in mail.classes
    assert options[0].classes == [TravelClass.CC]
    prov = mail.provenance
    assert prov.mode is DataMode.LIVE and prov.source == "NTES (unofficial client)" == SOURCE
    assert prov.as_of == FETCHED_AT.astimezone(IST) and "unofficial" in prov.note
    # Six pairs asked, one per pair (not per date); pnr_status never touched.
    assert {c[0] for c in fake.calls} == {"trains_between"} and len(fake.calls) == 6


def test_search_keeps_only_requested_stations_and_days_of_run():
    fake = FakeNTES({"trains_between": between_for_pair})
    p = provider(fake)
    trains = {o.legs[0].train_no for o in p.search(CHENNAI, BENGALURU, [SUNDAY, date(2026, 10, 14)])}
    # 22601 goes to YNK and 15228 leaves from PER: other stations of NTES's groups. 12292 runs on Saturdays only.
    assert trains == {"20607", "12007", "12657"}
    wednesday = [o for o in p.search(CHENNAI, BENGALURU, [date(2026, 10, 14)])]
    assert {o.legs[0].train_no for o in wednesday} == {"12007", "12657"}  # 20607 does not run on Wednesdays


def test_runs_on_parses_ntes_days_and_refuses_to_guess():
    assert runs_on("Daily", SUNDAY) is True
    assert runs_on("Mon,tue,thu,fri,sat,sun", SUNDAY) is True
    assert runs_on("Tue,wed,thu", SUNDAY) is False
    assert runs_on("Alt days", SUNDAY) is None and runs_on("", SUNDAY) is None


def test_goal_planner_adapter_gets_ntes_candidates_with_no_fare():
    fake = FakeNTES({"trains_between": between_for_pair})
    result = ProviderJourneyAdapter(provider(fake), "Asia/Kolkata", FixedClock(FIXED_NOW)).search(
        CHENNAI, BENGALURU, [SUNDAY])
    assert result.error is None and len(result.candidates) == 3
    assert all(c.fares == {} for c in result.candidates)
    assert result.provenance.source == SOURCE and result.provenance.mode is DataMode.LIVE


def test_fan_out_is_capped_by_the_free_budget_primary_stations_first_and_labelled_partial():
    fake = FakeNTES({"trains_between": between_for_pair})
    options = provider(fake, quota=Quota(free=1)).search(CHENNAI, BENGALURU, [SUNDAY])
    assert fake.calls == [("trains_between", "MAS", "SBC", "XXX")]  # the primary pair only
    assert options and all(o.provenance.note.startswith("PARTIAL:") for o in options)
    assert "MS to SBC" in options[0].provenance.note


def test_search_with_no_budget_and_nothing_cached_is_rate_limited_not_empty():
    fake = FakeNTES({"trains_between": between_for_pair})
    with pytest.raises(ProviderError) as err:
        provider(fake, quota=Quota(free=0)).search(CHENNAI, BENGALURU, [SUNDAY])
    assert err.value.kind is ProviderErrorKind.RATE_LIMITED and fake.calls == []


def test_cached_then_stale_when_the_budget_is_used_up():
    fake = FakeNTES({"trains_between": between_for_pair})
    quota, clock = Quota(free=20), Clock()
    p = provider(fake, quota=quota, clock=clock)
    first = p.search(["MAS"], ["SBC"], [SUNDAY])
    assert first[0].provenance.mode is DataMode.LIVE
    again = p.search(["MAS"], ["SBC"], [SUNDAY])
    assert again[0].provenance.mode is DataMode.CACHED and again[0].provenance.note.startswith("CACHED:")
    assert len(fake.calls) == 1
    clock.t += 301  # the cached copy is no longer fresh
    quota.free = 0  # and the budget refuses a new call
    stale = p.search(["MAS"], ["SBC"], [SUNDAY])
    assert stale[0].provenance.mode is DataMode.STALE and stale[0].provenance.note.startswith("STALE:")
    assert stale[0].provenance.as_of == FETCHED_AT.astimezone(IST) and len(fake.calls) == 1


def test_upstream_failure_serves_stale_when_cached_else_unavailable():
    clock = Clock()
    fake = FakeNTES({"trains_between": between_for_pair})
    p = provider(fake, clock=clock)
    p.search(["MAS"], ["SBC"], [SUNDAY])
    clock.t += 301
    fake.responses["trains_between"] = UPSTREAM_DOWN
    assert p.search(["MAS"], ["SBC"], [SUNDAY])[0].provenance.mode is DataMode.STALE
    with pytest.raises(ProviderError) as err:
        provider(FakeNTES({"trains_between": UPSTREAM_DOWN})).search(["MAS"], ["SBC"], [SUNDAY])
    assert err.value.kind is ProviderErrorKind.UNAVAILABLE
    assert "HTTPSConnectionPool" not in err.value.message and "indianrail" not in err.value.message


def test_upstream_error_gives_unavailable_provenance_to_the_goal_planner():
    adapter = ProviderJourneyAdapter(provider(FakeNTES({"trains_between": UPSTREAM_DOWN})), "Asia/Kolkata",
                                     FixedClock(FIXED_NOW))
    result = adapter.search(["MAS"], ["SBC"], [SUNDAY])
    assert result.candidates == [] and result.error == "unavailable"
    assert result.provenance.mode is DataMode.UNAVAILABLE and result.provenance.source == SOURCE
    assert "indianrail" not in result.provenance.note


def test_no_trains_alert_is_an_answer_not_a_failure():
    options = provider(FakeNTES({})).search(["MAS"], ["SBC"], [SUNDAY])  # every call: "No Data Found" alert
    assert options == []


def test_import_failure_gives_not_configured_and_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "ntes", None)  # `from ntes import NTESClient` now raises ImportError
    client = NtesClient(quota=Quota(), clock=Clock())
    p = NtesJourneyProvider(client)
    with pytest.raises(ProviderError) as err:
        p.search(["MAS"], ["SBC"], [SUNDAY])
    assert err.value.kind is ProviderErrorKind.NOT_CONFIGURED
    src = NtesLiveSource(client, StationDirectory(p.stations()), FixedClock(BOARD_NOW))
    board = src.departures("MAS", 2)
    assert board.provenance.mode is DataMode.UNAVAILABLE and board.reason == REASONS[ProviderErrorKind.NOT_CONFIGURED]
    assert board.provenance.source == SOURCE
    assert src.schedule("12658").provenance.mode is DataMode.UNAVAILABLE
    assert src.live_status("12658", SUNDAY).provenance.mode is DataMode.UNAVAILABLE


# --- live boards, schedules, running status ------------------------------------------------------------------------

def test_station_board_maps_ntes_departures():
    fake = FakeNTES({"station_live": MAS_BOARD})
    board = live(fake).departures("MAS", 4)
    assert fake.calls == [("station_live", "MAS", 4)]
    assert [d.train_no for d in board.departures] == ["12511", "20607", "12007", "12675"]
    late = board.departures[0]
    assert late.scheduled_departure == datetime(2026, 10, 16, 23, 10, tzinfo=IST)
    assert late.delay_minutes == 227 and late.cancelled is False
    assert late.towards[0].code == "TVCN" and late.towards[0].name == "Thiruvananthapuram North"
    assert board.departures[1].delay_minutes == 0
    assert board.departures[2].cancelled is True and board.departures[2].delay_minutes is None
    assert board.departures[3].towards[0].name == "Coimbatore Junction"  # the catalogue's name for CBE
    assert board.complete is True and board.station.code == "MAS"
    assert board.provenance.mode is DataMode.LIVE and board.provenance.source == SOURCE
    assert board.provenance.as_of == FETCHED_AT.astimezone(IST)
    assert all(d.status_as_of == FETCHED_AT.astimezone(IST) for d in board.departures)


def test_station_board_window_follows_the_hours_asked():
    fake = FakeNTES({"station_live": MAS_BOARD})
    board = live(fake).departures("MAS", 2)
    assert fake.calls == [("station_live", "MAS", 2)]
    assert [d.train_no for d in board.departures] == ["12511"]  # 05:50 is outside 02:50-04:50


def test_board_reuses_a_recent_copy_and_goes_stale_when_ntes_fails():
    clock = Clock()
    fake = FakeNTES({"station_live": MAS_BOARD})
    src = live(fake, clock=clock)
    assert src.departures("MAS", 4).provenance.mode is DataMode.LIVE
    assert src.departures("MAS", 4).provenance.mode is DataMode.CACHED and len(fake.calls) == 1
    clock.t += 61  # live answers are reused for at most 60 s
    fake.responses["station_live"] = UPSTREAM_DOWN
    stale = src.departures("MAS", 4)
    assert stale.provenance.mode is DataMode.STALE and stale.provenance.note.startswith("STALE:")


def test_board_quota_exhausted_serves_stale_or_unavailable():
    clock, quota = Clock(), Quota(free=1)
    src = live(FakeNTES({"station_live": MAS_BOARD}), clock=clock, quota=quota)
    src.departures("MAS", 4)
    clock.t += 61
    assert src.departures("MAS", 4).provenance.mode is DataMode.STALE
    board = src.departures("MAS", 2)  # different NTES window: nothing cached
    assert board.provenance.mode is DataMode.UNAVAILABLE
    assert board.reason == REASONS[ProviderErrorKind.RATE_LIMITED]


def test_board_upstream_error_gives_unavailable_without_upstream_text():
    board = live(FakeNTES({"station_live": UPSTREAM_DOWN})).departures("MAS", 2)
    assert board.provenance.mode is DataMode.UNAVAILABLE and board.reason == REASONS[ProviderErrorKind.UNAVAILABLE]
    assert "indianrail" not in board.model_dump_json() and "SSLError" not in board.model_dump_json()


def test_board_with_an_unexpected_shape_is_unavailable_not_empty():
    board = live(FakeNTES({"station_live": {"Station": "MAS"}})).departures("MAS", 2)
    assert board.provenance.mode is DataMode.UNAVAILABLE and board.reason == REASONS[ProviderErrorKind.BAD_RESPONSE]


def test_schedule_mapping():
    fake = FakeNTES({"schedule": SCHEDULE_12658})
    sched = live(fake).schedule("12658")
    assert sched.train_name == "SBC MAS SF MAIL" and sched.provenance.source == SOURCE
    assert sched.provenance.mode is DataMode.LIVE
    first, last = sched.stops[0], sched.stops[-1]
    assert (first.station_code, first.arrival, first.departure, first.day_offset) == ("SBC", None, "22:40", 0)
    assert (last.station_code, last.arrival, last.departure, last.day_offset) == ("MAS", "04:05", None, 1)
    assert first.station_name == "KSR Bengaluru"  # the catalogue's name for a known station
    assert sched.stops[3].station_name == "Perambur"  # not in the catalogue: NTES's name, title case


def test_schedule_unknown_train_is_unavailable():
    sched = live(FakeNTES({})).schedule("99999")
    assert sched.provenance.mode is DataMode.UNAVAILABLE and sched.reason == "NTES has no data for this request."


def test_live_status_maps_delay_and_uses_the_ntes_start_date():
    fake = FakeNTES({"live_status": LIVE_12658})
    status = live(fake).live_status("12658", date(2026, 10, 16))
    assert fake.calls == [("live_status", "12658", "16-Oct-2026")]
    assert status.delay_minutes == 3 and status.cancelled is False
    assert status.provenance.mode is DataMode.LIVE and status.provenance.source == SOURCE


def test_live_status_alerts():
    gone = live(FakeNTES({"live_status": NTESError("request failed: Train 12658 is Cancelled for 16-Oct-2026")}))
    status = gone.live_status("12658", date(2026, 10, 16))
    assert status.cancelled is True and status.provenance.mode is DataMode.LIVE
    none = live(FakeNTES({})).live_status("12658", date(2026, 10, 16))
    assert none.provenance.mode is DataMode.UNAVAILABLE and "No Data" not in (none.reason or "")
    down = live(FakeNTES({"live_status": UPSTREAM_DOWN})).live_status("12658", date(2026, 10, 16))
    assert down.provenance.mode is DataMode.UNAVAILABLE and down.reason == REASONS[ProviderErrorKind.UNAVAILABLE]


def test_disruption_source_reports_delays_only():
    on_time = {**LIVE_12658, "LDEL": "0"}
    fake = FakeNTES({"live_status": lambda no, day: LIVE_LATE if no == "12657" else on_time})
    src = NtesDisruptionSource(gateway(fake))
    events = src.events_for_trains([("12657", SUNDAY), ("12658", SUNDAY), ("12657", SUNDAY)])
    assert [(e.train_no, e.type, e.delay_minutes) for e in events] == [("12657", "delay", 25)]
    assert events[0].provenance.source == SOURCE and not events[0].simulated
    assert "unofficial" in events[0].label and src.get_event(events[0].id) == events[0]


# --- error mapping and parsing -------------------------------------------------------------------------------------

@pytest.mark.parametrize("exc, kind", [
    (NTESError("request failed: HTTPSConnectionPool(...): Read timed out. (read timeout=10)"), ProviderErrorKind.TIMEOUT),
    (UPSTREAM_DOWN, ProviderErrorKind.UNAVAILABLE),
    (NTESError("request failed: ('Connection aborted.', RemoteDisconnected(...))"), ProviderErrorKind.UNAVAILABLE),
    (NTESError("request failed: empty response"), ProviderErrorKind.BAD_RESPONSE),
    (NTESError("request failed: No Exceptional Details found for train 12658 !!!"), ProviderErrorKind.NOT_FOUND),
    (NTESCryptoError("bad padding"), ProviderErrorKind.BAD_RESPONSE),
    (KeyError("jsonIn"), ProviderErrorKind.BAD_RESPONSE),
])
def test_errors_map_to_typed_kinds_with_fixed_messages(exc, kind):
    err = map_error(exc)
    assert err.kind is kind and str(exc) not in err.message


def test_alerts_are_not_found_and_carry_only_a_cancelled_flag():
    assert isinstance(map_error(NTESError("request failed: Invalid Train Number")), NtesAlert)
    assert map_error(NTESError("request failed: Train Cancelled")).cancelled is True


def test_parsers():
    assert ntes_date(date(2026, 5, 2)) == "02-May-2026"
    assert parse_delay("RT") == 0 and parse_delay("03:47") == 227 and parse_delay("12") == 12
    assert parse_delay("--") is None
    assert parse_board_time("23:10 16-Oct", BOARD_NOW) == datetime(2026, 10, 16, 23, 10, tzinfo=IST)
    assert parse_board_time("00:10 01-Jan", datetime(2026, 12, 31, 23, 0, tzinfo=IST)).year == 2027
    assert parse_board_time("DSTN", BOARD_NOW) is None


# --- wiring, configuration, readiness ------------------------------------------------------------------------------

def test_container_wires_ntes_mode(monkeypatch):
    fake = FakeNTES({"trains_between": between_for_pair, "station_live": MAS_BOARD})
    monkeypatch.setattr(ntes_client, "default_factory", lambda timeout: (lambda: fake))
    redis = fakeredis.FakeStrictRedis(decode_responses=True)
    c = build_container(Settings(_env_file=None, RAILWAY_DATA_MODE="ntes", ntes_requests_per_minute=7,
                                 ntes_call_budget_seconds=9), clock=FixedClock(FIXED_NOW),
                        use_configured_llm=False, redis=redis)
    assert isinstance(c.provider, NtesJourneyProvider) and isinstance(c.disruptions, NtesDisruptionSource)
    assert isinstance(c.live, NtesLiveSource) and c.live._client is c.provider.client  # one budget and cache
    assert c.data_provider_status == {"requested": "ntes", "active": "ntes", "configured": True, "reason": None}
    assert c.provider._budget == 9 and c.disruptions._budget == 9
    quota = c.provider.client._quota
    assert isinstance(quota, RedisQuotaGate) and quota._rpm == 7 and ":ntes:quota:" in quota._key
    assert c.provider.data_mode is DataMode.LIVE
    # The planner and the live board both answer from NTES through the fake.
    assert c.live.departures("MAS", 4).provenance.source == SOURCE
    assert [o.legs[0].train_no for o in c.provider.search(["MAS"], ["SBC"], [SUNDAY])] == ["20607", "12007", "12657"]


def test_ntes_and_railradar_quota_keys_do_not_collide():
    redis = fakeredis.FakeStrictRedis(decode_responses=True)
    assert RedisQuotaGate(redis, "x", namespace="ntes")._key != RedisQuotaGate(redis, "x")._key


def test_app_import_does_not_import_ntes():
    code = ("import sys; import app.main; from app.config import Settings; from app.container import build_container; "
            "build_container(Settings(_env_file=None, RAILWAY_DATA_MODE='ntes'), use_configured_llm=False); "
            "assert 'ntes' not in sys.modules, 'ntes imported at startup'")
    backend = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-c", code], cwd=backend, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-2000:]


def test_no_captcha_or_pnr_path_is_used():
    app_dir = Path(__file__).resolve().parents[1] / "app"
    for path in app_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "pnr_status(" not in text and "irctc_reservation_chart" not in text and "from ntes.pnr" not in text, path


def test_ntes_call_budget_is_part_of_the_lock_ttl_check():
    with pytest.raises(ValueError, match="NTES_CALL_BUDGET_SECONDS"):
        Settings(_env_file=None, RAILWAY_DATA_MODE="ntes", ntes_call_budget_seconds=30, session_lock_ttl_ms=45_000)
    Settings(_env_file=None, RAILWAY_DATA_MODE="railradar", ntes_call_budget_seconds=30, session_lock_ttl_ms=45_000)
    ntes = Settings(_env_file=None, RAILWAY_DATA_MODE="ntes", ntes_call_budget_seconds=12)
    assert ntes.call_budget_seconds == 12 and ntes.planner_turn_budget_seconds == 32
    assert Settings(_env_file=None).ntes_requests_per_minute == 20


def make(redis=None, **overrides) -> TestClient:
    settings = Settings(_env_file=None, **overrides)
    container = build_container(settings, clock=FixedClock(FIXED_NOW), use_configured_llm=False, redis=redis)
    return TestClient(create_app(settings, container))


PROD = {"app_env": "production", "session_signing_key": "k" * 32, "RAILWAY_DATA_MODE": "ntes"}


def test_production_readiness_with_ntes_needs_no_railradar_key():
    res = make(redis=fakeredis.FakeStrictRedis(decode_responses=True), **PROD).get("/readyz")
    body = res.json()
    assert res.status_code == 200, body
    assert body["checks"]["data_provider"] is True and body["checks"]["railradar_key"] is True
    assert "ntes" not in body["degraded"]


def test_readiness_fails_when_the_ntes_package_is_missing(monkeypatch):
    monkeypatch.setattr("app.container.ntes_installed", lambda: False)
    c = make(redis=fakeredis.FakeStrictRedis(decode_responses=True), **PROD)
    assert c.app.state.container.data_provider_status["reason"] == "ntes_client_not_installed"
    res = c.get("/readyz")
    assert res.status_code == 503 and res.json()["checks"]["data_provider"] is False
    assert "ntes" in res.json()["degraded"]


def test_api_health_reports_ntes_as_the_active_live_provider():
    body = make(RAILWAY_DATA_MODE="ntes").get("/api/health").json()
    assert body["data_mode"] == "live" and body["data_provider"]["active"] == "ntes"


def test_planner_reply_names_ntes_as_the_source(monkeypatch):
    fake = FakeNTES({"trains_between": between_for_pair})
    monkeypatch.setattr(ntes_client, "default_factory", lambda timeout: (lambda: fake))
    api = make(RAILWAY_DATA_MODE="ntes")
    created = api.post("/api/planner/sessions", json={}).json()
    api.headers["X-Session-Token"] = created["session_token"]
    body = api.post(f"/api/planner/sessions/{created['session_id']}/messages",
                    json={"message": "from Chennai to Bengaluru on 2026-10-11, 1 passenger, fastest"}).json()
    assert body["data_mode"] == "live" and "NTES" in body["data_notice"]
    assert "NTES (unofficial client)" in body["assistant_message"]
    recs = body["state"]["recommendations"]["recommendations"]
    assert recs and all(r["option"]["provenance"]["source"] == SOURCE for r in recs)
    assert all(r["total_fare"] is None for r in recs)


# --- review fix 1: coded notes the UI renders in the passenger's language ------------------------------------------

def test_notes_carry_stable_codes_with_the_english_note_kept():
    clock, quota = Clock(), Quota(free=20)
    p = provider(FakeNTES({"trains_between": between_for_pair}), quota=quota, clock=clock)
    live_prov = p.search(["MAS"], ["SBC"], [SUNDAY])[0].provenance
    assert live_prov.note_codes == ["ntes"] and live_prov.note.startswith("Live data from NTES")
    assert p.search(["MAS"], ["SBC"], [SUNDAY])[0].provenance.note_codes == ["ntes_cached", "ntes"]
    clock.t += 301
    quota.free = 0
    assert p.search(["MAS"], ["SBC"], [SUNDAY])[0].provenance.note_codes == ["ntes_stale", "ntes"]


def test_partial_note_has_a_code_and_neutral_params():
    options = provider(FakeNTES({"trains_between": between_for_pair}), quota=Quota(free=1)).search(
        CHENNAI, BENGALURU, [SUNDAY])
    prov = options[0].provenance
    assert prov.note_codes == ["ntes_partial", "ntes"]
    assert "MS→SBC" in prov.note_params["missed"] and " to " not in prov.note_params["missed"]


def test_board_schedule_and_unavailable_answers_carry_codes():
    assert live(FakeNTES({"station_live": MAS_BOARD})).departures("MAS", 4).provenance.note_codes == [
        "ntes_board", "ntes"]
    assert live(FakeNTES({"schedule": SCHEDULE_12658})).schedule("12658").provenance.note_codes == ["ntes"]
    down = live(FakeNTES({"station_live": UPSTREAM_DOWN})).departures("MAS", 2)
    assert down.provenance.note_codes == ["live_unavailable"]
    assert live(FakeNTES({})).schedule("99999").provenance.note_codes == ["ntes_not_found"]
    assert live(FakeNTES({})).live_status("12658", SUNDAY).provenance.note_codes == ["ntes_no_status"]


def test_disruption_labels_are_given_in_english_and_tamil():
    src = NtesDisruptionSource(gateway(FakeNTES({"live_status": LIVE_LATE})))
    event = src.events_for_trains([("12657", SUNDAY)])[0]
    assert event.labels["en"] == event.label and "25" in event.labels["ta"]
    assert "தாமதமாக" in event.labels["ta"] and "unofficial" not in event.labels["ta"]
    assert event.provenance.note_codes == ["ntes"]


def test_tamil_planner_reply_names_the_source_in_tamil(monkeypatch):
    fake = FakeNTES({"trains_between": between_for_pair})
    monkeypatch.setattr(ntes_client, "default_factory", lambda timeout: (lambda: fake))
    api = make(RAILWAY_DATA_MODE="ntes")
    created = api.post("/api/planner/sessions", json={"language": "ta"}).json()
    api.headers["X-Session-Token"] = created["session_token"]
    body = api.post(f"/api/planner/sessions/{created['session_id']}/messages",
                    json={"message": "from Chennai to Bengaluru on 2026-10-11, 1 passenger, fastest"}).json()
    assert "NTES (அதிகாரப்பூர்வமற்ற கிளையன்ட்)" in body["assistant_message"]
    assert "unofficial client" not in body["assistant_message"]


def test_source_name_falls_back_per_language():
    from app.domain.enums import Language
    from app.harness.i18n import source_name
    assert source_name(Language.TA, None) == "நேரடி தரவு மூலம்"
    assert source_name(Language.EN, None) == "the live data source"
    assert source_name(Language.TA, "Some Feed") == "Some Feed"


# --- review fix 2: a cancellation is claimed only when it is unambiguous -------------------------------------------

@pytest.mark.parametrize("text, verdict", [
    ("Train 12658 is Cancelled for 16-Oct-2026", True),
    ("request failed: Train Cancelled", True),
    ("Train No. 12658 Cancelled", True),
    ("Cancelled", True),
    ("Train has been fully cancelled", True),
    ("Train 12658 is Partially Cancelled between SBC and KPD", None),
    ("Partially cancelled", None),
    ("Train short terminated at KPD; cancelled beyond", None),
    ("Cancellation details not available", None),
    ("Train is not cancelled", None),
    ("No cancellation reported", None),
    ("No train cancelled today", None),
    ("Cancelled from AJJ to MAS", None),
    ("Train diverted; cancelled via JTJ", None),
    ("Departed from MAHENDRAVADI(MDVE) at 02:37 17-Oct", False),
    ("", False),
])
def test_cancellation_classification(text, verdict):
    from app.providers.ntes_mapper import classify_cancellation
    assert classify_cancellation(text) is verdict


@pytest.mark.parametrize("cpos, expected", [
    ("Cancelled", (None, True, False)),
    ("Train is Partially Cancelled", (3, None, True)),
    ("Short terminated at KPD (Cancelled beyond)", (3, None, True)),
    ("Departed from MAHENDRAVADI(MDVE) at 02:37 17-Oct", (3, False, False)),
])
def test_map_live_claims_only_full_cancellations(cpos, expected):
    from app.providers.ntes_mapper import map_live
    assert map_live({**LIVE_12658, "CPOS": cpos, "LUPDFULL": ""}) == expected


def test_ambiguous_cancellation_alert_is_status_unclear_not_cancelled():
    alert = NTESError("request failed: Train 12658 is Partially Cancelled between SBC and KPD")
    assert map_error(alert).cancelled is None
    status = live(FakeNTES({"live_status": alert})).live_status("12658", date(2026, 10, 16))
    assert status.cancelled is None and status.provenance.mode is DataMode.UNAVAILABLE
    assert status.provenance.note_codes == ["ntes_status_unclear"] and "Check NTES or the station" in status.reason


def test_ambiguous_position_text_keeps_the_delay_and_flags_unclear():
    data = {**LIVE_12658, "CPOS": "Train short terminated at KPD (cancelled beyond)", "LUPDFULL": ""}
    status = live(FakeNTES({"live_status": data})).live_status("12658", date(2026, 10, 16))
    assert status.cancelled is None and status.delay_minutes == 3
    assert status.provenance.note_codes[0] == "ntes_status_unclear"


def test_a_cancellation_event_is_created_only_for_an_unambiguous_cancellation():
    responses = {
        "11111": NTESError("request failed: Train 11111 is Cancelled for 11-Oct-2026"),
        "22222": NTESError("request failed: Train 22222 is Partially Cancelled between SBC and KPD"),
        "33333": {**LIVE_12658, "CPOS": "Short terminated at KPD; cancelled beyond", "LUPDFULL": "", "LDEL": "0"},
        "44444": NTESError("request failed: Cancellation details not available"),
    }
    src = NtesDisruptionSource(gateway(FakeNTES({"live_status": lambda no, day: responses[no]})))
    events = src.events_for_trains([(no, SUNDAY) for no in responses])
    assert [(e.train_no, e.type) for e in events] == [("11111", "cancellation")]
