"""Journey options returned by data providers and the recommendations built from them."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.enums import (
    CheckStatus,
    DataMode,
    PassengerNeed,
    RecommendationCategory,
    TravelClass,
    Verification,
)


class DataProvenance(BaseModel):
    mode: DataMode
    source: str
    as_of: datetime
    note: str  # English, for API clients
    # Stable codes for the parts of `note`, in order (e.g. ["ntes_cached", "ntes"]), so the UI can show the note in
    # the passenger's language; it falls back to `note` when a code is unknown or there are none.
    note_codes: list[str] = Field(default_factory=list)
    note_params: dict[str, str] = Field(default_factory=dict)  # values for {placeholders} in the coded texts


class Leg(BaseModel):
    train_no: str
    train_name: str
    from_code: str
    from_name: str
    to_code: str
    to_name: str
    departure: datetime
    arrival: datetime


class JourneyOption(BaseModel):
    option_id: str
    legs: list[Leg]
    departure: datetime
    arrival: datetime
    duration_minutes: int
    transfers: int
    min_transfer_minutes: int | None = None
    fares: dict[TravelClass, float] = Field(default_factory=dict)  # listed fare per passenger; empty = unknown
    classes: list[TravelClass] = Field(default_factory=list)  # classes offered (may be known without fares)
    station_codes: list[str]  # every station the passenger boards/alights at
    provenance: DataProvenance
    simulated_change: str | None = None  # set when a simulated disruption altered it


class ConstraintCheck(BaseModel):
    name: str
    status: CheckStatus
    detail: str


class NeedStatus(BaseModel):
    need: PassengerNeed
    status: Verification
    detail: str


class Recommendation(BaseModel):
    option: JourneyOption
    labels: list[RecommendationCategory]
    rank: int
    score: float
    score_breakdown: dict[str, float]
    selected_class: TravelClass | None  # None when the class cannot be determined from the data
    fare_per_passenger: float | None  # None when the data source has no fare
    total_fare: float | None
    fully_compliant: bool
    hard_constraints: list[ConstraintCheck]
    need_statuses: list[NeedStatus] = Field(default_factory=list)
    preference_matches: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    unverified: list[str] = Field(default_factory=list)
    explanation: str


class ExcludedOption(BaseModel):
    option_id: str
    summary: str
    reasons: list[str]


class RelaxSuggestion(BaseModel):
    constraint: str
    excluded_count: int
    message: str


class RecommendationSet(BaseModel):
    constraints_hash: str
    computed_at: datetime
    considered_count: int
    eligible_count: int
    recommendations: list[Recommendation]
    excluded: list[ExcludedOption]
    relax_suggestions: list[RelaxSuggestion] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)  # e.g. why a cheaper option was excluded
    limitations: list[str] = Field(default_factory=list)
    provenance: DataProvenance
