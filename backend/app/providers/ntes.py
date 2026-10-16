"""Journey search and live disruptions from NTES through the unofficial `ntes-client` (see ntes_client.py).

Implements JourneyProvider and DisruptionSource, so the conversational planner, the goal planner, ranking and the
API need no changes. Stations come from the bundled catalogue; facility data is not provided, so every need is
`unknown`. NTES gives no fares, so options carry none (the UI says "Fare: check on IRCTC")."""

import asyncio
import logging
import threading
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.domain.enums import DataMode
from app.domain.options import DataProvenance, JourneyOption
from app.infra.async_bridge import run_sync
from app.providers.base import CityRecord, DisruptionEvent, StationRecord
from app.providers.errors import ProviderError, ProviderErrorKind
from app.providers.ntes_client import SOURCE, NtesAlert, NtesClient
from app.providers.ntes_mapper import map_between, map_live, runs_on
from app.providers.railradar import load_catalogue
from app.providers.railradar_mapper import MappingError

log = logging.getLogger("railsaathi.ntes")
NOTE = ("Live data from NTES (National Train Enquiry System) through ntes-client, an unofficial client of the NTES "
        "app backend: not an official or authorised integration, and it can stop working at any time. Timings are "
        "as NTES publishes them; fares and seat availability are not provided; only direct trains are searched. "
        "Verify on the official NTES or IRCTC before travel.")
STALE_NOTE = ("STALE: NTES could not be asked just now (RailSaathi's request budget is used up or NTES failed), so "
              "an earlier response is shown and may be out of date. ")
CACHED_NOTE = "CACHED: a recent NTES response reused from cache (fetched at the time shown). "
_ERROR_PRIORITY = [ProviderErrorKind.RATE_LIMITED, ProviderErrorKind.NOT_CONFIGURED, ProviderErrorKind.AUTH_FAILED,
                   ProviderErrorKind.TIMEOUT, ProviderErrorKind.UNAVAILABLE, ProviderErrorKind.BAD_RESPONSE,
                   ProviderErrorKind.BAD_REQUEST, ProviderErrorKind.NOT_FOUND]


def note_for(mode: DataMode, base: str = NOTE) -> str:
    if mode is DataMode.STALE:
        return STALE_NOTE + base
    return CACHED_NOTE + base if mode is DataMode.CACHED else base


def _partial_note(missed: list[tuple[str, str]]) -> str:
    listed = ", ".join(f"{o} to {d}" for o, d in missed)
    return (f"PARTIAL: not every station search ran (RailSaathi's NTES request budget or an error), so trains from "
            f"these searches may be missing: {listed}. ")


