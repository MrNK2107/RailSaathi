"""Async gateway to NTES through `ntes-client`, an UNOFFICIAL Python client of the NTES app backend.

The owner chose this source knowingly (2026-10-17): it is not an authorised Indian Railways integration, it can
break or be blocked at any time, and NTES's terms of use apply. Only the train-enquiry calls are used:
trains_between, schedule, station_live and live_status. `pnr_status` (which solves a captcha) and the IRCTC chart
helpers are never called.

* The package is imported lazily on the first call, never when the app is imported. If the import fails, every
  call raises ProviderError(NOT_CONFIGURED) and the callers answer `unavailable` with a reason.
* The client is synchronous (requests). Calls run in a worker thread (asyncio.to_thread) from the shared async
  bridge, under the caller's run_sync budget, so the bridge loop is never blocked.
* Every request passes the QuotaGate first (Settings.ntes_requests_per_minute, a polite default of 20) and answers
  are kept in the ResponseCache, with their own Redis namespace ("ntes"). A cached copy is served CACHED while
  fresh, and STALE when the quota is used up or NTES fails.
* NTES failures arrive as NTESError with upstream text. They are mapped to ProviderError kinds with fixed messages;
  upstream or exception text never leaves this module."""

import asyncio
import importlib.util
import logging
import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Any

from app.domain.enums import DataMode
from app.providers.errors import ProviderError, ProviderErrorKind
from app.providers.railradar_client import Fetched
from app.providers.railradar_shared import (
    CacheEntry,
    InMemoryQuotaGate,
    InMemoryResponseCache,
    QuotaGate,
    ResponseCache,
)

log = logging.getLogger("railsaathi.ntes")
SOURCE = "NTES (unofficial client)"
# Stands in for an API key in the Redis key names of the shared quota and cache (there is no key).
QUOTA_IDENTITY = "ntes-client"
NAMESPACE = "ntes"
QUOTA_EXHAUSTED_EVENT = "ntes_quota_exhausted"
# Live answers (boards, running status) are reused for at most this long, whatever NTES_CACHE_SECONDS says.
LIVE_CACHE_SECONDS = 60
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
# Kinds after which an older cached copy is served (labelled STALE) instead of failing.
_SERVE_STALE = {ProviderErrorKind.RATE_LIMITED, ProviderErrorKind.TIMEOUT, ProviderErrorKind.UNAVAILABLE,
                ProviderErrorKind.BAD_RESPONSE, ProviderErrorKind.NOT_CONFIGURED}


def ntes_installed() -> bool:
    """Whether the package can be found (without importing it)."""
    try:
        return importlib.util.find_spec("ntes") is not None
    except (ImportError, ValueError):
        return False


def ntes_date(day: date) -> str:
    """NTES date format, e.g. 16-Oct-2026 (locale independent)."""
    return f"{day.day:02d}-{_MONTHS[day.month - 1]}-{day.year}"


def default_factory(timeout_seconds: float) -> Callable[[], Any]:
    def build() -> Any:
        try:
            from ntes import NTESClient
        except Exception as exc:  # noqa: BLE001 - ImportError or a broken install: report, never crash
            raise ProviderError(ProviderErrorKind.NOT_CONFIGURED, "The ntes-client package could not be imported") from exc
        # retries=0: this gateway decides about retries, so each attempt passes the quota gate.
        return NTESClient(timeout=max(1, round(timeout_seconds)), retries=0)

    return build


class NtesAlert(ProviderError):
    """NTES answered with an alert message instead of data (unknown train, no data, ...). `cancelled` is True only
    when the alert reports an unambiguous full cancellation, None when it mentions a cancellation ambiguously
    (partial, short-terminated, "details not available", ...), else False. The alert text itself is never kept."""

    def __init__(self, cancelled: bool | None) -> None:
        super().__init__(ProviderErrorKind.NOT_FOUND, "NTES has no data for this request")
        self.cancelled = cancelled


def map_error(exc: BaseException) -> ProviderError:
    """Typed error from whatever the client raised. Upstream text is inspected, never passed on."""
    if isinstance(exc, ProviderError):
        return exc
    name = type(exc).__name__
    text = str(exc).lower()
    if name == "NTESCryptoError":
        return ProviderError(ProviderErrorKind.BAD_RESPONSE, "NTES returned data that could not be decoded")
    if name != "NTESError":
        return ProviderError(ProviderErrorKind.BAD_RESPONSE, "The NTES client failed on this response")
    if "timed out" in text or "timeout" in text:
        return ProviderError(ProviderErrorKind.TIMEOUT, "NTES did not respond in time")
    if "empty response" in text or "invalid json" in text:
        return ProviderError(ProviderErrorKind.BAD_RESPONSE, "NTES returned an empty or malformed response")
    transport = ("connection", "ssl", "max retries", "httpsconnectionpool", "remote end", "proxy", "status code",
                 "http error", "chunked", "reset by peer")
    if any(marker in text for marker in transport):
        return ProviderError(ProviderErrorKind.UNAVAILABLE, "Could not reach NTES")
    # Anything else is a server alert ("No Exceptional Details found", "invalid train number", "Train Cancelled").
    from app.providers.ntes_mapper import classify_cancellation

    return NtesAlert(cancelled=classify_cancellation(str(exc)))


def _require(data: Any, key: str) -> Any:
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        raise ProviderError(ProviderErrorKind.BAD_RESPONSE, f"NTES response has no '{key}' list")
    return data


