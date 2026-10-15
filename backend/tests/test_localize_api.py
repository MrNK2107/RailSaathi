"""AR localisation: POST /api/navigation/localize and the Gemini vision adapter.

Runs over the bundled Chennai Central data (ar_enabled, cues on most nodes). The localizer is a scripted mock or
the Gemini adapter over a fake SDK client; nothing contacts Google."""

import asyncio
import base64
import json
import logging
from types import SimpleNamespace

import fakeredis
import pytest
from fastapi.testclient import TestClient
from google.genai import types

from app.api.observability import JsonLogFormatter
from app.clock import FixedClock
from app.config import STATIONS_DIR, Settings
from app.container import build_container, build_vision_localizer
from app.llm.base import Deadline, LLMError, LLMErrorKind
from app.llm.mock import MockVisionLocalizer
from app.security.rate_limit import Decision
from app.llm.vision import GeminiVisionLocalizer, LocalizeCandidate, LocalizeHint, LocalizeResult
from app.main import create_app
from app.navigation.services.station_store import build_source, load_catalogue
from tests.conftest import FIXED_NOW

URL = "/api/navigation/localize"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
CHENNAI = load_catalogue(build_source(str(STATIONS_DIR))).get("chennai_central").station


def make(vision=None, redis=None, **kw) -> tuple[TestClient, object]:
    kw.setdefault("rate_limit_llm_per_minute", 1000)  # the per-minute LLM tier is not what these tests exercise
    settings = Settings(_env_file=None, stations_uri=str(STATIONS_DIR), **kw)
    container = build_container(settings, clock=FixedClock(FIXED_NOW), use_configured_llm=False, redis=redis,
                                vision=vision)
    return TestClient(create_app(settings, container)), container


def post(client, image=JPEG, mime="image/jpeg", headers=None, **fields):
    data = {"station_id": "chennai_central", **fields}
    return client.post(URL, data=data, files={"image": ("frame", image, mime)}, headers=headers or {})


def fix(node="p11_access", confidence=0.9, **kw) -> LocalizeResult:
    return LocalizeResult(node_id=node, confidence=confidence, **kw)


# ---- answers ---------------------------------------------------------------------------------------------------

def test_confident_answer_is_a_fix_with_live_gemini_provenance():
    vision = MockVisionLocalizer([fix(facing_bearing_deg=271.4, matched_cues=("Platform 11", "Free Wi-Fi zone"),
                                      candidates=(LocalizeCandidate("wa_north", 0.2),))])
    client, _ = make(vision)
    res = post(client, previous_node_id="wa_north", route_node_ids="wa_north,p11_access,platform_11")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "fix" and body["station_id"] == "chennai_central"
    assert body["fix"] == {"node_id": "p11_access", "node_name": "Platform 11 Access", "level": 0,
                           "position": [0.35969, 0.34722], "confidence": 0.9, "facing_bearing_deg": 271.4,
                           "matched_cues": ["Platform 11"]}  # an invented cue is dropped
    assert body["candidates"] == [{"node_id": "wa_north", "node_name": "West Aisle (north)", "confidence": 0.2}]
    assert body["confidence_threshold"] == 0.6 and body["latency_ms"] >= 0 and body["message"] is None
    prov = body["provenance"]
    assert prov["mode"] == "live" and prov["source"] == "gemini-vision" and "Approximate" in prov["note"]
    assert body["session_token"]
    call = vision.calls[0]
    assert call["mime_type"] == "image/jpeg" and call["bytes"] == len(JPEG)
    assert call["hint"] == LocalizeHint("wa_north", ("wa_north", "p11_access", "platform_11"))


def test_webp_is_accepted():
    client, _ = make(MockVisionLocalizer([fix()]))
    assert post(client, image=WEBP, mime="image/webp").json()["status"] == "fix"


def test_below_threshold_returns_candidates_and_no_fix():
    vision = MockVisionLocalizer([fix("p10_access", 0.45, candidates=(LocalizeCandidate("p9_access", 0.3),
                                                                      LocalizeCandidate("wa_centre", 0.1)))])
    body = post(make(vision)[0]).json()
    assert body["status"] == "low_confidence" and body["fix"] is None and body["message"]
    assert [c["node_id"] for c in body["candidates"]] == ["p10_access", "p9_access", "wa_centre"]
    assert body["provenance"]["mode"] == "live"


