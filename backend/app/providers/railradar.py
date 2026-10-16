"""Live railway data from RailRadar (third-party, not an official Indian Railways source).

Implements the JourneyProvider and DisruptionSource interfaces so the planner,
ranking and API layers need no changes. Station facility data (assistance,
wheelchair) is not provided by RailRadar and is therefore always 'unknown'.
"""

import asyncio
import json
import logging
import threading
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.domain.enums import DataMode
from app.domain.options import DataProvenance, JourneyOption
from app.infra.async_bridge import run_sync
from app.providers.base import CityRecord, DisruptionEvent, StationRecord
from app.providers.errors import ProviderError, ProviderErrorKind
from app.providers.railradar_client import RailRadarClient
from app.providers.railradar_mapper import MappingError, map_live_status, map_train

log = logging.getLogger("railsaathi.railradar")
CATALOGUE = Path(__file__).parent / "data" / "station_catalogue.json"
SOURCE = "RailRadar live API (third-party)"
NOTE = ("Live third-party data from RailRadar, not an official Indian Railways source. Timings are as published "
        "by RailRadar and can change; fares, classes and seat availability are not provided; only direct trains "
        "are searched. Verify on IRCTC/NTES before travel.")
STALE_NOTE = ("STALE: RailRadar's request quota is exhausted, so this is an earlier response shown instead of "
              "fresh data and may be out of date. ")
# When several neighbour/date searches fail differently and none succeeds, the most actionable reason wins.
_ERROR_PRIORITY = [ProviderErrorKind.RATE_LIMITED, ProviderErrorKind.NOT_CONFIGURED, ProviderErrorKind.AUTH_FAILED,
                   ProviderErrorKind.TIMEOUT, ProviderErrorKind.UNAVAILABLE, ProviderErrorKind.BAD_RESPONSE,
                   ProviderErrorKind.BAD_REQUEST, ProviderErrorKind.NOT_FOUND]


def _partial_note(missed: list[tuple[str, str, date]]) -> str:
    listed = ", ".join(f"{o} to {d} on {day:%d %b}" for o, d, day in missed)
    return (f"PARTIAL: not every station search ran (RailRadar's shared request quota or an error), so trains "
            f"from these searches may be missing: {listed}. ")


CACHED_NOTE = ("CACHED: a recent RailRadar response reused from cache (fetched at the time shown), not fetched "
               "for this request. ")


def _note(mode: DataMode) -> str:
    if mode is DataMode.STALE:
        return STALE_NOTE + NOTE
    return CACHED_NOTE + NOTE if mode is DataMode.CACHED else NOTE


def load_catalogue() -> tuple[list[CityRecord], dict[str, StationRecord]]:
    doc = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    cities = [CityRecord(**c) for c in doc["cities"]]
    stations = {
        s["code"]: StationRecord(code=s["code"], name=s["name"], city=s["city"], aliases=s["aliases"], facilities={})
        for s in doc["stations"]
    }
    return cities, stations