class NtesJourneyProvider:
    def __init__(self, client: NtesClient, tz: str = "Asia/Kolkata", max_concurrency: int = 4,
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
    def client(self) -> NtesClient:
        """The shared client (one quota and cache) so live boards reuse it."""
        return self._client

    def provenance(self, fetched_at: datetime | None = None, mode: DataMode = DataMode.LIVE) -> DataProvenance:
        """as_of is when NTES was actually asked (cached responses keep their original time)."""
        as_of = (fetched_at or datetime.now(self._tz)).astimezone(self._tz)
        return DataProvenance(mode=mode, source=SOURCE, as_of=as_of, note=note_for(mode))

    def cities(self) -> list[CityRecord]:
        return list(self._cities)

    def stations(self) -> list[StationRecord]:
        return list(self._stations.values())

    def station(self, code: str) -> StationRecord | None:
        return self._stations.get(code)  # facilities={} -> every need is Verification.UNKNOWN

    def search(self, origin_codes: list[str], destination_codes: list[str],
               departure_dates: list[date]) -> list[JourneyOption]:
        return run_sync(self._search(origin_codes, destination_codes, departure_dates), self._budget)

    async def _plan_jobs(self, origin_codes: list[str],
                         destination_codes: list[str]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """Station pairs, primary stations first (the resolver lists a place's main station first), and no more
        uncached calls than the request budget has free right now. NTES answers are not date specific, so one
        call per pair serves every searched date. Returns (to run, skipped)."""
        ranked = sorted(((oi + di, oi, (o, d)) for oi, o in enumerate(origin_codes)
                         for di, d in enumerate(destination_codes) if o != d), key=lambda item: item[:2])
        free = await self._client.quota_remaining()
        run, skipped = [], []
        for *_, pair in ranked:
            cached = await self._client.trains_between_cached(*pair)
            if cached == "fresh":
                run.append(pair)
            elif free > 0:
                run.append(pair)
                free -= 1
            elif cached == "stale":
                run.append(pair)  # the budget refuses it and the client serves the stale copy, labelled STALE
            else:
                skipped.append(pair)
        return run, skipped

    async def _search(self, origin_codes: list[str], destination_codes: list[str],
                      departure_dates: list[date]) -> list[JourneyOption]:
        jobs, skipped = await self._plan_jobs(origin_codes, destination_codes)
        gate = asyncio.Semaphore(self._workers)
        origins, dests = set(origin_codes), set(destination_codes)

        async def bounded(pair: tuple[str, str]) -> list[JourneyOption]:
            async with gate:
                return await self._search_pair(*pair, departure_dates, origins, dests)

        results = await asyncio.gather(*(bounded(job) for job in jobs), return_exceptions=True)
        errors: list[ProviderError] = []
        missed = list(skipped)
        seen: dict[str, JourneyOption] = {}
        for job, result in zip(jobs, results):
            if isinstance(result, ProviderError):
                if isinstance(result, NtesAlert):
                    continue  # NTES has no trains for this pair: an answer, not a failure
                errors.append(result)
                missed.append(job)
                continue
            if isinstance(result, BaseException):
                raise result
            for option in result:
                seen.setdefault(option.option_id, option)  # NTES lists the same train for several pairs
        if skipped:
            log.warning("NTES budget allowed %d of %d searches; skipped %d", len(jobs), len(jobs) + len(skipped),
                        len(skipped))
        options = sorted(seen.values(), key=lambda o: (o.departure, o.option_id))
        if not missed:
            return options
        if not options:
            if errors:
                raise min(errors, key=lambda e: _ERROR_PRIORITY.index(e.kind))
            raise ProviderError(ProviderErrorKind.RATE_LIMITED, "RailSaathi's NTES request budget is used up")
        prefix = _partial_note(sorted(missed))
        return [o.model_copy(update={"provenance": o.provenance.model_copy(
            update={"note": prefix + o.provenance.note})}) for o in options]

    async def _search_pair(self, origin: str, dest: str, days: list[date], origins: set[str],
                           dests: set[str]) -> list[JourneyOption]:
        fetched = await self._client.trains_between(origin, dest)
        provenance = self.provenance(fetched.fetched_at, fetched.mode)
        options, unusable, elsewhere = [], 0, 0
        for raw in fetched.data:
            if not isinstance(raw, dict):
                unusable += 1
                continue
            frm = str(raw.get("FromStation") or "").upper()
            to = str(raw.get("toStation") or raw.get("ToStation") or "").upper()
            if frm not in origins or to not in dests:
                elsewhere += 1  # another station of the NTES station group, not one the passenger's places use
                continue
            for day in days:
                running = runs_on(raw.get("DayOfRun"), day)
                if running is None:
                    unusable += 1
                    break
                if not running:
                    continue
                try:
                    options.append(map_between(raw, day, self._tz, provenance, self._names))
                except (MappingError, ValueError):
                    unusable += 1
                    break
        if unusable and not options and not elsewhere:
            raise ProviderError(ProviderErrorKind.BAD_RESPONSE, "NTES returned trains in a format RailSaathi does "
                                                                "not understand (see scripts/ntes_smoke.py)")
        if unusable:
            log.warning("Skipped %d unusable NTES records for %s-%s", unusable, origin, dest)
        return options


class NtesDisruptionSource:
    """Turns NTES running status into disruption events for the trains in a plan. NTES identifies a run by the date
    it left its origin; the plan's boarding date is used as that date (exact for trains boarded on their first
    day, see docs/LIMITATIONS.md)."""

    def __init__(self, client: NtesClient, tz: str = "Asia/Kolkata", budget_seconds: float = 15.0) -> None:
        self._client = client
        self._tz = ZoneInfo(tz)
        self._budget = budget_seconds
        self._events: dict[str, DisruptionEvent] = {}
        self._lock = threading.Lock()

    def list_events(self) -> list[DisruptionEvent]:
        with self._lock:
            return list(self._events.values())

    def get_event(self, event_id: str) -> DisruptionEvent | None:
        with self._lock:
            return self._events.get(event_id)

    def events_for_trains(self, trains: list[tuple[str, date]]) -> list[DisruptionEvent]:
        return run_sync(self._events_for_trains(trains), self._budget)

    async def _status(self, train_no: str, day: date) -> tuple[int | None, bool | None, datetime, DataMode] | None:
        try:
            fetched = await self._client.live_status(train_no, day)
        except NtesAlert as alert:
            # A cancellation alert is a real answer; any other alert means NTES has no status for this run.
            return (None, True, datetime.now(self._tz), DataMode.LIVE) if alert.cancelled else None
        delay, cancelled = map_live(fetched.data)
        return delay, cancelled, fetched.fetched_at, fetched.mode

    async def _events_for_trains(self, trains: list[tuple[str, date]]) -> list[DisruptionEvent]:
        pairs = list(dict.fromkeys(trains))
        statuses = await asyncio.gather(*(self._status(n, d) for n, d in pairs))
        events: list[DisruptionEvent] = []
        for (train_no, day), status in zip(pairs, statuses):
            if status is None:
                continue
            delay, cancelled, fetched_at, mode = status
            if not cancelled and not delay:
                continue
            events.append(DisruptionEvent(
                id=f"LIVE-{train_no}-{day.isoformat()}",
                type="cancellation" if cancelled else "delay",
                train_no=train_no,
                delay_minutes=0 if cancelled else int(delay or 0),
                label=(f"Live (NTES, unofficial client): train {train_no} reported cancelled" if cancelled
                       else f"Live (NTES, unofficial client): train {train_no} running {delay} min late"),
                simulated=False,
                provenance=DataProvenance(mode=mode, source=SOURCE, as_of=fetched_at.astimezone(self._tz),
                                          note=note_for(mode)),
            ))
        with self._lock:
            self._events.update({e.id: e for e in events})
        return events
