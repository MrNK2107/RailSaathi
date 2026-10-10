"""Journey request model: what the passenger wants (constraints + preferences)."""

import hashlib
import json
from datetime import date

from pydantic import BaseModel, Field

from app.domain.enums import (
    BudgetPriority,
    DateAnchor,
    FieldSource,
    PassengerNeed,
    TransferPreference,
    TravelClass,
)


class Place(BaseModel):
    """A resolved location: either a whole city (any station) or a single station."""

    id: str
    label: str
    kind: str = Field(pattern="^(city|station)$")
    station_codes: list[str]


class TimeWindow(BaseModel):
    start: str = Field(pattern=r"^\d{2}:\d{2}$")
    end: str = Field(pattern=r"^\d{2}:\d{2}$")
    label: str | None = None


class JourneyDetails(BaseModel):
    origin: Place | None = None
    destination: Place | None = None
    journey_date: date | None = None
    date_anchor: DateAnchor = DateAnchor.DEPARTURE
    passenger_count: int | None = None
    arrival_deadline: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    deadline_strict: bool = True
    departure_window: TimeWindow | None = None
    budget_limit: float | None = None
    budget_strict: bool = False
    budget_priority: BudgetPriority | None = None
    class_preference: TravelClass | None = None
    class_strict: bool = False
    passenger_needs: list[PassengerNeed] = Field(default_factory=list)
    assistance_mandatory: bool = False
    transfer_preference: TransferPreference | None = None
    transfer_strict: bool = False
    field_sources: dict[str, FieldSource] = Field(default_factory=dict)

    def constraints_hash(self) -> str:
        """Stable fingerprint of everything that affects search/ranking."""
        payload = self.model_dump(mode="json", exclude={"field_sources"})
        raw = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


REQUIRED_FIELDS: tuple[str, ...] = ("origin", "destination", "journey_date", "passenger_count")