class RailRadarJourneyProvider:
    def __init__(self, client: RailRadarClient, tz: str = "Asia/Kolkata", max_concurrency: int = 4,
                 budget_seconds: float = 15.0) -> None:
        self._client = client
        self._tz = ZoneInfo(tz)
        self._workers = max_concurrency
        self._budget = budget_seconds  # bounds a whole search (it runs under the planner's session lock)
        self._cities, self._stations = load_catalogue()
        self._names = {code: st.name for code, st in self._stations.items()}

    @property
    def data_mode(self) -> DataMode:
        return DataMode.LIVE

    @property
    def client(self) -> RailRadarClient:
        """The shared client (one quota and cache) so live boards reuse it."""
        return self._client

    def provenance(self, fetched_at: datetime | None = None, mode: DataMode = DataMode.LIVE) -> DataProvenance:
        """as_of is when RailRadar was actually called (cached responses keep their original time)."""
        as_of = (fetched_at or datetime.now(self._tz)).astimezone(self._tz)
        return DataProvenance(mode=mode, source=SOURCE, as_of=as_of, note=_note(mode))

    def cities(self) -> list[CityRecord]:
        return list(self._cities)

    def stations(self) -> list[StationRecord]:
        return list(self._stations.values())

    def station(self, code: str) -> StationRecord | None:
        # facilities={} -> every need resolves to Verification.UNKNOWN (never assumed)
        return self._stations.get(code)

    def search(self, origin_codes: list[str], destination_codes: list[str],
               departure_dates: list[date]) -> list[JourneyOption]:
        return run_sync(self._search(origin_codes, destination_codes, departure_dates), self._budget)

    async def _plan_jobs(self, origin_codes: list[str], destination_codes: list[str],
                         departure_dates: list[date]) -> tuple[list[tuple[str, str, date]], list[tuple[str, str, date]]]:
        """Primary stations first (the resolver lists a place's main station first), and no more uncached searches
        than the shared quota has free right now, so one plan cannot burn the minute's quota for every user.
        Returns (to run, skipped)."""
        ranked = sorted(
            ((oi + di, oi, ti, (o, d, day)) for ti, day in enumerate(departure_dates)
             for oi, o in enumerate(origin_codes) for di, d in enumerate(destination_codes) if o != d),
            key=lambda item: item[:3])
        free = await self._client.quota_remaining()
        run, skipped = [], []
        for *_, job in ranked:
            cached = await self._client.trains_between_cached(*job)
            if cached == "fresh":
                run.append(job)  # answered from cache, costs no quota
            elif free > 0:
                run.append(job)
                free -= 1
            elif cached == "stale":
                run.append(job)  # the quota will refuse it and the client serves the stale copy, labelled STALE
            else:
                skipped.append(job)
        return run, skipped

    async def _search(self, origin_codes: list[str], destination_codes: list[str],
                      departure_dates: list[date]) -> list[JourneyOption]:
        jobs, skipped = await self._plan_jobs(origin_codes, destination_codes, departure_dates)
        gate = asyncio.Semaphore(self._workers)

        async def bounded(job: tuple[str, str, date]) -> list[JourneyOption]:
            async with gate:
                return await self._search_one(*job)

        results = await asyncio.gather(*(bounded(job) for job in jobs), return_exceptions=True)
        errors: list[ProviderError] = []
        missed = list(skipped)
        seen: dict[str, JourneyOption] = {}
        for job, result in zip(jobs, results):
            if isinstance(result, ProviderError):
                errors.append(result)
                missed.append(job)
                continue
            if isinstance(result, BaseException):
                raise result
            for option in result:
                seen.setdefault(option.option_id, option)  # same train listed for several station pairs
        if skipped:
            log.warning("RailRadar quota allowed %d of %d searches; skipped %d", len(jobs), len(jobs) + len(skipped),
                        len(skipped))
        if not missed:
            return list(seen.values())
        if not seen:
            # Nothing usable came back: never report "no trains" when searches did not run or failed.
            if errors:
                raise min(errors, key=lambda e: _ERROR_PRIORITY.index(e.kind))
            raise ProviderError(ProviderErrorKind.RATE_LIMITED,
                                "RailRadar's shared request quota is used up for this minute")
        prefix = _partial_note(sorted(missed, key=lambda j: (j[2], j[0], j[1])))
        return [o.model_copy(update={"provenance": o.provenance.model_copy(
            update={"note": prefix + o.provenance.note})}) for o in seen.values()]

    async def _search_one(self, origin: str, dest: str, day: date) -> list[JourneyOption]:
        fetched = await self._client.trains_between(origin, dest, day)
        raw_trains = fetched.data
        provenance = self.provenance(fetched.fetched_at, fetched.mode)
        options, skipped = [], 0
        for raw in raw_trains:
            try:
                options.append(map_train(raw, origin, dest, day, self._tz, provenance, self._names))
            except (MappingError, ValueError):
                skipped += 1
        if raw_trains and not options:
            raise ProviderError(ProviderErrorKind.BAD_RESPONSE,
                                "RailRadar returned trains in a format the planner does not understand. "
                                "Run scripts/check_railradar.py and update railradar_mapper.py.")
        if skipped:
            log.warning("Skipped %d unmappable RailRadar records for %s-%s %s", skipped, origin, dest, day)
        return options


