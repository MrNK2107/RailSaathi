"""Typed handoff payload for the main RailSaathi AI application.

Contains only what a consuming module needs. Confirmed passenger choices are
separated from information that remains unverified."""

from datetime import datetime
from typing import Any

from app.domain.enums import Verification
from app.domain.journey import JourneyDetails
from app.domain.options import Recommendation

HANDOFF_SCHEMA_VERSION = "1.0"
DISCLAIMERS = [
    "No ticket has been booked and no seat has been reserved.",
    "Assistance has not been booked or guaranteed; facility status reflects the data source only.",
]


def build_handoff(
    session_id: str, confirmation_id: str, confirmed_at: datetime, journey: JourneyDetails,
    rec: Recommendation, replaces: str | None,
) -> dict[str, Any]:
    option = rec.option
    return {
        "module": "smart_passenger_planner",
        "schema_version": HANDOFF_SCHEMA_VERSION,
        "session_id": session_id,
        "status": "confirmed",
        "confirmation_id": confirmation_id,
        "confirmed_at": confirmed_at.isoformat(),
        "replaces_confirmation_id": replaces,
        "journey": {
            "origin": _place(journey.origin),
            "destination": _place(journey.destination),
            "journey_date": journey.journey_date.isoformat() if journey.journey_date else None,
            "date_refers_to": journey.date_anchor.value,
            "passenger_count": journey.passenger_count,
        },
        "selected_option": {
            "option_id": option.option_id,
            "legs": [leg.model_dump(mode="json") for leg in option.legs],
            "departure": option.departure.isoformat(),
            "arrival": option.arrival.isoformat(),
            "duration_minutes": option.duration_minutes,
            "transfers": option.transfers,
            "travel_class": rec.selected_class.value if rec.selected_class else None,
            "listed_fare_per_passenger": rec.fare_per_passenger,
            "listed_total_fare": rec.total_fare,
            "currency": "INR",
            "simulated_change": option.simulated_change,
        },
        "constraints": _constraints(journey),
        "preferences": _preferences(journey),
        "verification": {
            "confirmed_by_passenger": ["origin", "destination", "journey_date", "passenger_count", "selected_option"],
            "hard_constraints": [c.model_dump(mode="json") for c in rec.hard_constraints],
            "passenger_needs": [s.model_dump(mode="json") for s in rec.need_statuses],
            "unverified": rec.unverified + [
                s.detail for s in rec.need_statuses if s.status == Verification.NOT_SUPPORTED
            ],
            # Neither the bundled dataset nor third-party feeds are authoritative IRCTC fares/schedules.
            "fare_and_schedule_verified": False,
            "fare_available": rec.total_fare is not None,
            "seat_availability_checked": False,
        },
        "data_provenance": option.provenance.model_dump(mode="json"),
        "disclaimers": list(DISCLAIMERS),
    }


def _place(place: Any) -> dict[str, Any] | None:
    return place.model_dump(mode="json") if place else None


def _constraints(j: JourneyDetails) -> dict[str, Any]:
    return {
        "arrival_deadline": j.arrival_deadline if j.deadline_strict else None,
        "max_budget_total": j.budget_limit if j.budget_strict else None,
        "travel_class": j.class_preference.value if j.class_preference and j.class_strict else None,
        "direct_only": j.transfer_strict and j.transfer_preference is not None
        and j.transfer_preference.value == "direct_only",
        "assistance_mandatory": j.assistance_mandatory,
    }


def _preferences(j: JourneyDetails) -> dict[str, Any]:
    return {
        "budget_priority": j.budget_priority.value if j.budget_priority else None,
        "preferred_arrival_by": j.arrival_deadline if not j.deadline_strict else None,
        "budget_target_total": j.budget_limit if not j.budget_strict else None,
        "class_preference": j.class_preference.value if j.class_preference and not j.class_strict else None,
        "departure_window": j.departure_window.model_dump() if j.departure_window else None,
        "transfer_preference": j.transfer_preference.value if j.transfer_preference and not j.transfer_strict else None,
        "passenger_needs": [n.value for n in j.passenger_needs],
    }
