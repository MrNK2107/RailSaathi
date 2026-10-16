"""Merge an IntentUpdate into JourneyDetails. Every raw value is resolved and
parsed deterministically; uncertain values become clarification issues instead
of being silently accepted. Returns a new JourneyDetails (no mutation)."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.domain.enums import FieldSource
from app.domain.journey import JourneyDetails, TimeWindow
from app.domain.state import ValidationIssue
from app.intent.schema import IntentUpdate
from app.stations.resolver import StationResolver
from app.validation.parsing import parse_class, parse_date_text, parse_time_text

PERIODS = {
    "morning": ("05:00", "12:00"), "afternoon": ("12:00", "17:00"),
    "evening": ("17:00", "21:00"), "night": ("20:00", "23:59"), "daytime": ("06:00", "18:00"),
}
CONSTRAINT_FIELDS = (
    "origin", "destination", "journey_date", "date_anchor", "passenger_count", "arrival_deadline",
    "deadline_strict", "departure_window", "budget_limit", "budget_strict", "budget_priority",
    "class_preference", "class_strict", "passenger_needs", "assistance_mandatory",
    "transfer_preference", "transfer_strict",
)
CLEAR_VALUES: dict[str, Any] = {"passenger_needs": []}


@dataclass
class MergeResult:
    journey: JourneyDetails
    issues: list[ValidationIssue] = field(default_factory=list)
    candidates: dict[str, list[str]] = field(default_factory=dict)
    changed: list[str] = field(default_factory=list)


def changed_fields(before: JourneyDetails, after: JourneyDetails) -> list[str]:
    b, a = before.model_dump(mode="json"), after.model_dump(mode="json")
    return [f for f in CONSTRAINT_FIELDS if b[f] != a[f]]


class JourneyMerger:
    def __init__(self, resolver: StationResolver) -> None:
        self._resolver = resolver

    def merge(self, journey: JourneyDetails, u: IntentUpdate, now: datetime) -> MergeResult:
        updates: dict[str, Any] = {}
        sources: dict[str, FieldSource] = {}
        result = MergeResult(journey=journey)
        self._places(journey, u, updates, sources, result)
        self._date_time(u, now, updates, sources, result)
        self._preferences(journey, u, updates, sources, result)
        for name in u.clear_fields:
            updates[name] = CLEAR_VALUES.get(name)
            if name == "budget_limit":
                updates["budget_strict"] = False
        merged = journey.model_copy(update={**updates, "field_sources": {**journey.field_sources, **sources}})
        # Re-validate through the model so bad values cannot slip in via model_copy.
        result.journey = JourneyDetails.model_validate(merged.model_dump())
        result.changed = changed_fields(journey, result.journey)
        return result

    def _places(self, j: JourneyDetails, u: IntentUpdate, updates: dict, sources: dict, result: MergeResult) -> None:
        texts = {"origin": u.origin_text, "destination": u.destination_text}
        for place in u.unassigned_places:
            slot = next((f for f in ("destination", "origin")
                         if texts[f] is None and getattr(j, f) is None), None)
            if slot:
                texts[slot] = place
        for name, text in texts.items():
            if text:
                self._resolve_into(name, text, updates, sources, result)

    def _resolve_into(self, name: str, text: str, updates: dict, sources: dict, result: MergeResult) -> None:
        res = self._resolver.resolve(text)
        if res.status == "resolved":
            updates[name] = res.place
            sources[name] = FieldSource.EXPLICIT
        elif res.status == "ambiguous":
            result.candidates[name] = [c.id for c in res.candidates]
            result.issues.append(ValidationIssue(
                field=name, code="ambiguous_station", message=f"\"{text}\" matches several places.",
                candidates=[c.label for c in res.candidates]))
        else:
            result.issues.append(ValidationIssue(
                field=name, code="station_not_found", message=f"\"{text}\" is not in the station list."))

    def _date_time(self, u: IntentUpdate, now: datetime, updates: dict, sources: dict, result: MergeResult) -> None:
        if u.date_text:
            parsed = parse_date_text(u.date_text, now)
            if parsed.status == "ok":
                updates["journey_date"] = parsed.value
                sources["journey_date"] = FieldSource.INFERRED if parsed.inferred else FieldSource.EXPLICIT
            else:
                result.issues.append(ValidationIssue(
                    field="journey_date", code=f"date_{parsed.status}", message=parsed.message))
        if u.date_anchor and (u.date_text or u.arrival_deadline_text):
            updates["date_anchor"] = u.date_anchor
        if u.arrival_deadline_text:
            parsed_time = parse_time_text(u.arrival_deadline_text)
            if parsed_time:
                updates["arrival_deadline"] = parsed_time
                updates["deadline_strict"] = u.deadline_strict if u.deadline_strict is not None else True
                sources["arrival_deadline"] = FieldSource.EXPLICIT
            else:
                result.issues.append(ValidationIssue(field="arrival_deadline", code="invalid_time",
                                                     message="I couldn't understand that arrival time."))
        window = self._window(u)
        if window:
            updates["departure_window"] = window
            sources["departure_window"] = FieldSource.EXPLICIT

    @staticmethod
    def _window(u: IntentUpdate) -> TimeWindow | None:
        after = parse_time_text(u.departure_after_text) if u.departure_after_text else None
        before = parse_time_text(u.departure_before_text) if u.departure_before_text else None
        if after or before:
            return TimeWindow(start=after or "00:00", end=before or "23:59")
        if u.departure_period:
            start, end = PERIODS[u.departure_period]
            return TimeWindow(start=start, end=end, label=u.departure_period)
        return None

    def _preferences(self, j: JourneyDetails, u: IntentUpdate, updates: dict, sources: dict, result: MergeResult) -> None:
        simple = {
            "passenger_count": u.passenger_count, "budget_limit": u.budget_limit,
            "budget_priority": u.budget_priority, "transfer_preference": u.transfer_preference,
            "assistance_mandatory": u.assistance_mandatory,
        }
        for name, value in simple.items():
            if value is not None:
                updates[name] = value
                sources[name] = FieldSource.EXPLICIT
        if u.budget_limit is not None:
            updates["budget_strict"] = bool(u.budget_strict)
        if u.transfer_preference is not None:
            updates["transfer_strict"] = bool(u.transfer_strict)
        if u.class_text:
            cls = parse_class(u.class_text)
            if cls:
                updates["class_preference"] = cls
                updates["class_strict"] = bool(u.class_strict)
                sources["class_preference"] = FieldSource.EXPLICIT
            else:
                result.issues.append(ValidationIssue(field="class_preference", code="unsupported_class",
                                                     message=f"Class \"{u.class_text}\" is not supported."))
        if u.needs_add or u.needs_remove:
            needs = [n for n in j.passenger_needs if n not in u.needs_remove]
            needs += [n for n in u.needs_add if n not in needs]
            updates["passenger_needs"] = needs
