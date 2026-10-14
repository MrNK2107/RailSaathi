"""
RailSaathi AI — goal planner data models.

Strictly typed Pydantic models for goal-based journey planning: requirements, the leg model the provider
adapter maps `JourneyOption`s into, feasibility evaluations and booking handoffs. Every plan response carries
the shared `DataProvenance`.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.config import Settings
from app.domain.enums import TravelClass
from app.domain.options import DataProvenance

HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"
TRAIN_QUERY_MAX = 80
PLACE_MAX = 120
# Schema cap for free-text prompts: the default of Settings.max_message_chars. The configured (possibly lower)
# limit is enforced per request by enforce_message_limit.
MAX_PROMPT_CHARS: int = Settings.model_fields["max_message_chars"].default
PLAN_ID_PATTERN = r"^plan_[A-Za-z0-9_-]{8,64}$"


class TripRequirements(BaseModel):
    """Complete requirements for one goal plan. Nothing here is defaulted from hidden constants: origin, date and
    time come from the passenger (form fields or the parsed prompt)."""

    origin: str = Field(min_length=1, max_length=PLACE_MAX)
    destination_venue: str | None = Field(default=None, max_length=PLACE_MAX)
    destination_station: str | None = Field(default=None, max_length=PLACE_MAX)
    meeting_date: date
    meeting_time: str = Field(pattern=HHMM)
    required_arrival_buffer_minutes: int = Field(default=45, ge=0, le=720)
    preferred_train_name_or_number: str | None = Field(default=None, max_length=TRAIN_QUERY_MAX)
    preferred_class: TravelClass | None = None
    budget_max: float | None = Field(default=None, ge=0)
    maximum_journey_duration_minutes: int | None = Field(default=None, ge=0)
    hard_constraints: list[str] = Field(default_factory=lambda: ["deadline", "arrival_buffer"])
    assumptions: list[str] = Field(default_factory=list)


class ResolvedPlace(BaseModel):
    """Where an origin or destination resolved to and which station codes it searches."""

    query: str
    display_name: str
    kind: Literal["venue", "station", "city"]
    city: str | None = None
    station_codes: list[str]
    source: str


class StationCandidate(BaseModel):
    """A station searched for this plan, with the last-mile estimate to the venue when one is known."""

    station_code: str
    station_name: str
    distance_to_venue_km: float | None = None
    estimated_last_mile_minutes: int | None = None
    last_mile_mode: str | None = None


class LastMileEstimate(BaseModel):
    """Station-to-venue transfer. `duration_minutes` is None when it cannot be estimated (never invented)."""

    station_code: str
    destination_venue: str | None
    distance_km: float | None
    duration_minutes: int | None
    transit_mode: str | None = "cab"
    confidence: Literal["estimate", "unknown"] = "estimate"
    method: str = "straight-line distance at urban cab speed plus a station exit allowance"


class TrainLeg(BaseModel):
    """One train in a goal-planner candidate, mapped from the provider's `Leg`."""

    train_number: str
    train_name: str
    from_code: str
    from_name: str
    to_code: str
    to_name: str
    departure: datetime
    arrival: datetime


class TrainCandidate(BaseModel):
    """A provider journey option as the goal planner sees it. Only built by `journey/provider_adapter.py`."""

    option_id: str
    legs: list[TrainLeg] = Field(min_length=1)
    departure: datetime
    arrival: datetime
    duration_minutes: int
    transfers: int
    classes: list[str] = Field(default_factory=list)
    fares: dict[str, float] = Field(default_factory=dict)  # listed fare per passenger; empty = unknown
    provenance: DataProvenance

    @computed_field
    @property
    def train_number(self) -> str:
        return " + ".join(leg.train_number for leg in self.legs)

    @computed_field
    @property
    def train_name(self) -> str:
        return " → ".join(leg.train_name for leg in self.legs)

    @computed_field
    @property
    def origin_code(self) -> str:
        return self.legs[0].from_code

    @computed_field
    @property
    def destination_code(self) -> str:
        return self.legs[-1].to_code

    @property
    def origin_name(self) -> str:
        return self.legs[0].from_name

    @property
    def destination_name(self) -> str:
        return self.legs[-1].to_name


