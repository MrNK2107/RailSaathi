"""Uniform error envelope, request ids and structured logs."""

import json
import logging
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.observability import JsonLogFormatter, configure_logging
from app.audit.log import AuditEvent, AuditLog
from app.clock import FixedClock
from app.config import Settings
from app.container import build_container
from app.main import create_app
from app.sessions.redis_store import SessionLockTimeout
from tests.conftest import FIXED_NOW

SECRET = "super-secret-internal-detail"


def make(**overrides) -> TestClient:
    settings = Settings(_env_file=None, **overrides)
    container = build_container(settings, clock=FixedClock(FIXED_NOW), use_configured_llm=False)
    app = create_app(settings, container)

    @app.get("/__boom")
    def boom():
        raise RuntimeError(SECRET)

    @app.get("/__structured")
    def structured():
        raise HTTPException(409, {"code": "custom_code", "message": "Custom message.", "extra": 1})

    @app.get("/__busy")
    def busy():
        raise SessionLockTimeout("x")

    @app.get("/__log")
    def log_line():
        logging.getLogger("railsaathi.test").info("inside request")
        return {}

    return TestClient(app, raise_server_exceptions=False)


def assert_envelope(res, status, code):
    body = res.json()
    assert res.status_code == status
    assert set(body) == {"error", "request_id"} and set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code
    assert body["request_id"] and res.headers["X-Request-Id"] == body["request_id"]
    return body


def test_404_envelope():
    assert_envelope(make().get("/api/nope"), 404, "not_found")


def test_405_envelope():
    assert_envelope(make().delete("/api/health"), 405, "method_not_allowed")


def test_422_envelope_lists_fields_without_input_values():
    res = make().post("/api/planner/sessions", json={"language": "klingon"})
    body = assert_envelope(res, 422, "invalid_request")
    assert body["error"]["details"]["errors"][0]["field"] == "language"
    assert "klingon" not in res.text


def test_500_envelope_has_request_id_and_no_exception_text():
    res = make().get("/__boom")
    body = assert_envelope(res, 500, "internal_error")
    assert SECRET not in res.text and "RuntimeError" not in res.text and "Traceback" not in res.text
    assert body["error"]["message"] == "Something went wrong. Please try again."


def test_structured_http_exception_detail_is_kept():
    body = assert_envelope(make().get("/__structured"), 409, "custom_code")
    assert body["error"]["message"] == "Custom message." and body["error"]["details"] == {"extra": 1}


def test_planner_error_keeps_code_and_adds_request_id():
    res = make().get("/api/planner/sessions/00000000-0000-0000-0000-000000000000")
    assert_envelope(res, 401, "invalid_session_token")


def test_session_busy_envelope_keeps_retry_after():
    res = make().get("/__busy")
    assert_envelope(res, 503, "session_busy")
    assert res.headers["Retry-After"] == "2"


def test_rate_limit_and_body_limit_responses_carry_request_id():
    c = make(rate_limit_per_minute=1)
    c.get("/api/planner/reference")
    assert_envelope(c.get("/api/planner/reference"), 429, "rate_limited")
    big = make(max_body_bytes=1024).post("/api/chat", content=b"x" * 5000, headers={"Content-Length": "5000"})
    assert_envelope(big, 413, "payload_too_large")


def test_supplied_request_id_is_echoed_and_unsafe_ones_replaced():
    c = make()
    assert c.get("/api/health", headers={"X-Request-Id": "abc-123"}).headers["X-Request-Id"] == "abc-123"
    replaced = c.get("/api/health", headers={"X-Request-Id": "bad id with spaces"}).headers["X-Request-Id"]
    assert replaced != "bad id with spaces" and len(replaced) == 16


def test_validation_failed_details_exclude_input_values():
    from pydantic import BaseModel, ValidationError
    from app.harness.errors import safe_validation_errors

    class M(BaseModel):
        passengers: int

    with pytest.raises(ValidationError) as exc:
        M(passengers="my-private-value")
    out = safe_validation_errors(exc.value)
    assert out == [{"field": "passengers", "message": out[0]["message"]}]
    assert "my-private-value" not in str(out)


def test_patch_journey_invalid_values_do_not_echo_input():
    c = make()
    created = c.post("/api/planner/sessions", json={}).json()
    res = c.patch(f"/api/planner/sessions/{created['session_id']}/journey",
                  json={"passengers": 3}, headers={"X-Session-Token": created["session_token"]})
    assert res.status_code in (200, 422) and "input_value" not in res.text and "pydantic" not in res.text


def test_navigation_404_does_not_echo_exception_text():
    res = make().get("/api/stations/nowhere")
    body = assert_envelope(res, 404, "not_found")
    assert "nowhere" not in body["error"]["message"] and "Errno" not in res.text


@pytest.fixture
def json_logs():
    lines: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record):
            lines.append(self.format(record))

    handler = Capture()
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    previous = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    yield lines
    root.removeHandler(handler)
    root.setLevel(previous)


def test_json_logs_carry_request_id_trace_and_latency(json_logs):
    trace = "105445aa7843bc8bf206b12000100000"
    make(gcp_project="demo-proj").get(
        "/__log", headers={"X-Request-Id": "rid-1", "X-Cloud-Trace-Context": f"{trace}/1;o=1"})
    docs = [json.loads(line) for line in json_logs]
    inner = next(d for d in docs if d["message"] == "inside request")
    assert inner["severity"] == "INFO" and inner["request_id"] == "rid-1"
    assert inner["logging.googleapis.com/trace"] == f"projects/demo-proj/traces/{trace}"
    access = next(d for d in docs if d["message"] == "request")
    assert access["status"] == 200 and access["path"] == "/__log" and access["latency_ms"] >= 0
    assert access["request_id"] == "rid-1"


def test_no_trace_field_without_header(json_logs):
    make().get("/__log")
    assert all("logging.googleapis.com/trace" not in json.loads(line) for line in json_logs)


def test_audit_log_lines_never_include_detail_values(json_logs):
    AuditLog().record(AuditEvent(at=datetime.now(timezone.utc), session_id="s1", type="transition",
                                 detail={"reason": "private passenger text"}))
    line = next(line for line in json_logs if '"audit"' in line)
    doc = json.loads(line)
    assert doc["audit_type"] == "transition" and doc["detail_fields"] == ["reason"]
    assert "private passenger text" not in line


def test_configure_logging_is_idempotent():
    root = logging.getLogger()
    configure_logging("json")
    after_first = len(root.handlers)
    configure_logging("json")
    assert len(root.handlers) == after_first