def test_threshold_comes_from_settings():
    body = post(make(MockVisionLocalizer([fix(confidence=0.45)]), localize_confidence_threshold=0.4)[0]).json()
    assert body["status"] == "fix"


def test_node_ids_outside_the_station_are_never_returned():
    vision = MockVisionLocalizer([fix("platform_17", 0.99, candidates=(
        LocalizeCandidate("../../etc", 0.9), LocalizeCandidate("p7_access", 0.5)))])
    body = post(make(vision)[0]).json()
    assert body["status"] == "low_confidence" and body["fix"] is None
    assert body["candidates"] == [{"node_id": "p7_access", "node_name": "Platform 7 Access", "confidence": 0.5}]


# ---- degradation ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("failure", [LLMError(LLMErrorKind.TIMEOUT), LLMError(LLMErrorKind.THROTTLED)])
def test_model_outage_is_unavailable_not_500(failure):
    body = post(make(MockVisionLocalizer([failure]))[0]).json()
    assert body["status"] == "unavailable" and body["fix"] is None and body["candidates"] == []
    assert body["provenance"]["mode"] == "unavailable" and body["provenance"]["source"] == "gemini-vision"


def test_unexpected_localizer_crash_is_unavailable_not_500():
    class Broken:
        name = "broken"

        def localize(self, *args, **kwargs):
            raise RuntimeError("boom")

    res = post(make(Broken())[0])
    assert res.status_code == 200 and res.json()["status"] == "unavailable"


def test_no_localizer_configured_is_unavailable():
    client, container = make(None)
    assert container.vision is None and container.vision_reason == "llm_disabled"
    assert post(client).json()["status"] == "unavailable"


def test_container_builds_gemini_only_when_configured():
    assert build_vision_localizer(Settings(_env_file=None)) == (None, "llm_disabled")
    assert build_vision_localizer(Settings(_env_file=None, llm_provider="gemini")) == (None, "gemini_not_configured")
    vision, reason = build_vision_localizer(Settings(_env_file=None, llm_provider="gemini", gcp_project="p"))
    assert isinstance(vision, GeminiVisionLocalizer) and reason is None


# ---- feature flag and inputs ------------------------------------------------------------------------------------

def test_flag_off_for_the_station_refuses():
    client, _ = make(MockVisionLocalizer([fix()]), ar_guidance_enabled="ksr_bengaluru")
    res = post(client)
    assert res.status_code == 404 and res.json()["error"]["code"] == "ar_guidance_unavailable"


def test_station_without_ar_data_refuses():
    res = post(make(MockVisionLocalizer([fix()]))[0], station_id="chennai_egmore")
    assert res.status_code == 404 and res.json()["error"]["code"] == "ar_guidance_unavailable"


def test_flag_defaults_off_in_production_and_on_elsewhere():
    assert Settings(_env_file=None).ar_guidance_on("chennai_central")
    prod = Settings(_env_file=None, app_env="production")
    assert not prod.ar_guidance_on("chennai_central")
    assert Settings(_env_file=None, app_env="production", ar_guidance_enabled="chennai_central").ar_guidance_on(
        "chennai_central")
    assert Settings(_env_file=None, app_env="production", ar_guidance_enabled="*").ar_guidance_on("x")


@pytest.mark.parametrize("fields", [{"previous_node_id": "nowhere"}, {"route_node_ids": "p11_access,nowhere"},
                                    {"station_id": "Chennai Central!"}])
def test_bad_fields_are_422(fields):
    vision = MockVisionLocalizer([fix()])
    res = post(make(vision)[0], **fields)
    assert res.status_code == 422 and vision.calls == []


def test_unknown_station_is_404():
    assert post(make(MockVisionLocalizer([fix()]))[0], station_id="atlantis").status_code == 404


def test_invalid_session_token_is_rejected():
    res = post(make(MockVisionLocalizer([fix()]))[0], headers={"X-Session-Token": "forged.token"})
    assert res.status_code == 401


# ---- upload limits ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("image,mime", [(PNG, "image/png"), (PNG, "image/jpeg"), (JPEG, "image/webp"),
                                        (b"GIF89a" + b"\x00" * 10, "image/gif")])
def test_only_real_jpeg_or_webp_is_accepted(image, mime):
    vision = MockVisionLocalizer([fix()])
    res = post(make(vision)[0], image=image, mime=mime)
    assert res.status_code == 415 and res.json()["error"]["code"] == "unsupported_image_type"
    assert vision.calls == []


