"""Journey validation independent of any LLM."""

from datetime import datetime, timedelta

from app.config import Settings
from app.domain.enums import DateAnchor, PassengerNeed
from app.domain.journey import REQUIRED_FIELDS, JourneyDetails
from app.domain.state import ValidationIssue
from app.validation.parsing import is_valid_hhmm

DAYTIME_START = "06:00"
DAYTIME_END = "18:00"


def missing_fields(journey: JourneyDetails) -> list[str]:
    return [f for f in REQUIRED_FIELDS if getattr(journey, f) is None]


def validate_journey(journey: JourneyDetails, now: datetime, settings: Settings) -> list[ValidationIssue]:
    checks = (
        _check_places,
        _check_date,
        _check_passengers,
        _check_budget,
        _check_times,
    )
    issues: list[ValidationIssue] = []
    for check in checks:
        issues.extend(check(journey, now, settings))
    return issues


def _issue(field: str, code: str, message: str) -> ValidationIssue:
    return ValidationIssue(field=field, code=code, message=message)


def _check_places(j: JourneyDetails, _now: datetime, _s: Settings) -> list[ValidationIssue]:
    if j.origin and j.destination and set(j.origin.station_codes) & set(j.destination.station_codes):
        return [_issue("destination", "same_origin_destination",
                       "Origin and destination cannot be the same place.")]
    return []


def _check_date(j: JourneyDetails, now: datetime, s: Settings) -> list[ValidationIssue]:
    if j.journey_date is None:
        return []
    today = now.date()
    if j.journey_date < today:
        return [_issue("journey_date", "date_in_past", "The journey date is in the past.")]
    if j.journey_date > today + timedelta(days=s.max_planning_days):
        return [_issue("journey_date", "date_too_far",
                       f"Journeys can be planned up to {s.max_planning_days} days ahead.")]
    deadline_today = (
        j.arrival_deadline and j.deadline_strict and j.date_anchor == DateAnchor.ARRIVAL
        and j.journey_date == today and is_valid_hhmm(j.arrival_deadline)
    )
    if deadline_today and j.arrival_deadline <= now.strftime("%H:%M"):
        return [_issue("arrival_deadline", "deadline_passed",
                       "The requested arrival time today has already passed.")]
    return []


def _check_passengers(j: JourneyDetails, _now: datetime, s: Settings) -> list[ValidationIssue]:
    count = j.passenger_count
    if count is None:
        return []
    if count < 1 or count > s.max_passengers:
        return [_issue("passenger_count", "invalid_passenger_count",
                       f"Passenger count must be between 1 and {s.max_passengers}.")]
    return []


def _check_budget(j: JourneyDetails, _now: datetime, _s: Settings) -> list[ValidationIssue]:
    if j.budget_limit is not None and j.budget_limit <= 0:
        return [_issue("budget_limit", "invalid_budget", "Budget must be a positive amount.")]
    return []


def _check_times(j: JourneyDetails, _now: datetime, _s: Settings) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if j.arrival_deadline and not is_valid_hhmm(j.arrival_deadline):
        issues.append(_issue("arrival_deadline", "invalid_time", "Arrival time must be HH:MM."))
    window = j.departure_window
    if window:
        if not (is_valid_hhmm(window.start) and is_valid_hhmm(window.end)):
            issues.append(_issue("departure_window", "invalid_time", "Departure window must be HH:MM."))
        elif window.start == window.end:
            issues.append(_issue("departure_window", "empty_window",
                                 "The departure window start and end cannot be the same."))
        elif PassengerNeed.DAYTIME_DEPARTURE in j.passenger_needs and (
            window.start >= DAYTIME_END or window.end <= DAYTIME_START
        ):
            issues.append(_issue("departure_window", "contradictory_constraints",
                                 "A daytime departure was requested, but the departure window "
                                 "is at night. Please choose one."))
    return issues