def _require_dict(data: Any) -> Any:
    if not isinstance(data, dict):
        raise ProviderError(ProviderErrorKind.BAD_RESPONSE, "NTES response is not an object")
    return data


class NtesClient:
    """Quota-gated, cached access to the NTES enquiry calls. `factory` builds the synchronous client (tests pass a
    fake); one client is built per worker thread because requests sessions are not documented as thread safe."""

    def __init__(self, factory: Callable[[], Any] | None = None, timeout_seconds: float = 10.0,
                 cache_seconds: int = 300, requests_per_minute: int = 20, quota: QuotaGate | None = None,
                 cache: ResponseCache | None = None, clock: Callable[[], float] = time.time,
                 wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 stale_seconds: int = 21_600) -> None:
        self._factory = factory or default_factory(timeout_seconds)
        self._cache_seconds = cache_seconds
        self._clock = clock
        self._wall = wall_clock
        self._quota = quota or InMemoryQuotaGate(requests_per_minute, clock)
        self._cache = cache or InMemoryResponseCache(stale_seconds, clock=clock)
        self._local = threading.local()

    # --- the four enquiry calls -------------------------------------------------------------------------------

    async def trains_between(self, from_code: str, to_code: str) -> Fetched:
        """All trains between two stations (not date specific: each record carries its days of run)."""
        fetched = await self._get(f"between:{from_code}:{to_code}",
                                  lambda c: c.trains_between(from_code, to_code, "XXX"),
                                  lambda d: _require(d, "Trains"), self._cache_seconds)
        return Fetched(fetched.data["Trains"], fetched.fetched_at, fetched.mode)

    async def trains_between_cached(self, from_code: str, to_code: str) -> str | None:
        """"fresh" when trains_between would be answered from cache, "stale" when only an expired copy exists
        (served if the quota refuses), None when nothing is cached."""
        entry = await self._cache.get(f"between:{from_code}:{to_code}")
        if entry is None:
            return None
        return "fresh" if entry.fresh_until > self._clock() else "stale"

    async def schedule(self, train_no: str) -> Fetched:
        return await self._get(f"schedule:{train_no}", lambda c: c.schedule(train_no),
                               lambda d: _require(d, "stations"), self._cache_seconds)

    async def station_live(self, station_code: str, hours: int) -> Fetched:
        return await self._get(f"board:{station_code}:{hours}", lambda c: c.station_live(station_code, hours),
                               lambda d: _require(d, "TrainsAtStation"), min(self._cache_seconds, LIVE_CACHE_SECONDS))

    async def live_status(self, train_no: str, start_date: date, use_cache: bool = False) -> Fetched:
        """Running status of the run that left its origin on `start_date`. Not served from a fresh cache entry
        unless `use_cache` (the planner's "check live status" fetches anew); an earlier copy is still served STALE
        when the quota is used up or NTES fails."""
        return await self._get(f"live:{train_no}:{start_date.isoformat()}",
                               lambda c: c.live_status(train_no, ntes_date(start_date)), _require_dict,
                               min(self._cache_seconds, LIVE_CACHE_SECONDS), use_fresh_cache=use_cache)

    async def quota_remaining(self) -> int:
        return await self._quota.remaining()

    # --- plumbing ---------------------------------------------------------------------------------------------

    async def _get(self, key: str, call: Callable[[Any], Any], validate: Callable[[Any], Any], ttl: int,
                   use_fresh_cache: bool = True) -> Fetched:
        entry = await self._cache.get(key)
        if use_fresh_cache and entry is not None and entry.fresh_until > self._clock():
            return Fetched(entry.data, entry.fetched_at, DataMode.CACHED)
        try:
            data = validate(await self._request_with_retry(call))
        except ProviderError as err:
            if err.kind is ProviderErrorKind.RATE_LIMITED:
                log.warning("NTES quota exhausted for %s; %s", key.split(":")[0],
                            "serving a stale cached response" if entry is not None else "no cached response to serve",
                            extra={"fields": {"event": QUOTA_EXHAUSTED_EVENT, "served_stale": entry is not None}})
            if entry is not None and err.kind in _SERVE_STALE:
                return Fetched(entry.data, entry.fetched_at, DataMode.STALE)
            raise
        fetched = Fetched(data, self._wall())
        if ttl:
            await self._cache.set(key, CacheEntry(data, fetched.fetched_at, self._clock() + ttl))
        return fetched

    async def _request_with_retry(self, call: Callable[[Any], Any]) -> Any:
        try:
            return await self._request(call)
        except ProviderError as err:
            if err.kind not in (ProviderErrorKind.UNAVAILABLE, ProviderErrorKind.TIMEOUT):
                raise
            log.warning("NTES call failed (%s); retrying once", err.kind.value)
            return await self._request(call)

    async def _request(self, call: Callable[[Any], Any]) -> Any:
        decision = await self._quota.acquire()
        if not decision.allowed:
            raise ProviderError(ProviderErrorKind.RATE_LIMITED,
                                f"RailSaathi's NTES request budget is used up; try again in {decision.retry_after} s")
        return await asyncio.to_thread(self._call, call)

    def _call(self, call: Callable[[Any], Any]) -> Any:
        try:
            client = getattr(self._local, "client", None)
            if client is None:
                client = self._local.client = self._factory()
            return call(client)
        except Exception as exc:  # noqa: BLE001 - every client failure becomes a typed ProviderError
            err = map_error(exc)
            log.warning("NTES call failed (%s, %s)", err.kind.value, type(exc).__name__)
            raise err from None
