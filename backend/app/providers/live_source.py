"""Live station information: departure boards, train schedules and running status.

`LiveSource` is the one interface the live API uses. Implementations:
  * NtesLiveSource      - NTES through the unofficial ntes-client, on its own quota and response cache (the
                          planner's client instance): real station boards, schedules and running status.
  * RailRadarLiveSource - RailRadar on the shared quota and response cache (the planner's client instance).
  * DemoLiveSource      - bundled simulated data, labelled `demo`; never built when APP_ENV=production.
  * UnavailableLiveSource - every answer is `unavailable` with a reason (key missing, demo refused in production).

No implementation ever substitutes invented data: a request that cannot be answered returns provenance mode
`unavailable` and a passenger-safe `reason` (upstream error text is never passed through)."""

import asyncio
import json
import logging
from datetime import date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from app.clock import Clock
from app.domain.enums import DataMode
from app.domain.options import DataProvenance
from app.infra.async_bridge import run_sync
from app.providers.demo import DATA_DIR
from app.providers.errors import ProviderError, ProviderErrorKind
from app.providers.ntes import NOTE as NTES_NOTE
from app.providers.ntes import note_for as ntes_note_for
from app.providers.ntes_client import SOURCE as NTES_SOURCE
from app.providers.ntes_client import NtesAlert, NtesClient
from app.providers.ntes_mapper import map_board_entry, map_live, map_schedule, station_label
from app.providers.railradar import NOTE as RAILRADAR_NOTE
from app.providers.railradar import SOURCE as RAILRADAR_SOURCE
from app.providers.railradar_client import RailRadarClient
from app.providers.railradar_mapper import MappingError, map_live_status, map_train
from app.providers.station_directory import StationDirectory, StationPoint

log = logging.getLogger("railsaathi.live")

DEMO_SOURCE = "RailSaathi sample timetable"
DEMO_NOTE = "Simulated trains and running status for development. Not real Indian Railways data."
CATALOGUE_SOURCE = "RailSaathi station catalogue (bundled reference list)"

# Passenger-safe reasons per provider failure. Provider messages can carry upstream text, so they are never shown.
REASONS = {
    ProviderErrorKind.RATE_LIMITED: ("The live data provider's request quota is used up and no recent copy is "
                                     "cached. Try again in a minute."),
    ProviderErrorKind.TIMEOUT: "The live data provider did not respond in time.",
    ProviderErrorKind.UNAVAILABLE: "The live data provider could not be reached.",
    ProviderErrorKind.AUTH_FAILED: "Live data is not configured correctly.",
    ProviderErrorKind.NOT_CONFIGURED: "Live data is not configured.",
    ProviderErrorKind.NOT_FOUND: "The live data provider has no data for this request.",
    ProviderErrorKind.BAD_REQUEST: "The live data provider rejected this request.",
    ProviderErrorKind.BAD_RESPONSE: "The live data provider returned data in a format RailSaathi does not understand.",
}
# When several neighbour queries fail differently, the most actionable reason wins.
_REASON_PRIORITY = [ProviderErrorKind.RATE_LIMITED, ProviderErrorKind.NOT_CONFIGURED, ProviderErrorKind.AUTH_FAILED,
                    ProviderErrorKind.TIMEOUT, ProviderErrorKind.UNAVAILABLE, ProviderErrorKind.BAD_RESPONSE,
                    ProviderErrorKind.BAD_REQUEST, ProviderErrorKind.NOT_FOUND]
SCHEDULE_UNSUPPORTED = "Train schedules are not supported by the live data provider (RailRadar) in this release."


def reason_for(err: ProviderError) -> str:
    return REASONS.get(err.kind, "Live data is unavailable.")


class UnknownStation(LookupError):
    """The station code is not in the station catalogue."""


class StationRef(BaseModel):
    code: str
    name: str


