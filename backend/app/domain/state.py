"""Authoritative per-session workflow state (separate from the audit history)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domain.enums import DataMode, Language, WorkflowStatus
from app.domain.journey import JourneyDetails
from app.domain.options import Recommendation, RecommendationSet


class ValidationIssue(BaseModel):
    field: str
    code: str
    message: str
    candidates: list[str] = Field(default_factory=list)


class Reassessment(BaseModel):
    event_id: str
    event_label: str
    simulated: bool
    summary: str
    affected_option_ids: list[str]
    selected_option_affected: bool
    original_still_valid: bool | None
    changes: list[str]
    previous_selection: Recommendation | None = None
    requires_confirmation: bool = True


class ConfirmationRecord(BaseModel):
    confirmation_id: str
    confirmed_at: datetime
    selected_option_id: str
    constraints_hash: str
    handoff: dict[str, Any]
    superseded: bool = False


class SessionState(BaseModel):
    session_id: str
    workflow: str = "journey_planning"
    status: WorkflowStatus = WorkflowStatus.COLLECTING_DETAILS
    language: Language = Language.EN
    journey: JourneyDetails = Field(default_factory=JourneyDetails)
    missing_fields: list[str] = Field(default_factory=list)
    validation_errors: list[ValidationIssue] = Field(default_factory=list)
    pending_question: str | None = None
    asked_preferences: bool = False
    pending_candidates: dict[str, list[str]] = Field(default_factory=dict)  # field -> place ids
    awaiting_confirmation: bool = False
    selected_option_id: str | None = None
    recommendations: RecommendationSet | None = None
    reassessment: Reassessment | None = None
    confirmation: ConfirmationRecord | None = None
    data_mode: DataMode = DataMode.DEMO
    extraction_source: str | None = None
    version: int = 0
    created_at: datetime
    updated_at: datetime
