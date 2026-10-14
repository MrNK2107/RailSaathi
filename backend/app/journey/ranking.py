"""
RailSaathi AI — goal plan ranking.

Ranks evaluated provider candidates deterministically and assembles the plan response. Sources are derived from
the provenance of the data actually used; nothing here claims a source the data did not come from.
"""

from app.domain.options import DataProvenance
from app.journey.models import (
    JourneyEvaluation,
    JourneyPlanResponse,
    ResolvedPlace,
    StationCandidate,
    TripRequirements,
)

MAX_INFEASIBLE_SHOWN = 8


def plan_sources(provenance: DataProvenance) -> list[dict]:
    """Stable source ids so the guidance agent can cite them (it only collects sources with a source_id)."""
    return [
        {"source_id": f"SRC-JOURNEY-{provenance.mode.value.upper()}", "title": provenance.source,
         "publisher": provenance.source, "mode": provenance.mode.value, "as_of": provenance.as_of.isoformat(),
         "last_verified_at": provenance.as_of.isoformat(), "note": provenance.note},
        {"source_id": "SRC-IRCTC-BOOKING", "title": "IRCTC official booking portal", "publisher": "IRCTC",
         "source_url": "https://www.irctc.co.in",
         "note": "Bookings are completed by the passenger on IRCTC; fares and availability are confirmed there."},
    ]


def _buffer_phrase(ev: JourneyEvaluation) -> str:
    if ev.last_mile_duration_minutes is None:
        return (f"arriving at the station about {ev.actual_arrival_buffer_minutes} min before the meeting (this "
                "buffer excludes the unknown station-to-venue travel time)")
    return f"leaving an estimated {ev.actual_arrival_buffer_minutes}-min buffer at the venue"


class JourneyRankingEngine:
    def rank_and_assemble_plan(
        self,
        requirements: TripRequirements,
        evaluations: list[JourneyEvaluation],
        provenance: DataProvenance,
        resolved_origin: ResolvedPlace | None,
        resolved_destination: ResolvedPlace | None,
        candidate_origin_stations: list[StationCandidate],
        candidate_destination_stations: list[StationCandidate],
        trace_id: str,
    ) -> JourneyPlanResponse:
        common = dict(
            provenance=provenance, trip_requirements=requirements, resolved_origin=resolved_origin,
            resolved_destination=resolved_destination, candidate_origin_stations=candidate_origin_stations,
            candidate_destination_stations=candidate_destination_stations, sources=plan_sources(provenance),
            trace_id=trace_id,
        )
        target = requirements.destination_venue or requirements.destination_station or "your destination"
        when = f"{requirements.meeting_time} on {requirements.meeting_date.isoformat()}"

        if not evaluations:
            return JourneyPlanResponse(
                status="no_feasible_journey",
                summary=(f"The data source returned no trains from {requirements.origin} towards {target} for the "
                         f"dates searched (the meeting day and the day before)."),
                tradeoff_explanation=("Try a different departure station or a nearby arrival station. Only trains "
                                      "the data source lists are considered."),
                **common,
            )

        feasible = sorted((e for e in evaluations if e.is_feasible), key=lambda e: e.score, reverse=True)
        infeasible = sorted((e for e in evaluations if not e.is_feasible),
                            key=lambda e: e.actual_arrival_buffer_minutes, reverse=True)
        for rank, ev in enumerate([*feasible, *infeasible], start=1):
            ev.rank = rank
            ev.match_category = "infeasible" if not ev.is_feasible else "feasible_alternative"
        infeasible = infeasible[:MAX_INFEASIBLE_SHOWN]

        if feasible:
            best = feasible[0]
            best.match_category = "best_match"
            tradeoff = None
            if requirements.preferred_train_name_or_number and not best.is_preferred_train:
                pref = next((e for e in evaluations if e.is_preferred_train and not e.is_feasible), None)
                if pref:
                    tradeoff = (f"Your preferred train {pref.candidate.train_number} cannot meet the deadline: "
                                f"{' '.join(pref.hard_constraint_violations)}")
            count = len(feasible)
            return JourneyPlanResponse(
                status="answered",
                summary=(f"Found {count} train option{'s' if count > 1 else ''} that reach {target} before {when}. "
                         f"Top recommendation: {best.candidate.train_number} {best.candidate.train_name}, "
                         f"{_buffer_phrase(best)}."),
                best_match=best, feasible_alternatives=feasible[1:], infeasible_options=infeasible,
                tradeoff_explanation=tradeoff, **common,
            )

        closest = infeasible[0]
        return JourneyPlanResponse(
            status="no_feasible_journey",
            summary=(f"None of the {len(evaluations)} trains found reaches {target} before {when} with your "
                     f"{requirements.required_arrival_buffer_minutes}-min buffer."),
            infeasible_options=infeasible,
            tradeoff_explanation=(f"Closest option: {closest.candidate.train_number} "
                                  f"({' '.join(closest.hard_constraint_violations)}) Consider a smaller buffer, an "
                                  f"earlier departure the previous day or a different arrival station."),
            **common,
        )