class Departure(BaseModel):
    train_no: str
    train_name: str
    scheduled_departure: datetime  # at the board's station
    # RailRadar: catalogue neighbours this train reaches directly (not necessarily its terminus); NTES: its terminus
    towards: list[StationRef]
    delay_minutes: int | None = None  # None: running status not known
    cancelled: bool | None = None  # None: running status not known
    status_as_of: datetime | None = None  # when the running status was fetched


class DepartureBoard(BaseModel):
    station: StationRef
    window_start: datetime
    window_end: datetime
    neighbours_checked: list[StationRef] = Field(default_factory=list)
    complete: bool  # False when some neighbour queries failed (the list may be missing trains)
    departures: list[Departure] = Field(default_factory=list)
    provenance: DataProvenance
    reason: str | None = None  # set when provenance.mode is unavailable


class ScheduleStop(BaseModel):
    station_code: str
    station_name: str
    arrival: str | None = None  # "HH:MM", None at the origin
    departure: str | None = None  # "HH:MM", None at the terminus
    day_offset: int = 0  # days after the train's first departure


class TrainSchedule(BaseModel):
    train_no: str
    train_name: str | None = None
    stops: list[ScheduleStop] = Field(default_factory=list)
    provenance: DataProvenance
    reason: str | None = None


class TrainLiveStatus(BaseModel):
    train_no: str
    run_date: date
    delay_minutes: int | None = None
    cancelled: bool | None = None
    provenance: DataProvenance
    reason: str | None = None


class LiveSource(Protocol):
    @property
    def directory(self) -> StationDirectory: ...

    def catalogue_provenance(self) -> DataProvenance: ...

    def departures(self, station_code: str, hours: int) -> DepartureBoard: ...

    def schedule(self, train_no: str) -> TrainSchedule: ...

    def live_status(self, train_no: str, run_date: date) -> TrainLiveStatus: ...


def _ref(point: StationPoint) -> StationRef:
    return StationRef(code=point.code, name=point.name)


class _Base:
    """Shared window, catalogue and `unavailable` helpers."""

    source = RAILRADAR_SOURCE
    catalogue_mode = DataMode.CACHED

    def __init__(self, directory: StationDirectory, clock: Clock, tz: str) -> None:
        self._dir = directory
        self._clock = clock
        self._tz = ZoneInfo(tz)
        self._loaded_at = clock.now().astimezone(self._tz)

    @property
    def directory(self) -> StationDirectory:
        return self._dir

    def catalogue_provenance(self) -> DataProvenance:
        return DataProvenance(mode=self.catalogue_mode, source=CATALOGUE_SOURCE, as_of=self._loaded_at,
                              note="Stations RailSaathi can show boards for, bundled with the app (not fetched live). "
                                   "Coordinates are approximate.")

    def _now(self) -> datetime:
        return self._clock.now().astimezone(self._tz)

    def _origin(self, station_code: str) -> StationPoint:
        origin = self._dir.get(station_code)
        if origin is None:
            raise UnknownStation(station_code)
        return origin

    def _window(self, hours: int) -> tuple[datetime, datetime]:
        """[now, now + hours], clipped at midnight: boards cover today's departures only."""
        now = self._now()
        midnight = datetime.combine(now.date() + timedelta(days=1), time(0), tzinfo=self._tz)
        return now, min(now + timedelta(hours=hours), midnight)

    def _unavailable(self, reason: str) -> DataProvenance:
        return DataProvenance(mode=DataMode.UNAVAILABLE, source=self.source, as_of=self._now(), note=reason)

    def _unavailable_board(self, origin: StationPoint, hours: int, reason: str,
                           neighbours: list[StationPoint] | None = None) -> DepartureBoard:
        start, end = self._window(hours)
        return DepartureBoard(station=_ref(origin), window_start=start, window_end=end,
                              neighbours_checked=[_ref(n) for n in neighbours or []], complete=False,
                              provenance=self._unavailable(reason), reason=reason)

    def _unavailable_schedule(self, train_no: str, reason: str) -> TrainSchedule:
        return TrainSchedule(train_no=train_no, provenance=self._unavailable(reason), reason=reason)

    def _unavailable_status(self, train_no: str, run_date: date, reason: str) -> TrainLiveStatus:
        return TrainLiveStatus(train_no=train_no, run_date=run_date, provenance=self._unavailable(reason),
                               reason=reason)


