"""Request hardening: body size limit and rate limiting. Pure ASGI so bodies are never buffered whole."""

import logging

import anyio
import anyio.to_thread
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.observability import current_request_id
from app.security.rate_limit import Decision, RateLimiter
from app.security.tokens import TOKEN_HEADER, InvalidSessionToken, SessionTokenSigner

log = logging.getLogger("railsaathi.http")

HEALTH_PATHS = frozenset({"/healthz", "/readyz", "/api/health"})
BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})
LIMITER_TIMEOUT_SECONDS = 1.0  # a slower limiter (e.g. a hung Redis) fails open instead of stalling requests


def error_json(status: int, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, headers=headers,
                        content={"error": {"code": code, "message": message, "details": {}},
                                 "request_id": current_request_id()})


def is_llm_route(method: str, path: str) -> bool:
    """Routes that can reach an LLM: ticketing chat, goal-planner prompt parsing, planner messages and AR
    localisation."""
    if method != "POST":
        return False
    return (path in ("/api/chat", "/api/journey/plan", "/api/journey/refine", "/api/navigation/localize")
            or path.endswith("/messages"))


def client_ip(headers: Headers, scope: Scope, trusted_hops: int = 0, trust_cf: bool = False) -> str:
    """Client IP from X-Forwarded-For, taking the Nth entry from the right (entries added by trusted proxies;
    anything to the left is client-controlled). 0 hops, or too few entries, means the socket peer.
    With `trust_cf` (the local demo tunnel only) the Cloudflare-set CF-Connecting-IP header is the visitor."""
    if trust_cf:
        cf = headers.get("cf-connecting-ip", "").strip()
        if cf:
            return cf[:64]
    if trusted_hops > 0:
        parts = [p.strip() for p in headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if len(parts) >= trusted_hops:
            return parts[-trusted_hops][:64]
    client = scope.get("client")
    return client[0] if client else "unknown"


async def hit_with_timeout(limiter: RateLimiter, key: str, limit: int, window_seconds: int = 60,
                           timeout: float = LIMITER_TIMEOUT_SECONDS) -> Decision:
    """Run the (possibly blocking Redis) limiter off the event loop; fail open if it is too slow."""
    decision: Decision | None = None
    with anyio.move_on_after(timeout):
        decision = await anyio.to_thread.run_sync(limiter.hit, key, limit, window_seconds, abandon_on_cancel=True)
    if decision is None:
        log.warning("rate limiter timed out; failing open")
        return Decision(True)
    return decision


class BodySizeLimitMiddleware:
    """`max_bytes` for every body, except the exact paths in `path_limits` (e.g. the camera-frame upload)."""

    def __init__(self, app: ASGIApp, max_bytes: int, path_limits: dict[str, int] | None = None) -> None:
        self.app = app
        self._default = max_bytes
        self._path_limits = dict(path_limits or {})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in BODY_METHODS:
            await self.app(scope, receive, send)
            return
        limit = self._path_limits.get(scope.get("path", ""), self._default)
        length = Headers(scope=scope).get("content-length")
        too_large = error_json(413, "payload_too_large", "Request body is too large.")
        if length and length.isdigit() and int(length) > limit:
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
                if received > limit:
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
                 trust_cf: bool = False, limiter_timeout: float = LIMITER_TIMEOUT_SECONDS) -> None:
        self.app = app
        self._limiter = limiter
        self._limit = per_minute
        self._llm_limit = llm_per_minute
        self._signer = signer
        self._hops = trusted_hops
        self._trust_cf = trust_cf
        self._timeout = limiter_timeout

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or path in HEALTH_PATHS or scope["method"] == "OPTIONS":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        tier, limit = ("llm", self._llm_limit) if is_llm_route(scope["method"], path) else ("std", self._limit)
        keys = [f"{tier}:ip:{client_ip(headers, scope, self._hops, self._trust_cf)}"]
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
        return await hit_with_timeout(self._limiter, key, limit, timeout=self._timeout)

    def _session_of(self, token: str | None) -> str | None:
        if not token or self._signer is None:
            return None
        try:
            return self._signer.verify(token)
        except InvalidSessionToken:
            return None
