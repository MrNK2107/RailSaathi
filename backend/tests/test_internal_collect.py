"""POST /internal/collect: Cloud Run OIDC rejection paths, sampling of recently seen trains, JSONL output."""

import json
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import fakeredis
import pytest
from fastapi.testclient import TestClient
from google.auth import exceptions as google_auth_exceptions

from app.clock import FixedClock
from app.config import Settings
from app.container import build_container
from app.delay.observations import GcsObservationSink, InMemorySeenTrains, RedisSeenTrains, build_sink
from app.domain.enums import DataMode
from app.domain.options import DataProvenance
from app.main import create_app
from app.providers.live_source import TrainLiveStatus
from tests.conftest import FIXED_NOW

AUDIENCE = "https://railsaathi-backend-abc.a.run.app"
ACCOUNT = "scheduler@proj.iam.gserviceaccount.com"
GOOD = {"iss": "https://accounts.google.com", "aud": AUDIENCE, "email": ACCOUNT, "email_verified": True}
VERIFY = "app.api.internal_auth._verify"


class FakeLive:
    """LiveSource stand-in: 12676 is fresh, 22626 is stale, 12000 is unavailable, 12001 has no delay."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def live_status(self, train_no: str, run_date: date) -> TrainLiveStatus:
        self.calls.append(train_no)
        mode = {"12676": DataMode.LIVE, "12001": DataMode.LIVE, "22626": DataMode.STALE}.get(train_no,
                                                                                            DataMode.UNAVAILABLE)
        delay = {"12676": 12}.get(train_no)
        prov = DataProvenance(mode=mode, source="RailRadar", as_of=FIXED_NOW, note="n")
        return TrainLiveStatus(train_no=train_no, run_date=run_date, delay_minutes=delay, cancelled=False,
                               provenance=prov)


def make(tmp_path, **kw):
    settings = Settings(_env_file=None, observations_uri=str(tmp_path / "obs"), **kw)
    container = build_container(settings, clock=FixedClock(FIXED_NOW), use_configured_llm=False)
    container.live = FakeLive()
    return TestClient(create_app(settings, container)), container


def enabled(tmp_path):
    return make(tmp_path, internal_oidc_audience=AUDIENCE, internal_oidc_service_account=ACCOUNT)


def bearer(token="tok"):
    return {"Authorization": f"Bearer {token}"}


# ---- authentication ------------------------------------------------------------------------------------------

def test_disabled_when_oidc_is_not_configured(tmp_path):
    client, _ = make(tmp_path)
    assert client.post("/internal/collect", headers=bearer()).status_code == 404
    only_audience, _ = make(tmp_path, internal_oidc_audience=AUDIENCE)
    assert only_audience.post("/internal/collect", headers=bearer()).status_code == 404


def test_rejects_missing_or_malformed_authorization(tmp_path):
    client, _ = enabled(tmp_path)
    with patch(VERIFY) as verify:
        assert client.post("/internal/collect").status_code == 401
        assert client.post("/internal/collect", headers={"Authorization": "Basic abc"}).status_code == 401
        assert client.post("/internal/collect", headers={"Authorization": "Bearer "}).status_code == 401
        verify.assert_not_called()


@pytest.mark.parametrize("error", [ValueError("Token expired"), ValueError("Wrong audience"),
                                   google_auth_exceptions.TransportError("certs"), RuntimeError("boom")])
def test_rejects_tokens_that_fail_verification(tmp_path, error):
    client, container = enabled(tmp_path)
    with patch(VERIFY, side_effect=error):
        res = client.post("/internal/collect", headers=bearer())
    assert res.status_code == 401
    assert str(error) not in res.text  # never says why
    assert container.live.calls == []


@pytest.mark.parametrize("claims", [
    {**GOOD, "email": "someone-else@proj.iam.gserviceaccount.com"},
    {**GOOD, "iss": "https://evil.example.com"},
    {**GOOD, "email_verified": False},
    {k: v for k, v in GOOD.items() if k != "email"},
    {**GOOD, "email_verified": "true"},
])
def test_rejects_valid_tokens_from_the_wrong_caller(tmp_path, claims):
    client, container = enabled(tmp_path)
    with patch(VERIFY, return_value=claims):
        res = client.post("/internal/collect", headers=bearer())
    assert res.status_code == 403 and container.live.calls == []
    assert not (tmp_path / "obs").exists()


def test_verifier_is_given_the_configured_audience(tmp_path):
    client, _ = enabled(tmp_path)
    with patch(VERIFY, return_value=GOOD) as verify:
        assert client.post("/internal/collect", headers=bearer("abc")).status_code == 200
    verify.assert_called_once_with("abc", AUDIENCE)


def test_verification_uses_google_auth_with_the_audience():
    """The real verifier delegates to google-auth's verify_oauth2_token (signature, expiry, audience)."""
    from app.api import internal_auth

    with patch.object(internal_auth.id_token, "verify_oauth2_token", return_value=GOOD) as v:
        assert internal_auth._verify("tok", AUDIENCE) == GOOD
    assert v.call_args.args[0] == "tok" and v.call_args.kwargs["audience"] == AUDIENCE