class RailRadarLiveSource(_Base):
    """Departure board = cached `trains_between(station, neighbour, today)` for the nearest catalogue stations in
    other cities, plus (cached) running status for the first few departures. Labelled `cached` with the oldest
    `as_of`, or `stale` when the quota forced an expired cached response. Uses the planner's client instance, so
    the quota and cache are shared with journey search."""

    def __init__(self, client: RailRadarClient, directory: StationDirectory, clock: Clock,
                 tz: str = "Asia/Kolkata", neighbours: int = 3, status_limit: int = 3,
                 max_concurrency: int = 4, timeout_seconds: float = 30.0) -> None:
        super().__init__(directory, clock, tz)
        self._client = client
        self._k = neighbours
        self._status_limit = status_limit
        self._workers = max_concurrency
        self._timeout = timeout_seconds

    def departures(self, station_code: str, hours: int) -> DepartureBoard:
        origin = self._origin(station_code)
        neighbours = self._dir.neighbours(origin.code, self._k)
        if not neighbours:
            return self._unavailable_board(origin, hours, "RailSaathi has no neighbouring catalogue stations with "
                                                          "known locations for this station, so it cannot build a board.")
        try:
            return run_sync(self._board(origin, neighbours, hours), self._timeout)
        except ProviderError as err:
            log.warning("Live board for %s unavailable (%s)", origin.code, err.kind.value)
            return self._unavailable_board(origin, hours, reason_for(err), neighbours)

    async def _board(self, origin: StationPoint, neighbours: list[StationPoint], hours: int) -> DepartureBoard:
        start, end = self._window(hours)
        day = start.date()
        gate = asyncio.Semaphore(self._workers)

        async def between(n: StationPoint):
            async with gate:
                return await self._client.trains_between(origin.code, n.code, day)

        results = await asyncio.gather(*(between(n) for n in neighbours), return_exceptions=True)
        errors: list[ProviderError] = []
        fetched_times: list[datetime] = []
        stale = False
        found: dict[str, Departure] = {}
        names = {origin.code: origin.name, **{n.code: n.name for n in neighbours}}
        placeholder = self._unavailable("placeholder")  # map_train needs one; never returned
        for neighbour, result in zip(neighbours, results):
            if isinstance(result, ProviderError):
                errors.append(result)
                continue
            if isinstance(result, BaseException):
                raise result
            fetched_times.append(result.fetched_at)
            stale = stale or result.mode is DataMode.STALE
            for raw in result.data:
                try:
                    option = map_train(raw, origin.code, neighbour.code, day, self._tz, placeholder, names)
                except (MappingError, ValueError):
                    continue
                leg = option.legs[0]
                if leg.from_code != origin.code or not (start <= leg.departure <= end):
                    continue  # departs from another station of the pair, or outside the window
                entry = found.get(leg.train_no)
                if entry is None:
                    found[leg.train_no] = Departure(train_no=leg.train_no, train_name=leg.train_name,
                                                    scheduled_departure=leg.departure, towards=[_ref(neighbour)])
                elif all(t.code != neighbour.code for t in entry.towards):
                    entry.towards.append(_ref(neighbour))
        if not fetched_times:
            errors.sort(key=lambda e: _REASON_PRIORITY.index(e.kind) if e.kind in _REASON_PRIORITY else 99)
            raise errors[0]
        departures = sorted(found.values(), key=lambda d: (d.scheduled_departure, d.train_no))
        status_times = await self._attach_status(departures[: self._status_limit], day)
        as_of = min(fetched_times + status_times).astimezone(self._tz)
        note = (f"Built from cached RailRadar 'trains between stations' results for {len(neighbours)} nearby "
                f"catalogue stations, so only direct trains to those stations are listed. Running status is shown "
                f"for at most {self._status_limit} trains. " + RAILRADAR_NOTE)
        if errors:
            note = "INCOMPLETE: some nearby-station queries failed, so trains may be missing. " + note
        if stale:
            note = "STALE: the request quota is used up, so an older cached response is shown. " + note
        provenance = DataProvenance(mode=DataMode.STALE if stale else DataMode.CACHED, source=RAILRADAR_SOURCE,
                                    as_of=as_of, note=note)
        return DepartureBoard(station=_ref(origin), window_start=start, window_end=end,
                              neighbours_checked=[_ref(n) for n in neighbours], complete=not errors,
                              departures=departures, provenance=provenance)

    async def _attach_status(self, departures: list[Departure], day: date) -> list[datetime]:
        """Fill delay/cancelled for the given departures; failures leave them unknown (None)."""
        results = await asyncio.gather(*(self._client.live_status(d.train_no, day, use_cache=True)
                                         for d in departures), return_exceptions=True)
        times = []
        for dep, result in zip(departures, results):
            if isinstance(result, ProviderError):
                continue
            if isinstance(result, BaseException):
                raise result
            if not result.data:
                continue
            delay, cancelled = map_live_status(result.data)
            dep.delay_minutes, dep.cancelled = delay, cancelled
            dep.status_as_of = result.fetched_at.astimezone(self._tz)
            times.append(result.fetched_at)
        return times

    def schedule(self, train_no: str) -> TrainSchedule:
        # The RailRadar schedule endpoint's shape has not been verified, so nothing is guessed.
        return self._unavailable_schedule(train_no, SCHEDULE_UNSUPPORTED)

    def live_status(self, train_no: str, run_date: date) -> TrainLiveStatus:
        try:
            fetched = run_sync(self._client.live_status(train_no, run_date), self._timeout)
        except ProviderError as err:
            log.warning("Live status for %s unavailable (%s)", train_no, err.kind.value)
            return self._unavailable_status(train_no, run_date, reason_for(err))
        if not fetched.data:
            return self._unavailable_status(train_no, run_date,
                                            "The live data provider returned no running status for this train "
                                            "and date.")
        delay, cancelled = map_live_status(fetched.data)
        mode = fetched.mode  # LIVE when fetched now, CACHED/STALE when a cached response was served
        provenance = DataProvenance(mode=mode, source=RAILRADAR_SOURCE,
                                    as_of=fetched.fetched_at.astimezone(self._tz), note=RAILRADAR_NOTE)
        return TrainLiveStatus(train_no=train_no, run_date=run_date, delay_minutes=delay, cancelled=cancelled,
                               provenance=provenance)