def test_non_multipart_body_is_415():
    res = make(MockVisionLocalizer([fix()]))[0].post(URL, json={"station_id": "chennai_central"})
    assert res.status_code == 415


def test_oversized_image_is_413():
    vision = MockVisionLocalizer([fix()])
    client, _ = make(vision, localize_max_image_bytes=10_000)
    res = post(client, image=JPEG + b"\x00" * 10_000)
    assert res.status_code == 413 and vision.calls == []
    assert post(client, image=JPEG + b"\x00" * 9_000).status_code == 200


def test_default_limit_is_one_and_a_half_megabytes():
    vision = MockVisionLocalizer([fix()])
    client, _ = make(vision)
    assert post(client, image=JPEG + b"\x00" * 1_500_000).status_code == 413
    assert vision.calls == []


def _asgi_call(app, headers: list[tuple[bytes, bytes]]) -> tuple[int, bool]:
    """Call the app directly with a body that fails the test if it is ever read."""
    read = False
    sent: list[dict] = []

    async def receive():
        nonlocal read
        read = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http",
             "path": URL, "raw_path": URL.encode(), "query_string": b"", "root_path": "",
             "headers": headers, "client": ("1.2.3.4", 1234), "server": ("test", 80)}
    asyncio.run(app(scope, receive, send))
    return next(m["status"] for m in sent if m["type"] == "http.response.start"), read


def test_declared_size_is_refused_before_the_body_is_read():
    client, _ = make(MockVisionLocalizer([fix()]))
    status, read = _asgi_call(client.app, [(b"content-type", b"multipart/form-data; boundary=x"),
                                           (b"content-length", b"50000000")])
    assert status == 413 and not read


def test_missing_content_length_is_refused_before_the_body_is_read():
    client, _ = make(MockVisionLocalizer([fix()]))
    status, read = _asgi_call(client.app, [(b"content-type", b"multipart/form-data; boundary=x")])
    assert status == 411 and not read


def test_other_routes_keep_the_small_body_limit():
    client, _ = make(MockVisionLocalizer([]))
    res = client.post("/api/chat", content=b"x" * 20_000, headers={"content-type": "application/json"})
    assert res.status_code == 413


# ---- rate limit ------------------------------------------------------------------------------------------------

@pytest.fixture(params=["memory", "redis"])
def limiter_redis(request):
    return fakeredis.FakeStrictRedis(decode_responses=True) if request.param == "redis" else None


def test_twenty_fixes_per_session_per_ten_minutes(limiter_redis):
    vision = MockVisionLocalizer([fix()] * 25)
    client, _ = make(vision, redis=limiter_redis)
    token = post(client).json()["session_token"]
    codes = [post(client, headers={"X-Session-Token": token}).status_code for _ in range(20)]
    assert codes == [200] * 19 + [429]
    res = post(client, headers={"X-Session-Token": token})
    assert res.json()["error"]["code"] == "rate_limited" and int(res.headers["Retry-After"]) > 60
    assert len(vision.calls) == 20  # refused requests never reach the model
    assert post(client).status_code == 200  # a new session has its own budget


def test_per_ip_budget_stops_session_farming(limiter_redis):
    client, _ = make(MockVisionLocalizer([fix()] * 5), redis=limiter_redis, localize_ip_rate_limit=2)
    assert [post(client).status_code for _ in range(3)] == [200, 200, 429]


# ---- privacy ---------------------------------------------------------------------------------------------------

def test_frame_bytes_never_reach_the_logs():
    marker = b"PASSENGER-FRAME-SECRET-0123456789"
    frame = b"\xff\xd8\xff\xe0" + marker * 50
    lines: list[str] = []
    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record)
            lines.append(self.format(record))

    client, _ = make(MockVisionLocalizer([fix(), LLMError(LLMErrorKind.MODEL_ERROR), fix(confidence=0.1)]))
    handler = Capture(level=logging.DEBUG)
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    previous = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)  # after create_app, which sets INFO: capture everything, debug included
    try:
        for _ in range(3):
            assert post(client, image=frame).status_code == 200
        assert post(client, image=frame, mime="image/png").status_code == 415
    finally:
        root.removeHandler(handler)
        root.setLevel(previous)
    text = "\n".join(lines) + "\n".join(repr(r.__dict__) for r in records)
    for needle in (marker, base64.b64encode(marker), marker.hex().encode()):
        assert needle.decode() not in text
    localize_logs = [json.loads(line) for line in lines if json.loads(line)["message"] == "localize"]
    assert len(localize_logs) == 3
    for doc in localize_logs:
        assert {"node_id", "confidence", "latency_ms", "status"} <= doc.keys()