class RailRadarDisruptionSource:
    """Turns live running status into disruption events for the trains in a plan."""

    def __init__(self, client: RailRadarClient, tz: str = "Asia/Kolkata", budget_seconds: float = 15.0) -> None:
        self._client = client
        self._tz = ZoneInfo(tz)
        self._budget = budget_seconds  # bounds the whole lookup (it runs under the planner's session lock)
        self._events: dict[str, DisruptionEvent] = {}
        self._lock = threading.Lock()

    def list_events(self) -> list[DisruptionEvent]:
        with self._lock:
            return list(self._events.values())

    def get_event(self, event_id: str) -> DisruptionEvent | None:
        with self._lock:
            return self._events.get(event_id)

    def events_for_trains(self, trains: list[tuple[str, date]]) -> list[DisruptionEvent]:
        """Fetch live status for (train_no, run_date) pairs; return delays/cancellations only."""
        return run_sync(self._events_for_trains(trains), self._budget)

    async def _events_for_trains(self, trains: list[tuple[str, date]]) -> list[DisruptionEvent]:
        pairs = list(dict.fromkeys(trains))
        statuses = await asyncio.gather(*(self._client.live_status(n, d) for n, d in pairs))
        events: list[DisruptionEvent] = []
        for (train_no, day), fetched in zip(pairs, statuses):
            delay, cancelled = map_live_status(fetched.data)
            if not cancelled and not delay:
                continue
            event = DisruptionEvent(
                id=f"LIVE-{train_no}-{day.isoformat()}",
                type="cancellation" if cancelled else "delay",
                train_no=train_no,
                delay_minutes=0 if cancelled else int(delay or 0),
                label=(f"Live (RailRadar): train {train_no} reported cancelled" if cancelled
                       else f"Live (RailRadar): train {train_no} running {delay} min late"),
                simulated=False,
                provenance=DataProvenance(mode=DataMode.LIVE, source=SOURCE,
                                          as_of=fetched.fetched_at.astimezone(self._tz), note=NOTE),
            )
            events.append(event)
        with self._lock:
            self._events.update({e.id: e for e in events})
        return events


class UnconfiguredLiveProvider:
    """Used when live mode is requested but RailRadar is not configured.

    Station names still resolve (so the conversation works), but every search fails
    with a clear error. It never substitutes demo/fictional journeys."""

    def __init__(self, reason: str, tz: str = "Asia/Kolkata") -> None:
        self._reason = reason
        self._tz = ZoneInfo(tz)
        self._cities, self._stations = load_catalogue()

    @property
    def data_mode(self) -> DataMode:
        return DataMode.LIVE

    def provenance(self) -> DataProvenance:
        return DataProvenance(mode=DataMode.LIVE, source=SOURCE, as_of=datetime.now(self._tz), note=NOTE)

    def cities(self) -> list[CityRecord]:
        return list(self._cities)

    def stations(self) -> list[StationRecord]:
        return list(self._stations.values())

    def station(self, code: str) -> StationRecord | None:
        return self._stations.get(code)

    def search(self, origin_codes: list[str], destination_codes: list[str],
               departure_dates: list[date]) -> list[JourneyOption]:
        raise ProviderError(ProviderErrorKind.NOT_CONFIGURED, self._reason)

    # DisruptionSource side
    def list_events(self) -> list[DisruptionEvent]:
        return []

    def get_event(self, event_id: str) -> DisruptionEvent | None:
        return None

    def events_for_trains(self, trains: list[tuple[str, date]]) -> list[DisruptionEvent]:
        raise ProviderError(ProviderErrorKind.NOT_CONFIGURED, self._reason)