NTES_BOARD_NOTE = ("Station board as published by NTES for the next hours (trains that end here are left out). "
                   + NTES_NOTE)
NTES_NOT_FOUND = "NTES has no data for this request."


class NtesLiveSource(_Base):
    """Boards, schedules and running status from NTES (unofficial client). One NTES call per board, so no
    neighbour fan-out is needed. Labelled `live` when fetched for this request, `cached` when a recent copy is
    reused and `stale` when an older copy is served because the request budget is used up or NTES failed."""

    source = NTES_SOURCE

    def __init__(self, client: NtesClient, directory: StationDirectory, clock: Clock, tz: str = "Asia/Kolkata",
                 timeout_seconds: float = 15.0) -> None:
        super().__init__(directory, clock, tz)
        self._client = client
        self._timeout = timeout_seconds

    def _label(self, code: str, ntes_name) -> str:
        point = self._dir.get(code)
        return point.name if point else station_label(code, ntes_name, {})

    @staticmethod
    def _reason(err: ProviderError) -> str:
        return NTES_NOT_FOUND if isinstance(err, NtesAlert) else reason_for(err)

    def _provenance(self, fetched, note: str) -> DataProvenance:
        return DataProvenance(mode=fetched.mode, source=NTES_SOURCE,
                              as_of=fetched.fetched_at.astimezone(self._tz), note=ntes_note_for(fetched.mode, note))

    def departures(self, station_code: str, hours: int) -> DepartureBoard:
        origin = self._origin(station_code)
        start, end = self._window(hours)
        try:
            # NTES boards cover the next 2 or 4 hours; the window is cut to the asked hours below.
            fetched = run_sync(self._client.station_live(origin.code, 2 if hours <= 2 else 4), self._timeout)
        except ProviderError as err:
            log.warning("NTES board for %s unavailable (%s)", origin.code, err.kind.value)
            return self._unavailable_board(origin, hours, self._reason(err))
        found: dict[str, Departure] = {}
        as_of = fetched.fetched_at.astimezone(self._tz)
        for raw in fetched.data.get("TrainsAtStation") or []:
            entry = map_board_entry(raw, start) if isinstance(raw, dict) else None
            if entry is None or entry["train_no"] in found:
                continue
            scheduled = entry["scheduled_departure"]
            expected = scheduled + timedelta(minutes=entry["delay_minutes"] or 0)
            # Scheduled in the window, or scheduled earlier but running late and still to leave in the window.
            if not (scheduled <= end and (scheduled >= start or (expected >= start and not entry["cancelled"]))):
                continue
            dest = entry["destination"]
            found[entry["train_no"]] = Departure(
                train_no=entry["train_no"], train_name=entry["train_name"], scheduled_departure=scheduled,
                towards=[StationRef(code=dest, name=self._label(dest, entry["destination_name"]))] if dest else [],
                delay_minutes=entry["delay_minutes"], cancelled=entry["cancelled"], status_as_of=as_of)
        departures = sorted(found.values(), key=lambda d: (d.scheduled_departure, d.train_no))
        return DepartureBoard(station=_ref(origin), window_start=start, window_end=end, complete=True,
                              departures=departures, provenance=self._provenance(fetched, NTES_BOARD_NOTE))

    def schedule(self, train_no: str) -> TrainSchedule:
        try:
            fetched = run_sync(self._client.schedule(train_no), self._timeout)
        except ProviderError as err:
            log.warning("NTES schedule for %s unavailable (%s)", train_no, err.kind.value)
            return self._unavailable_schedule(train_no, self._reason(err))
        name, stops = map_schedule(fetched.data, {})
        if not stops:
            return self._unavailable_schedule(train_no, NTES_NOT_FOUND)
        return TrainSchedule(
            train_no=train_no, train_name=name,
            stops=[ScheduleStop(**{**stop, "station_name": self._label(stop["station_code"], stop["station_name"])})
                   for stop in stops],
            provenance=self._provenance(fetched, NTES_NOTE))

    def live_status(self, train_no: str, run_date: date) -> TrainLiveStatus:
        """`run_date` is used as the date the run left its origin (how NTES identifies a run)."""
        try:
            fetched = run_sync(self._client.live_status(train_no, run_date), self._timeout)
        except NtesAlert as alert:
            if alert.cancelled:
                return TrainLiveStatus(train_no=train_no, run_date=run_date, cancelled=True,
                                       provenance=DataProvenance(mode=DataMode.LIVE, source=NTES_SOURCE,
                                                                 as_of=self._now(), note=NTES_NOTE))
            return self._unavailable_status(train_no, run_date,
                                            "NTES has no running status for this train and date.")
        except ProviderError as err:
            log.warning("NTES live status for %s unavailable (%s)", train_no, err.kind.value)
            return self._unavailable_status(train_no, run_date, reason_for(err))
        delay, cancelled = map_live(fetched.data)
        if delay is None and cancelled is None:
            return self._unavailable_status(train_no, run_date,
                                            "NTES returned no running status for this train and date.")
        return TrainLiveStatus(train_no=train_no, run_date=run_date, delay_minutes=delay, cancelled=cancelled,
                               provenance=self._provenance(fetched, NTES_NOTE))