def test_email_comparison_ignores_case(tmp_path):
    client, _ = enabled(tmp_path)
    with patch(VERIFY, return_value={**GOOD, "email": ACCOUNT.upper()}):
        assert client.post("/internal/collect", headers=bearer()).status_code == 200


# ---- collection ----------------------------------------------------------------------------------------------

def test_collect_samples_recently_seen_trains_and_writes_only_fresh_observations(tmp_path):
    client, container = enabled(tmp_path)
    container.seen_trains.record(["12676", "22626", "12000", "12001"])
    with patch(VERIFY, return_value=GOOD):
        body = client.post("/internal/collect", headers=bearer()).json()
    assert body["trains_seen"] == 4 and body["observations_written"] == 1 and body["skipped_not_fresh"] == 3
    files = list((tmp_path / "obs").rglob("*.jsonl"))
    assert len(files) == 1 and str(files[0]).replace("\\", "/") == body["object"].replace("\\", "/")
    [line] = files[0].read_text(encoding="utf-8").splitlines()
    obs = json.loads(line)
    assert obs["train_no"] == "12676" and obs["delay_minutes"] == 12 and obs["run_date"] == "2026-10-10"
    assert obs["hour"] == 10 and obs["weekday"] == 5 and obs["source"] == "RailRadar"


def test_collect_with_nothing_seen_writes_nothing(tmp_path):
    client, _ = enabled(tmp_path)
    with patch(VERIFY, return_value=GOOD):
        body = client.post("/internal/collect", headers=bearer()).json()
    assert body["trains_seen"] == 0 and body["object"] is None and not (tmp_path / "obs").exists()


def test_collect_is_capped_per_run(tmp_path):
    client, container = make(tmp_path, internal_oidc_audience=AUDIENCE, internal_oidc_service_account=ACCOUNT,
                             observation_max_trains=2)
    container.seen_trains.record(["12676", "12001", "12000", "22626"])
    with patch(VERIFY, return_value=GOOD):
        assert client.post("/internal/collect", headers=bearer()).json()["trains_seen"] == 2


def test_storage_failure_is_reported_without_details(tmp_path):
    client, container = enabled(tmp_path)
    container.seen_trains.record(["12676"])
    container.observation_sink = MagicMock(write=MagicMock(side_effect=OSError("bucket secret-name denied")))
    with patch(VERIFY, return_value=GOOD):
        res = client.post("/internal/collect", headers=bearer())
    assert res.status_code == 502 and "secret-name" not in res.text


def test_live_endpoints_record_seen_trains(tmp_path):
    settings = Settings(_env_file=None, observations_uri=str(tmp_path / "obs"))
    container = build_container(settings, clock=FixedClock(FIXED_NOW), use_configured_llm=False)
    client = TestClient(create_app(settings, container))
    assert client.get("/api/live/trains/12676/status").status_code == 200
    board = client.get("/api/live/stations/CBE/departures").json()
    seen = container.seen_trains.recent(50)
    assert "12676" in seen
    assert {d["train_no"] for d in board["departures"]} <= set(seen)


# ---- storage -------------------------------------------------------------------------------------------------

class MovableClock:
    def __init__(self, now):
        self.current = now

    def now(self):
        return self.current


def test_seen_trains_expire_and_reject_junk():
    clock = MovableClock(FIXED_NOW)
    seen = InMemorySeenTrains(clock, ttl_seconds=3600)
    seen.record(["12676", "bad code!", "../x"])
    assert seen.recent(10) == ["12676"]
    clock.current = FIXED_NOW + timedelta(hours=2)
    assert seen.recent(10) == []


def test_redis_seen_trains_most_recent_first_with_limit():
    r = fakeredis.FakeStrictRedis(decode_responses=True)
    clock = MovableClock(FIXED_NOW)
    seen = RedisSeenTrains(r, clock, 86400)
    seen.record(["11111"])
    clock.current = FIXED_NOW + timedelta(minutes=5)
    seen.record(["22222"])
    assert seen.recent(10) == ["22222", "11111"] and seen.recent(1) == ["22222"]
    clock.current = FIXED_NOW + timedelta(days=2)
    assert seen.recent(10) == []


def test_gcs_sink_writes_one_object_per_run():
    client = MagicMock()
    sink = GcsObservationSink("bkt", "observations/", client=client)
    uri = sink.write("2026/10/10/obs-1.jsonl", "{}\n")
    assert uri == "gs://bkt/observations/2026/10/10/obs-1.jsonl"
    client.bucket.assert_called_with("bkt")
    client.bucket.return_value.blob.assert_called_with("observations/2026/10/10/obs-1.jsonl")
    client.bucket.return_value.blob.return_value.upload_from_string.assert_called_once()


def test_build_sink_chooses_by_uri(tmp_path):
    from app.delay.observations import LocalObservationSink

    assert isinstance(build_sink(str(tmp_path)), LocalObservationSink)
    with pytest.raises(ValueError):
        build_sink("gs://")
