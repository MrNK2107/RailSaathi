"""Prototype-level request hardening: body size limit, rate limiting, access logs.

The rate limiter is in-memory and per process; a deployment behind several
workers should use a shared store or the gateway's limiter instead."""

import json
import logging
import threading
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

log = logging.getLogger("railsaathi.http")


def error_json(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": {}}})


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int) -> None:
        super().__init__(app)
        self._max = max_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in ("POST", "PUT", "PATCH"):
            length = request.headers.get("content-length")
            if length and length.isdigit() and int(length) > self._max:
                return error_json(413, "payload_too_large", "Request body is too large.")
            body = await request.body()
            if len(body) > self._max:
                return error_json(413, "payload_too_large", "Request body is too large.")
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, per_minute: int) -> None:
        super().__init__(app)
        self._limit = per_minute
        self._hits: dict[str, tuple[int, int]] = {}
        self._lock = threading.Lock()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path.startswith("/api/") and request.url.path != "/api/health":
            client = request.client.host if request.client else "unknown"
            window = int(time.time() // 60)
            with self._lock:
                start, count = self._hits.get(client, (window, 0))
                count = count + 1 if start == window else 1
                self._hits[client] = (window, count)
            if count > self._limit:
                return error_json(429, "rate_limited", "Too many requests. Please wait a moment.")
        return await call_next(request)


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Logs method, path, status and latency only — never bodies or passenger messages."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        started = time.perf_counter()
        response = await call_next(request)
        log.info(json.dumps({
            "request_id": request_id, "method": request.method, "path": request.url.path,
            "status": response.status_code, "ms": round((time.perf_counter() - started) * 1000, 1),
        }))
        response.headers["x-request-id"] = request_id
        return response