class DemoLiveSource(_Base):
    """Simulated boards, schedules and running status from the bundled demo dataset. Every answer is labelled
    `demo`. The container never builds this when APP_ENV=production."""

    source = DEMO_SOURCE
    catalogue_mode = DataMode.DEMO

    def __init__(self, directory: StationDirectory, clock: Clock, tz: str = "Asia/Kolkata") -> None:
        super().__init__(directory, clock, tz)
        journeys = json.loads((DATA_DIR / "journeys.json").read_text(encoding="utf-8"))
        events = json.loads((DATA_DIR / "disruptions.json").read_text(encoding="utf-8"))["events"]
        self._legs = [leg for service in journeys["services"] for leg in service["legs"]]
        self._as_of = datetime.fromisoformat(journeys["as_of"])
        self._events = {e["train_no"]: e for e in events}

    def _demo(self) -> DataProvenance:
        return DataProvenance(mode=DataMode.DEMO, source=DEMO_SOURCE, as_of=self._as_of, note=DEMO_NOTE)

    def _name(self, code: str) -> str:
        point = self._dir.get(code)
        return point.name if point else code

    def departures(self, station_code: str, hours: int) -> DepartureBoard:
        origin = self._origin(station_code)
        start, end = self._window(hours)
        found: dict[str, Departure] = {}
        for leg in self._legs:
            if leg["from"] != origin.code:
                continue
            hh, mm = (int(p) for p in leg["dep"].split(":"))
            when = datetime.combine(start.date(), time(hh, mm), tzinfo=self._tz)
            if not (start <= when <= end) or leg["train_no"] in found:
                continue
            event = self._events.get(leg["train_no"])
            found[leg["train_no"]] = Departure(
                train_no=leg["train_no"], train_name=leg["name"], scheduled_departure=when,
                towards=[StationRef(code=leg["to"], name=self._name(leg["to"]))],
                delay_minutes=int(event["delay_minutes"]) if event and event["type"] == "delay" else None,
                cancelled=(event["type"] == "cancellation") if event else None,
                status_as_of=self._as_of if event else None)
        departures = sorted(found.values(), key=lambda d: (d.scheduled_departure, d.train_no))
        return DepartureBoard(station=_ref(origin), window_start=start, window_end=end, complete=True,
                              departures=departures, provenance=self._demo())

    def schedule(self, train_no: str) -> TrainSchedule:
        legs = [leg for leg in self._legs if leg["train_no"] == train_no]
        if not legs:
            return self._unavailable_schedule(train_no, "This train is not in the bundled timetable.")
        first = legs[0]
        stops = [ScheduleStop(station_code=first["from"], station_name=self._name(first["from"]),
                              departure=first["dep"], day_offset=first["dep_day"]),
                 ScheduleStop(station_code=first["to"], station_name=self._name(first["to"]),
                              arrival=first["arr"], day_offset=first["arr_day"])]
        return TrainSchedule(train_no=train_no, train_name=first["name"], stops=stops, provenance=self._demo())

    def live_status(self, train_no: str, run_date: date) -> TrainLiveStatus:
        event = self._events.get(train_no)
        if event is None:
            return self._unavailable_status(train_no, run_date,
                                            "The bundled timetable has no simulated running status for this train.")
        cancelled = event["type"] == "cancellation"
        return TrainLiveStatus(train_no=train_no, run_date=run_date, cancelled=cancelled,
                               delay_minutes=None if cancelled else int(event["delay_minutes"]),
                               provenance=self._demo())


class UnavailableLiveSource(_Base):
    """Live data cannot be served (no RailRadar key, or demo refused in production). Station search still works
    from the catalogue; every board, schedule and status is `unavailable` with the reason."""

    def __init__(self, directory: StationDirectory, clock: Clock, reason: str, tz: str = "Asia/Kolkata") -> None:
        super().__init__(directory, clock, tz)
        self._reason = reason

    def departures(self, station_code: str, hours: int) -> DepartureBoard:
        return self._unavailable_board(self._origin(station_code), hours, self._reason)

    def schedule(self, train_no: str) -> TrainSchedule:
        return self._unavailable_schedule(train_no, self._reason)

    def live_status(self, train_no: str, run_date: date) -> TrainLiveStatus:
        return self._unavailable_status(train_no, run_date, self._reason)