# ---- Gemini adapter (fake SDK client) ----------------------------------------------------------------------------

def _gemini(payload):
    calls = []

    async def generate_content(*, model, contents, config):
        calls.append({"contents": contents, "config": config})
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return types.GenerateContentResponse(candidates=[types.Candidate(
            content=types.Content(role="model", parts=[types.Part.from_text(text=text)]))])

    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    settings = Settings(_env_file=None, llm_provider="gemini", gcp_project="p")
    return GeminiVisionLocalizer(settings, client=client, backoff_seconds=0.01), calls


def test_gemini_sends_inline_image_and_an_enum_of_station_node_ids():
    localizer, calls = _gemini({"node_id": "p11_access", "confidence": 0.8, "facing_bearing_deg": 270,
                                "matched_cues": ["Platform 11"],
                                "candidates": [{"node_id": "wa_north", "confidence": 0.1}]})
    result = localizer.localize(JPEG, "image/jpeg", CHENNAI, LocalizeHint("wa_north"), Deadline(5))
    assert result == LocalizeResult("p11_access", 0.8, 270.0, ("Platform 11",),
                                    (LocalizeCandidate("wa_north", 0.1),))
    config = calls[0]["config"]
    schema = config.response_json_schema
    assert config.response_mime_type == "application/json"
    assert schema["properties"]["node_id"]["enum"] == [n.id for n in CHENNAI.nodes]
    assert schema["properties"]["candidates"]["items"]["properties"]["node_id"]["enum"] == [n.id for n in CHENNAI.nodes]
    parts = calls[0]["contents"][0].parts
    assert parts[0].inline_data.data == JPEG and parts[0].inline_data.mime_type == "image/jpeg"
    assert "wa_north" in parts[1].text and "Platform 11" in parts[1].text


@pytest.mark.parametrize("payload", ["not json", {"node_id": "platform_17", "confidence": 0.9}, ["p11_access"]])
def test_gemini_answers_outside_the_enum_or_malformed_are_invalid(payload):
    localizer, _ = _gemini(payload)
    with pytest.raises(LLMError) as err:
        localizer.localize(JPEG, "image/jpeg", CHENNAI, LocalizeHint(), Deadline(5))
    assert err.value.kind is LLMErrorKind.INVALID_OUTPUT


def test_gemini_clamps_numbers_and_filters_candidates():
    localizer, _ = _gemini({"node_id": "p9_access", "confidence": 7, "facing_bearing_deg": -90,
                            "matched_cues": [], "candidates": [{"node_id": "nope", "confidence": 1},
                                                               {"node_id": "p9_access", "confidence": 1}]})
    result = localizer.localize(JPEG, "image/jpeg", CHENNAI, LocalizeHint(), Deadline(5))
    assert result.confidence == 1.0 and result.facing_bearing_deg == 270.0 and result.candidates == ()


# ---- review round 1: malformed localizer output and a hung limiter -----------------------------------------------

class _Returns:
    name = "malformed"

    def __init__(self, value):
        self.value = value

    def localize(self, *args, **kwargs):
        return self.value


@pytest.mark.parametrize("value", [None, "p11_access", LocalizeResult("p11_access", 0.9, candidates=None),
                                   LocalizeResult("p11_access", 0.9, matched_cues=7)])
def test_malformed_localizer_result_is_unavailable_not_500(value):
    res = post(make(_Returns(value))[0])
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "unavailable" and body["fix"] is None
    assert body["provenance"]["mode"] == "unavailable" and body["provenance"]["source"] == "gemini-vision"


def test_hung_rate_limiter_fails_open_within_a_second():
    import threading
    import time

    release = threading.Event()

    class HungLimiter:
        def hit(self, key, limit, window_seconds=60):
            release.wait(10)  # a Memorystore call that never answers
            return Decision(True)

    client, _ = make(MockVisionLocalizer([fix()]))
    client.app.state.rate_limiter = HungLimiter()
    try:
        started = time.monotonic()
        res = post(client)
        elapsed = time.monotonic() - started
    finally:
        release.set()
    assert res.status_code == 200 and res.json()["status"] == "fix"
    assert elapsed < 4.0  # two limiter keys, each capped at 1 s, instead of hanging for 10 s
