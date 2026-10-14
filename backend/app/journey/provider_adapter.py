"""The goal planner's only source of trains: the container's `JourneyProvider`.

Maps `JourneyProvider.search()` results (`JourneyOption` + `DataProvenance`) into the goal planner's leg model
(`TrainCandidate`). One journey data path: the same provider, cache, quota and provenance as the conversational
planner. Provider failures become an `unavailable` provenance with a reason, never substitute data."""

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol
from zoneinfo import ZoneInfo

from app.clock import Clock
from app.domain.enums import DataMode
from app.domain.options import DataProvenance, JourneyOption
from app.journey.models import TrainCandidate, TrainLeg
from app.providers.errors import ProviderError, ProviderErrorKind

log = logging.getLogger("railsaathi.journey.provider")

UNAVAILABLE_NOTES = {
    ProviderErrorKind.NOT_CONFIGURED: "The live train data source is not configured, so no trains can be shown.",
    ProviderErrorKind.RATE_LIMITED: "The live train data source is rate limited right now. Try again in a minute.",
    ProviderErrorKind.TIMEOUT: "The live train data source did not respond in time. Try again shortly.",
    ProviderErrorKind.AUTH_FAILED: "The live train data source rejected our credentials, so no trains can be shown.",
}
DEFAULT_UNAVAILABLE_NOTE = "Train data could not be retrieved right now, so no trains can be shown."


class _Searchable(Protocol):
    def search(self, origin_codes: list[str], destination_codes: list[str],
               departure_dates: list[date]) -> list[JourneyOption]: ...

    def provenance(self) -> DataProvenance: ...


@dataclass
class SearchResult:
    candidates: list[TrainCandidate] = field(default_factory=list)
    provenance: DataProvenance | None = None
    error: str | None = None  # ProviderErrorKind value when the provider failed


def option_to_candidate(option: JourneyOption) -> TrainCandidate:
    legs = [
        TrainLeg(train_number=leg.train_no, train_name=leg.train_name, from_code=leg.from_code,
                 from_name=leg.from_name, to_code=leg.to_code, to_name=leg.to_name,
                 departure=leg.departure, arrival=leg.arrival)
        for leg in option.legs
    ]
    fares = {str(cls): float(v) for cls, v in option.fares.items()}
    classes = [str(c) for c in option.classes] or list(fares)
    return TrainCandidate(
        option_id=option.option_id, legs=legs, departure=option.departure, arrival=option.arrival,
        duration_minutes=option.duration_minutes, transfers=option.transfers, classes=classes, fares=fares,
        provenance=option.provenance,
    )


def set_provenance(options: list[JourneyOption], fallback: DataProvenance) -> DataProvenance:
    """The oldest provenance among the options used (a stale or cached answer is reported as such)."""
    if not options:
        return fallback
    stale = [o for o in options if o.provenance.mode == DataMode.STALE]
    pool = stale or options
    return min(pool, key=lambda o: o.provenance.as_of).provenance


class ProviderJourneyAdapter:
    def __init__(self, provider: _Searchable, tz: str, clock: Clock) -> None:
        self._provider = provider
        self._clock = clock
        self._tz = ZoneInfo(tz)

    def unavailable(self, kind: ProviderErrorKind | None) -> DataProvenance:
        try:
            source = self._provider.provenance().source
        except Exception:  # noqa: BLE001 - the provenance of a broken provider is still "unavailable"
            source = "railway data provider"
        return DataProvenance(mode=DataMode.UNAVAILABLE, source=source, as_of=self._clock.now(),
                              note=UNAVAILABLE_NOTES.get(kind, DEFAULT_UNAVAILABLE_NOTE) if kind else
                              DEFAULT_UNAVAILABLE_NOTE)

    def search(self, origin_codes: list[str], destination_codes: list[str],
               departure_dates: list[date]) -> SearchResult:
        try:
            options = self._provider.search(origin_codes, destination_codes, departure_dates)
        except ProviderError as err:
            log.warning("Goal planner search failed: %s", err.kind.value)
            return SearchResult(provenance=self.unavailable(err.kind), error=err.kind.value)
        wanted = set(departure_dates)
        # Departure-date (and therefore day-of-week) filter: only trains that actually depart on a searched date.
        used = [o for o in options if o.departure.astimezone(self._tz).date() in wanted]
        return SearchResult(candidates=[option_to_candidate(o) for o in used],
                            provenance=set_provenance(used, self._provider.provenance()))
