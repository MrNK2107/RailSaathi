"""One error envelope for every router: {"error": {"code", "message", "details"}, "request_id"}.

Exception text never reaches a response: unhandled errors are logged server-side (with the request id) and the
client gets a generic message."""

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.observability import REQUEST_ID_HEADER, request_id_from_scope
from app.harness.errors import PlannerError
from app.sessions.redis_store import SessionLockTimeout

log = logging.getLogger("railsaathi")

_CODES = {
    400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed",
    409: "conflict", 410: "gone", 411: "length_required", 413: "payload_too_large", 415: "unsupported_media_type",
    422: "invalid_request", 429: "rate_limited",
    500: "internal_error", 502: "bad_gateway", 503: "service_unavailable", 504: "gateway_timeout",
}


def error_response(request: Request, status: int, code: str, message: str,
                   details: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> JSONResponse:
    request_id = request_id_from_scope(request.scope)
    return JSONResponse(
        status_code=status,
        headers={**(headers or {}), REQUEST_ID_HEADER: request_id},
        content={"error": {"code": code, "message": message, "details": details or {}}, "request_id": request_id},
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(PlannerError)
    async def planner_error(request: Request, exc: PlannerError) -> JSONResponse:
        return error_response(request, exc.http_status, exc.code, exc.message, exc.details)

    @app.exception_handler(SessionLockTimeout)
    async def session_busy(request: Request, _: SessionLockTimeout) -> JSONResponse:
        return error_response(request, 503, "session_busy", "This session is busy. Please retry shortly.",
                              headers={"Retry-After": "2"})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        status = exc.status_code
        generic = HTTPStatus(status).phrase if status in HTTPStatus._value2member_map_ else "Error"
        code, message, details = _CODES.get(status, f"http_{status}"), generic, {}
        detail = exc.detail
        if isinstance(detail, dict):  # structured detail authored by a route, e.g. {"code", "message", ...}
            code = str(detail.get("code") or code)
            message = str(detail.get("message") or generic)
            details = {k: v for k, v in detail.items() if k not in ("code", "message")}
        elif isinstance(detail, str) and status < 500 and detail != generic:
            message = detail
        return error_response(request, status, code, message, details, dict(exc.headers or {}))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
        return error_response(request, 422, "invalid_request", "The request is invalid.", {"errors": errors})

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        request_id = request_id_from_scope(request.scope)
        log.error("Unhandled error: %s", type(exc).__name__, exc_info=exc,
                  extra={"fields": {"request_id": request_id}})
        return error_response(request, 500, "internal_error", "Something went wrong. Please try again.")
