"""Thin HTTP client for the RailRadar API (https://railradar.in/docs).

Endpoints used:
  GET /v1/trains/between/{from}/{to}?date=YYYY-MM-DD   trains between two stations
  GET /v1/trains/{number}/live?date=YYYY-MM-DD          live running status

Responses are wrapped as {"success": bool, "data": ..., "meta": {...}}.
The API key is sent as a Bearer token and is never logged.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import httpx

from app.domain.enums import DataMode
from app.providers.errors import ProviderError, ProviderErrorKind
from app.providers.railradar_shared import (
    CacheEntry,
    InMemoryQuotaGate,
    InMemoryResponseCache,
    QuotaGate,
    ResponseCache,
)

log = logging.getLogger("railsaathi.railradar")
QUOTA_EXHAUSTED_EVENT = "railradar_quota_exhausted"

_STATUS_KINDS = {
    401: ProviderErrorKind.AUTH_FAILED,
    403: ProviderErrorKind.AUTH_FAILED,
    404: ProviderErrorKind.NOT_FOUND,
    429: ProviderErrorKind.RATE_LIMITED,
}


@dataclass(frozen=True)
class Fetched:
    """Response payload plus when RailRadar was actually called (not when the cache was read).
    `mode` is STALE when an expired cached response was served because the quota was exhausted."""
    data: Any
    fetched_at: datetime
    mode: DataMode = field(default=DataMode.LIVE)


class RailRadarClient:
    """Async client. The quota gate and response cache are injected so every instance shares one budget (Redis)
    or, locally and in tests, a per-process one (in-memory)."""

    def __init__(
        self, base_url: str, api_key: str, timeout_seconds: float = 10.0, cache_seconds: int = 300,
        transport: httpx.AsyncBaseTransport | None = None,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        requests_per_minute: int = 10, quota: QuotaGate | None = None, cache: ResponseCache | None = None,
        clock: Callable[[], float] = time.time, stale_seconds: int = 21_600,
    ) -> None:
        if not api_key:
            raise ProviderError(ProviderErrorKind.NOT_CONFIGURED, "RAILRADAR_API_KEY is not set")
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json",
                     "User-Agent": "RailSaathi-Planner/0.1"},
        )
        self._cache_seconds = cache_seconds
        self._clock = clock  # epoch seconds: freshness of cache entries
        self._wall = wall_clock  # when RailRadar was actually called (reported as as_of)
        # Observed live: "Rate limit exceeded. Maximum 10 requests per minute." The gate enforces it before a
        # request is sent so a search fails fast with a clear wait time instead of hitting HTTP 429 mid-search.
        self._quota = quota or InMemoryQuotaGate(requests_per_minute, clock)
        self._cache = cache or InMemoryResponseCache(stale_seconds, clock=clock)

    async def quota_remaining(self) -> int:
        """Requests the shared quota still allows this minute (a peek; other instances may spend them first)."""
        return await self._quota.remaining()

    async def trains_between_cached(self, from_code: str, to_code: str, day: date) -> str | None:
        """"fresh" when a trains_between call would be answered from cache (no quota spent), "stale" when only an
        expired copy exists (served if the quota refuses), None when nothing is cached."""
        entry = await self._cache.get(self._key(f"/v1/trains/between/{from_code}/{to_code}",
                                                 {"date": day.isoformat()}))
        if entry is None:
            return None
        return "fresh" if entry.fresh_until > self._clock() else "stale"

    @staticmethod
    def _key(path: str, params: dict[str, str]) -> str:
        return f"{path}?{sorted(params.items())}"

    async def trains_between(self, from_code: str, to_code: str, day: date) -> Fetched:
        """GET /v1/trains/between/{from}/{to}. Documented shape: data.trains[] (plus from/to/count).
        A 404 is NOT treated as "no trains": RailRadar also uses 404 for unknown routes."""
        fetched = await self.get(f"/v1/trains/between/{from_code}/{to_code}", {"date": day.isoformat()})
        return Fetched(_as_list(fetched.data, ("trains", "items", "results")), fetched.fetched_at, fetched.mode)

    async def live_status(self, train_no: str, day: date, use_cache: bool = False) -> Fetched:
        """Never cached by default (the planner's "check live status"). Departure boards opt in to the response
        cache so a popular board does not spend the shared quota on every view; they label the result cached."""
        fetched = await self.get(f"/v1/trains/{train_no}/live", {"date": day.isoformat()}, use_cache=use_cache)
        return Fetched(fetched.data if isinstance(fetched.data, dict) else {}, fetched.fetched_at, fetched.mode)

    async def get(self, path: str, params: dict[str, str], use_cache: bool = True) -> Fetched:
        key = self._key(path, params)
        entry = await self._cache.get(key) if use_cache else None
        if entry is not None and entry.fresh_until > self._clock():
            return Fetched(entry.data, entry.fetched_at)
        try:
            data = await self._request_with_retry(path, params)
        except ProviderError as err:
            if err.kind is ProviderErrorKind.RATE_LIMITED:
                # One line per refused call (shared quota gate or an upstream 429). The log-based metric
                # railradar_quota_exhausted (infra/monitoring/) counts these by `event`; keep the field stable.
                log.warning("RailRadar quota exhausted for %s; %s", path,
                            "serving a stale cached response" if entry is not None else "no cached response to serve",
                            extra={"fields": {"event": QUOTA_EXHAUSTED_EVENT, "served_stale": entry is not None}})
                if entry is not None:
                    return Fetched(entry.data, entry.fetched_at, DataMode.STALE)
            raise
        fetched = Fetched(data, self._wall())
        if use_cache and self._cache_seconds:
            await self._cache.set(key, CacheEntry(data, fetched.fetched_at, self._clock() + self._cache_seconds))
        return fetched

    async def _request_with_retry(self, path: str, params: dict[str, str]) -> Any:
        try:
            return await self._request(path, params)
        except ProviderError as err:
            if err.kind not in (ProviderErrorKind.UNAVAILABLE, ProviderErrorKind.TIMEOUT):
                raise
            log.warning("RailRadar %s failed (%s); retrying once", path, err.kind.value)
            return await self._request(path, params)

    async def _request(self, path: str, params: dict[str, str]) -> Any:
        decision = await self._quota.acquire()
        if not decision.allowed:
            raise ProviderError(ProviderErrorKind.RATE_LIMITED,
                                f"RailRadar allows a limited number of requests per minute; "
                                f"try again in {decision.retry_after} s")
        try:
            response = await self._http.get(path, params=params)
        except httpx.TimeoutException as exc:
            raise ProviderError(ProviderErrorKind.TIMEOUT, "RailRadar did not respond in time") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, "Could not reach RailRadar") from exc
        return _unwrap(response)

    async def aclose(self) -> None:
        await self._http.aclose()


def _unwrap(response: httpx.Response) -> Any:
    try:
        body = response.json()
    except ValueError:
        body = None
    if response.status_code >= 400:
        kind = _STATUS_KINDS.get(response.status_code)
        if kind is None:
            kind = ProviderErrorKind.UNAVAILABLE if response.status_code >= 500 else ProviderErrorKind.BAD_REQUEST
        raise ProviderError(kind, f"RailRadar returned HTTP {response.status_code}: {_error_text(body)}")
    if not isinstance(body, dict):
        raise ProviderError(ProviderErrorKind.BAD_RESPONSE, "RailRadar returned a non-JSON response")
    if body.get("success") is False:
        raise ProviderError(ProviderErrorKind.BAD_REQUEST, f"RailRadar error: {_error_text(body)}")
    return body.get("data", body)


def _error_text(body: Any) -> str:
    """Documented error envelope: {"success": false, "error": {"code", "message"}, "meta": {...}}."""
    if isinstance(body, dict):
        err = body.get("error") or body.get("message") or ""
        if isinstance(err, dict):
            code, message = err.get("code"), err.get("message")
            err = f"{code}: {message}" if code and message else (message or code or "")
        return str(err)[:200] or "no details"
    return "no details"


def _as_list(data: Any, keys: tuple[str, ...]) -> list[dict]:
    """Extract the train list. An unrecognised shape is an error, never an empty result."""
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if isinstance(data, dict):
        for key in keys:
            if isinstance(data.get(key), list):
                return [d for d in data[key] if isinstance(d, dict)]
        if data.get("count") == 0:
            return []
    raise ProviderError(ProviderErrorKind.BAD_RESPONSE,
                        "RailRadar response has no train list (expected data.trains). "
                        "Run scripts/check_railradar.py to inspect the response.")
