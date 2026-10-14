"""Request correlation and structured (Cloud Logging compatible) JSON logs.

Every request gets an id (taken from `X-Request-Id` when the caller supplies a sane one, otherwise generated),
kept in a contextvar for log lines, stored in the ASGI scope state for error handlers and echoed in the response
header. Request log lines carry method, path, status and latency only; never bodies or passenger messages."""

import contextvars
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-Id"
TRACE_HEADER = "X-Cloud-Trace-Context"
_SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
_trace: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace", default=None)
_HANDLER_MARK = "_railsaathi_json_handler"
_http_log = logging.getLogger("railsaathi.http")


def current_request_id() -> str | None:
    return _request_id.get()


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def request_id_from_scope(scope: Scope) -> str:
    return (scope.get("state") or {}).get("request_id") or current_request_id() or new_request_id()


def parse_trace(header: str | None, project: str | None) -> str | None:
    """`X-Cloud-Trace-Context: TRACE_ID/SPAN_ID;o=1` -> `projects/<project>/traces/<TRACE_ID>` (or the bare id)."""
    if not header:
        return None
    trace_id = header.split("/", 1)[0].strip()
    if not re.fullmatch(r"[0-9a-fA-F]{1,64}", trace_id):
        return None
    return f"projects/{project}/traces/{trace_id}" if project else trace_id


class JsonLogFormatter(logging.Formatter):
    """One JSON object per line using the field names Cloud Logging understands."""

    def format(self, record: logging.LogRecord) -> str:
        doc: dict[str, Any] = {
            "severity": "WARNING" if record.levelno == logging.WARNING else record.levelname,
            "message": record.getMessage(),
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "logger": record.name,
        }
        if request_id := current_request_id():
            doc["request_id"] = request_id
        if trace := _trace.get():
            doc["logging.googleapis.com/trace"] = trace
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            doc.update(fields)
        if record.exc_info:
            doc["exception"] = self.formatException(record.exc_info)
        return json.dumps(doc, default=str, ensure_ascii=False)


def configure_logging(log_format: str = "json", level: int = logging.INFO) -> None:
    """Idempotent: replaces only the handler installed by a previous call."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARK, False):
            root.removeHandler(handler)
    handler = logging.StreamHandler()
    setattr(handler, _HANDLER_MARK, True)
    handler.setFormatter(JsonLogFormatter() if log_format.lower() == "json"
                         else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
    root.setLevel(level)


class ObservabilityMiddleware:
    """Outermost middleware: request id + trace context, response header, one access-log line per request."""

    def __init__(self, app: ASGIApp, gcp_project: str | None = None) -> None:
        self.app = app
        self._project = gcp_project

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        supplied = headers.get(REQUEST_ID_HEADER.lower(), "")
        request_id = supplied if _SAFE_ID.match(supplied) else new_request_id()
        scope.setdefault("state", {})["request_id"] = request_id
        id_token = _request_id.set(request_id)
        trace_token = _trace.set(parse_trace(headers.get(TRACE_HEADER.lower()), self._project))
        started = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            _http_log.info("request", extra={"fields": {
                "method": scope["method"], "path": scope["path"], "status": status,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1)}})
            _request_id.reset(id_token)
            _trace.reset(trace_token)
