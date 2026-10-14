"""Request hardening: body size limit, rate limiting, access logs. Pure ASGI so bodies are never buffered whole."""

import json
import logging
import time
import uuid

import anyio
import anyio.to_thread
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.security.rate_limit import Decision, RateLimiter
from app.security.tokens import TOKEN_HEADER, InvalidSessionToken, SessionTokenSigner

log = logging.getLogger("railsaathi.http")

HEALTH_PATHS = frozenset({"/healthz", "/readyz", "/api/health"})
BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})


def error_json(status: int, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, headers=headers,
                        content={"error": {"code": code, "message": message, "details": {}}})


def is_llm_route(method: str, path: str) -> bool:
    """Routes that can reach an LLM: ticketing chat, goal-planner prompt parsing and planner messages."""
    if method != "POST":
        return False
    return path in ("/api/chat", "/api/journey/plan", "/api/journey/refine") or path.endswith("/messages")


def client_ip(headers: Headers, scope: Scope, trusted_hops: int = 0) -> str:
    """Client IP from X-Forwarded-For, taking the Nth entry from the right (entries added by trusted proxies;
    anything to the left is client-controlled). 0 hops, or too few entries, means the socket peer."""
    if trusted_hops > 0:
        parts = [p.strip() for p in headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if len(parts) >= trusted_hops:
            return parts[-trusted_hops][:64]
    client = scope.get("client")
    return client[0] if client else "unknown"


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self._max = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in BODY_METHODS:
            await self.app(scope, receive, send)
            return
        length = Headers(scope=scope).get("content-length")
        too_large = error_json(413, "payload_too_large", "Request body is too large.")
        if length and length.isdigit() and int(length) > self._max:
            await too_large(scope, receive, send)
            return

        received = 0
        exceeded = False

        async def counting_receive() -> Message:
            nonlocal received, exceeded
            if exceeded:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._max:
                    # Stop feeding the app; whatever it answers is replaced by the 413 below.
                    exceeded = True
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            if not exceeded:
                await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except Exception:
            if not exceeded:
                raise
        if exceeded:
            await too_large(scope, receive, send)


class RateLimitMiddleware:
    """Two sliding-window buckets per request: one per client IP and, when a valid session token is presented,
    one per session. Health routes are exempt; LLM routes use the lower tier."""

    def __init__(self, app: ASGIApp, limiter: RateLimiter, per_minute: int, llm_per_minute: int,
                 signer: SessionTokenSigner | None = None, trusted_hops: int = 0,
                 limiter_timeout: float = 1.0) -> None:
        self.app = app
        self._limiter = limiter
        self._limit = per_minute
        self._llm_limit = llm_per_minute
        self._signer = signer
        self._hops = trusted_hops
        self._timeout = limiter_timeout

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or path in HEALTH_PATHS or scope["method"] == "OPTIONS":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        tier, limit = ("llm", self._llm_limit) if is_llm_route(scope["method"], path) else ("std", self._limit)
        keys = [f"{tier}:ip:{client_ip(headers, scope, self._hops)}"]
        session_id = self._session_of(headers.get(TOKEN_HEADER.lower()))
        if session_id:
            keys.append(f"{tier}:sid:{session_id}")
        for key in keys:
            decision = await self._hit(key, limit)
            if not decision.allowed:
                resp = error_json(429, "rate_limited", "Too many requests. Please wait a moment.",
                                  {"Retry-After": str(decision.retry_after)})
                await resp(scope, receive, send)
                return
        await self.app(scope, receive, send)

    async def _hit(self, key: str, limit: int) -> Decision:
        """Run the (possibly blocking Redis) limiter off the event loop; fail open if it is too slow."""
        decision: Decision | None = None
        with anyio.move_on_after(self._timeout):
            decision = await anyio.to_thread.run_sync(self._limiter.hit, key, limit, abandon_on_cancel=True)
        if decision is None:
            log.warning("rate limiter timed out; failing open")
            return Decision(True)
        return decision

    def _session_of(self, token: str | None) -> str | None:
        if not token or self._signer is None:
            return None
        try:
            return self._signer.verify(token)
        except InvalidSessionToken:
            return None


class AccessLogMiddleware:
    """Logs method, path, status and latency only; never bodies or passenger messages."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = Headers(scope=scope).get("x-request-id") or uuid.uuid4().hex[:12]
        started = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            log.info(json.dumps({
                "request_id": request_id, "method": scope["method"], "path": scope["path"],
                "status": status, "ms": round((time.perf_counter() - started) * 1000, 1),
            }))
