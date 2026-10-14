"""HTTP request/response schemas for the planner API."""

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
    BudgetPriority,
    DataMode,
    DateAnchor,
    Language,
    PassengerNeed,
    TransferPreference,
    TravelClass,
    WorkflowStatus,
)
from app.domain.journey import TimeWindow
from app.domain.state import SessionState, ValidationIssue

DATA_NOTICE = ("DEMO DATA: trains, timings, fares and disruptions are simulated for demonstration. "
               "They are not live Indian Railways information. No tickets are booked.")
LIVE_NOTICE = ("LIVE DATA from RailRadar (third-party, not an official Indian Railways source). Timings can change "
               "and fares/seat availability may be missing. Verify on IRCTC/NTES. No tickets are booked.")


def data_notice(mode: DataMode) -> str:
    return LIVE_NOTICE if mode == DataMode.LIVE else DATA_NOTICE


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateSessionRequest(StrictModel):
    language: Language = Language.EN


class MessageRequest(StrictModel):
    message: str = Field(min_length=1, max_length=10_000)  # hard cap; Settings.max_message_chars is enforced in the handler
    language: Language | None = None


class JourneyPatch(StrictModel):
    """Manual corrections. Only fields present in the body are changed; null clears a field."""

    origin: str | None = Field(default=None, max_length=80, description="Place name, alias or id")
    destination: str | None = Field(default=None, max_length=80)
    journey_date: date | None = None
    date_anchor: DateAnchor | None = None
    passenger_count: int | None = Field(default=None, ge=1, le=20)
    arrival_deadline: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    deadline_strict: bool | None = None
    departure_window: TimeWindow | None = None
    budget_limit: float | None = Field(default=None, gt=0, le=1_000_000)
    budget_strict: bool | None = None
    budget_priority: BudgetPriority | None = None
    class_preference: TravelClass | None = None
    class_strict: bool | None = None
    passenger_needs: list[PassengerNeed] | None = None
    assistance_mandatory: bool | None = None
    transfer_preference: TransferPreference | None = None
    transfer_strict: bool | None = None


class SelectRequest(StrictModel):
    option_id: str = Field(min_length=1, max_length=120)


class ConfirmRequest(StrictModel):
    option_id: str | None = Field(default=None, max_length=120)


class ReassessRequest(StrictModel):
    event_id: str | None = Field(default=None, max_length=60)


class ExtractionInfo(BaseModel):
    source: str | None
    fallback_reason: str | None


class PlannerResponse(BaseModel):
    session_id: str
    session_token: str | None = None  # issued only by session creation
    assistant_message: str
    status: WorkflowStatus
    state: SessionState
    missing_fields: list[str]
    validation_errors: list[ValidationIssue]
    recommendations_ready: bool
    confirmation_required: bool
    data_mode: DataMode
    data_notice: str
    extraction: ExtractionInfo | None = None
    handoff: dict[str, Any] | None = None


class HealthResponse(BaseModel):
    status: str
    api_version: str
    data_mode: DataMode
    data_provider: dict[str, Any]
    ai: dict[str, Any]


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody
