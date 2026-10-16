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


def _note(mode: DataMode) -> str:
    return STALE_NOTE + NOTE if mode is DataMode.STALE else NOTE


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

    async def _search(self, origin_codes: list[str], destination_codes: list[str],
                      departure_dates: list[date]) -> list[JourneyOption]:
        jobs = [(o, d, day) for day in departure_dates for o in origin_codes for d in destination_codes if o != d]
        gate = asyncio.Semaphore(self._workers)

        async def bounded(job: tuple[str, str, date]) -> list[JourneyOption]:
            async with gate:
                return await self._search_one(*job)

        batches = await asyncio.gather(*(bounded(job) for job in jobs))
        seen: dict[str, JourneyOption] = {}
        for option in (o for batch in batches for o in batch):
            seen.setdefault(option.option_id, option)  # same train listed for several station pairs
        return list(seen.values())

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