class BookingHandoff(BaseModel):
    """Validated official booking handoff payload."""

    official_provider: str = "IRCTC Official Railway Reservation"
    booking_url: str
    is_url_allowlisted: bool = True
    train_number: str
    train_name: str
    from_station_code: str
    to_station_code: str
    journey_date: date
    recommended_class: str | None = None
    estimated_fare_inr: float | None = None
    disclaimer: str = (
        "RailSaathi AI provides booking guidance. This link opens the official IRCTC portal, where you complete "
        "the reservation yourself. No automated transactions are performed."
    )


class JourneyEvaluation(BaseModel):
    """Deterministic evaluation of a provider candidate against the passenger's constraints."""

    candidate_id: str
    candidate: TrainCandidate
    journey_date: date  # departure date of the first leg
    meeting_datetime: datetime

    last_mile_origin_station: str
    last_mile_destination_venue: str | None
    last_mile_duration_minutes: int | None
    last_mile_distance_km: float | None
    last_mile_mode: str | None

    latest_acceptable_station_arrival: datetime
    actual_arrival_buffer_minutes: int

    is_feasible: bool
    is_preferred_train: bool = False
    class_match: bool = True
    budget_match: bool = True
    duration_match: bool = True

    hard_constraint_violations: list[str] = Field(default_factory=list)
    soft_preference_matches: list[str] = Field(default_factory=list)
    soft_preference_penalties: list[str] = Field(default_factory=list)

    score: float = 0.0
    rank: int = 0
    match_category: Literal["best_match", "feasible_alternative", "infeasible"]
    explanation: str
    recommended_class: str | None = None
    recommended_fare: float | None = None
    booking_handoff: BookingHandoff | None = None


class JourneyPlanResponse(BaseModel):
    """Complete goal plan. `provenance` describes the journey data the plan was built from."""

    status: Literal[
        "answered",
        "clarification_required",
        "no_feasible_journey",
        "provider_unavailable",
    ]
    summary: str
    plan_id: str | None = None  # server-issued, bound to the caller's session; None until a plan is stored
    provenance: DataProvenance
    trip_requirements: TripRequirements | None = None
    resolved_origin: ResolvedPlace | None = None
    resolved_destination: ResolvedPlace | None = None
    candidate_origin_stations: list[StationCandidate] = Field(default_factory=list)
    candidate_destination_stations: list[StationCandidate] = Field(default_factory=list)

    best_match: JourneyEvaluation | None = None
    feasible_alternatives: list[JourneyEvaluation] = Field(default_factory=list)
    infeasible_options: list[JourneyEvaluation] = Field(default_factory=list)

    clarification_question: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    place_candidates: list[str] = Field(default_factory=list)
    tradeoff_explanation: str | None = None

    sources: list[dict] = Field(default_factory=list)
    trace_id: str


class GoalPlanRequest(BaseModel):
    """POST /api/journey/plan. Either a free-text `prompt`, structured fields, or both (fields win)."""

    model_config = ConfigDict(extra="forbid")

    prompt: str | None = Field(default=None, max_length=MAX_PROMPT_CHARS)  # runtime limit: MAX_MESSAGE_CHARS
    origin: str | None = Field(default=None, max_length=PLACE_MAX)
    destination_venue: str | None = Field(default=None, max_length=PLACE_MAX)
    destination_station: str | None = Field(default=None, max_length=PLACE_MAX)
    meeting_date: date | None = None
    meeting_time: str | None = Field(default=None, pattern=HHMM)
    required_arrival_buffer_minutes: int | None = Field(default=None, ge=0, le=720)
    preferred_class: TravelClass | None = None
    preferred_train_name_or_number: str | None = Field(default=None, max_length=TRAIN_QUERY_MAX)
    budget_max: float | None = Field(default=None, ge=0)


class RefineRequest(BaseModel):
    """POST /api/journey/refine: changes to a stored plan. Only fields that are sent are applied; sending
    `preferred_class`, `preferred_train_name_or_number` or `budget_max` as null clears it."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(pattern=PLAN_ID_PATTERN)
    meeting_date: date | None = None
    meeting_time: str | None = Field(default=None, pattern=HHMM)
    required_arrival_buffer_minutes: int | None = Field(default=None, ge=0, le=720)
    preferred_class: TravelClass | None = None
    preferred_train_name_or_number: str | None = Field(default=None, max_length=TRAIN_QUERY_MAX)
    budget_max: float | None = Field(default=None, ge=0)
