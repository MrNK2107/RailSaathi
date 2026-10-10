"""Thin HTTP client for the RailRadar API (https://railradar.in/docs).

Endpoints used:
  GET /v1/trains/between/{from}/{to}?date=YYYY-MM-DD   trains between two stations
  GET /v1/trains/{number}/live?date=YYYY-MM-DD          live running status

Responses are wrapped as {"success": bool, "data": ..., "meta": {...}}.
The API key is sent as a Bearer token and is never logged.
"""

import logging
import math
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import httpx

from app.providers.errors import ProviderError, ProviderErrorKind

log = logging.getLogger("railsaathi.railradar")

_STATUS_KINDS = {
    401: ProviderErrorKind.AUTH_FAILED,
    403: ProviderErrorKind.AUTH_FAILED,
    404: ProviderErrorKind.NOT_FOUND,
    429: ProviderErrorKind.RATE_LIMITED,
}


@dataclass(frozen=True)
class Fetched:
    """Response payload plus when RailRadar was actually called (not when the cache was read)."""
    data: Any
    fetched_at: datetime


class RailRadarClient:
    def __init__(
        self, base_url: str, api_key: str, timeout_seconds: float = 10.0, cache_seconds: int = 300,
        transport: httpx.BaseTransport | None = None, monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        requests_per_minute: int = 10,
    ) -> None:
        if not api_key:
            raise ProviderError(ProviderErrorKind.NOT_CONFIGURED, "RAILRADAR_API_KEY is not set")
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json",
                     "User-Agent": "RailSaathi-Planner/0.1"},
        )
        self._cache_seconds = cache_seconds
        self._cache: dict[str, tuple[float, Fetched]] = {}
        self._lock = threading.Lock()
        self._now = monotonic
        self._wall = wall_clock
        # Observed live: "Rate limit exceeded. Maximum 10 requests per minute." Enforce it locally so a
        # search fails fast with a clear wait time instead of hitting HTTP 429 mid-search.
        self._rpm = requests_per_minute
        self._sent: deque[float] = deque()

    def trains_between(self, from_code: str, to_code: str, day: date) -> Fetched:
        """GET /v1/trains/between/{from}/{to}. Documented shape: data.trains[] (plus from/to/count).
        A 404 is NOT treated as "no trains": RailRadar also uses 404 for unknown routes."""
        fetched = self.get(f"/v1/trains/between/{from_code}/{to_code}", {"date": day.isoformat()})
        return Fetched(_as_list(fetched.data, ("trains", "items", "results")), fetched.fetched_at)

    def live_status(self, train_no: str, day: date) -> Fetched:
        fetched = self.get(f"/v1/trains/{train_no}/live", {"date": day.isoformat()}, use_cache=False)
        return Fetched(fetched.data if isinstance(fetched.data, dict) else {}, fetched.fetched_at)

    def get(self, path: str, params: dict[str, str], use_cache: bool = True) -> Fetched:
        key = f"{path}?{sorted(params.items())}"
        if use_cache:
            cached = self._cached(key)
            if cached is not None:
                return cached
        fetched = Fetched(self._request_with_retry(path, params), self._wall())
        if use_cache and self._cache_seconds:
            with self._lock:
                self._cache[key] = (self._now() + self._cache_seconds, fetched)
        return fetched

    def _cached(self, key: str) -> Fetched | None:
        with self._lock:
            hit = self._cache.get(key)
            if hit and hit[0] > self._now():
                return hit[1]
            self._cache.pop(key, None)
            return None

    def _request_with_retry(self, path: str, params: dict[str, str]) -> Any:
        try:
            return self._request(path, params)
        except ProviderError as err:
            if err.kind not in (ProviderErrorKind.UNAVAILABLE, ProviderErrorKind.TIMEOUT):
                raise
            log.warning("RailRadar %s failed (%s); retrying once", path, err.kind.value)
            return self._request(path, params)

    def _reserve_slot(self) -> None:
        with self._lock:
            now = self._now()
            while self._sent and now - self._sent[0] >= 60:
                self._sent.popleft()
            if len(self._sent) >= self._rpm:
                wait = math.ceil(60 - (now - self._sent[0]))
                raise ProviderError(ProviderErrorKind.RATE_LIMITED,
                                    f"RailRadar allows {self._rpm} requests per minute; try again in {wait} s")
            self._sent.append(now)

    def _request(self, path: str, params: dict[str, str]) -> Any:
        self._reserve_slot()
        try:
            response = self._http.get(path, params=params)
        except httpx.TimeoutException as exc:
            raise ProviderError(ProviderErrorKind.TIMEOUT, "RailRadar did not respond in time") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, "Could not reach RailRadar") from exc
        return _unwrap(response)


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
