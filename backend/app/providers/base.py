"""Data-provider interfaces.

Teammates can plug in an authorised railway data source by implementing these
protocols; the planner, ranking and disruption services depend only on them.
"""

from datetime import date
from typing import Protocol

from pydantic import BaseModel, Field

from app.domain.enums import DataMode, PassengerNeed, Verification
from app.domain.options import DataProvenance, JourneyOption


class CityRecord(BaseModel):
    id: str
    label: str
    aliases: list[str]
    stations: list[str]


class StationRecord(BaseModel):
    code: str
    name: str
    city: str
    aliases: list[str]
    facilities: dict[PassengerNeed, Verification]


class DisruptionEvent(BaseModel):
    id: str
    type: str  # "delay" | "cancellation"
    train_no: str
    delay_minutes: int
    label: str  # English
    simulated: bool
    labels: dict[str, str] = Field(default_factory=dict)  # the label per language code ("en", "ta"), when known
    provenance: DataProvenance


class JourneyProvider(Protocol):
    @property
    def data_mode(self) -> DataMode: ...

    def cities(self) -> list[CityRecord]: ...

    def stations(self) -> list[StationRecord]: ...

    def station(self, code: str) -> StationRecord | None: ...

    def search(
        self, origin_codes: list[str], destination_codes: list[str], departure_dates: list[date]
    ) -> list[JourneyOption]: ...

    def provenance(self) -> DataProvenance: ...


class DisruptionSource(Protocol):
    def list_events(self) -> list[DisruptionEvent]: ...

    def get_event(self, event_id: str) -> DisruptionEvent | None: ...

    # Optional for live sources: `events_for_trains(trains: list[tuple[str, date]]) -> list[DisruptionEvent]`
    # fetches current status for specific trains. DisruptionService uses it when present.
