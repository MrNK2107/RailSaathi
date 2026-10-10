"""Structured intent update. Produced by either the LLM adapter or the rule-based
extractor, then validated deterministically before it touches session state.

Values are raw passenger text ("tomorrow", "9 am", "Kovai"); application logic
decides what they resolve to."""

from typing import Literal

from pydantic import BaseModel, Field

from app.domain.enums import BudgetPriority, DateAnchor, PassengerNeed, TransferPreference

IntentType = Literal[
    "provide_details", "request_recommendations", "select_option", "confirm",
    "cancel", "restart", "relax_constraint", "greeting", "help", "other",
]
ClearableField = Literal[
    "budget_limit", "budget_priority", "arrival_deadline", "departure_window",
    "class_preference", "transfer_preference", "passenger_needs",
]
DeparturePeriod = Literal["morning", "afternoon", "evening", "night", "daytime"]


class IntentUpdate(BaseModel):
    intent: IntentType = "provide_details"
    is_correction: bool = False
    origin_text: str | None = Field(default=None, max_length=80)
    destination_text: str | None = Field(default=None, max_length=80)
    unassigned_places: list[str] = Field(default_factory=list, max_length=5)
    date_text: str | None = Field(default=None, max_length=60)
    date_anchor: DateAnchor | None = None
    arrival_deadline_text: str | None = Field(default=None, max_length=30)
    deadline_strict: bool | None = None
    departure_after_text: str | None = Field(default=None, max_length=30)
    departure_before_text: str | None = Field(default=None, max_length=30)
    departure_period: DeparturePeriod | None = None
    passenger_count: int | None = Field(default=None, ge=-100, le=100)
    budget_limit: float | None = None
    budget_strict: bool | None = None
    budget_priority: BudgetPriority | None = None
    class_text: str | None = Field(default=None, max_length=40)
    class_strict: bool | None = None
    needs_add: list[PassengerNeed] = Field(default_factory=list)
    needs_remove: list[PassengerNeed] = Field(default_factory=list)
    assistance_mandatory: bool | None = None
    transfer_preference: TransferPreference | None = None
    transfer_strict: bool | None = None
    clear_fields: list[ClearableField] = Field(default_factory=list)
    selected_option: str | None = Field(default=None, max_length=40)
    unsupported_requests: list[str] = Field(default_factory=list, max_length=5)

    def has_details(self) -> bool:
        ignore = {"intent", "is_correction", "selected_option", "unsupported_requests"}
        data = self.model_dump(exclude=ignore)
        return any(v not in (None, [], False) for v in data.values())
