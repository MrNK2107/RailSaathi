"""
RailSathi AI — Journey Recommendation and Ranking Engine

Ranks feasible journey candidates deterministically and structures comprehensive
trade-off explanations, alternative suggestions, and infeasibility diagnoses.
"""

import logging
from typing import Any
from app.journey.models import (
    TripRequirements,
    ResolvedLocation,
    StationCandidate,
    JourneyEvaluation,
    JourneyPlanResponse,
)

logger = logging.getLogger("railsaathi.journey.ranking")


class JourneyRankingEngine:
    """Deterministic recommendation engine to rank journeys and synthesize alternatives."""

    def rank_and_assemble_plan(
        self,
        requirements: TripRequirements,
        evaluations: list[JourneyEvaluation],
        resolved_origin: ResolvedLocation | None,
        resolved_destination: ResolvedLocation | None,
        candidate_origin_stations: list[StationCandidate],
        candidate_destination_stations: list[StationCandidate],
        trace_id: str,
        sources: list[dict] | None = None,
        tool_calls_made: int = 0,
        rounds_used: int = 0,
    ) -> JourneyPlanResponse:
        """
        Rank journey evaluations and produce a structured JourneyPlanResponse.
        """
        sources_list = sources or [
            {
                "source_id": "SRC-NTES-TIMETABLE",
                "title": "Indian Railways National Train Enquiry System (NTES)",
                "publisher": "Centre for Railway Information Systems (CRIS)",
                "source_url": "https://enquiry.indianrail.gov.in",
                "last_verified_at": "2026-10-10",
                "verification_status": "official_repository",
            },
            {
                "source_id": "SRC-IRCTC-RESERVATION",
                "title": "IRCTC Official Train Booking Portal",
                "publisher": "IRCTC",
                "source_url": "https://www.irctc.co.in",
                "last_verified_at": "2026-10-10",
                "verification_status": "official_portal",
            },
        ]

        if not evaluations:
            # Insufficient data / no trains found
            return JourneyPlanResponse(
                status="no_feasible_journey",
                summary=(
                    f"No scheduled train services found between {requirements.origin} and "
                    f"{requirements.destination_venue} ({resolved_destination.city if resolved_destination else ''}) "
                    f"for the requested date ({requirements.meeting_date})."
                ),
                trip_requirements=requirements,
                resolved_origin=resolved_origin,
                resolved_destination=resolved_destination,
                candidate_origin_stations=candidate_origin_stations,
                candidate_destination_stations=candidate_destination_stations,
                best_match=None,
                feasible_alternatives=[],
                infeasible_options=[],
                tradeoff_explanation=(
                    "Try checking neighboring departure stations or choosing a date with higher service frequency. "
                    "You may also consider an overnight journey departing the previous evening."
                ),
                sources=sources_list,
                trace_id=trace_id,
                tool_calls_made=tool_calls_made,
                rounds_used=rounds_used,
            )

        feasible: list[JourneyEvaluation] = []
        infeasible: list[JourneyEvaluation] = []

        for ev in evaluations:
            if ev.is_feasible:
                feasible.append(ev)
            else:
                infeasible.append(ev)

        # Sort feasible candidates descending by deterministic score
        feasible.sort(key=lambda x: x.score, reverse=True)

        # Sort infeasible candidates by buffer shortfall (closest to deadline first)
        infeasible.sort(key=lambda x: x.actual_arrival_buffer_minutes or -9999, reverse=True)

        best_match: JourneyEvaluation | None = None
        alternatives: list[JourneyEvaluation] = []

        if feasible:
            best_match = feasible[0]
            best_match.rank = 1
            best_match.match_category = "best_match"

            for i, alt in enumerate(feasible[1:], start=2):
                alt.rank = i
                alt.match_category = "feasible_alternative"
                alternatives.append(alt)

            # Assign rank to infeasible candidates
            for i, inf in enumerate(infeasible, start=len(feasible) + 1):
                inf.rank = i
                inf.match_category = "infeasible"

            summary = (
                f"Found {len(feasible)} feasible train option{'s' if len(feasible) > 1 else ''} to reach "
                f"{requirements.destination_venue} by {requirements.meeting_time} on {requirements.meeting_date}. "
                f"Top recommendation is {best_match.train_service.train_name} ({best_match.train_service.train_number}), "
                f"arriving with a comfortable {best_match.actual_arrival_buffer_minutes}-minute buffer."
            )

            tradeoff_text = None
            if requirements.preferred_train_name_or_number and not best_match.is_preferred_train:
                pref_eval = next((e for e in evaluations if e.is_preferred_train), None)
                if pref_eval and not pref_eval.is_feasible:
                    tradeoff_text = (
                        f"Note on preferred train: {pref_eval.train_service.train_name} ({pref_eval.train_service.train_number}) "
                        f"was evaluated but cannot satisfy your arrival deadline ({' '.join(pref_eval.hard_constraint_violations)}). "
                        f"We strongly recommend {best_match.train_service.train_name} instead."
                    )

            return JourneyPlanResponse(
                status="answered",
                summary=summary,
                trip_requirements=requirements,
                resolved_origin=resolved_origin,
                resolved_destination=resolved_destination,
                candidate_origin_stations=candidate_origin_stations,
                candidate_destination_stations=candidate_destination_stations,
                best_match=best_match,
                feasible_alternatives=alternatives,
                infeasible_options=infeasible,
                tradeoff_explanation=tradeoff_text,
                sources=sources_list,
                trace_id=trace_id,
                tool_calls_made=tool_calls_made,
                rounds_used=rounds_used,
            )
        else:
            # No feasible trains found
            for i, inf in enumerate(infeasible, start=1):
                inf.rank = i
                inf.match_category = "infeasible"

            # Diagnose reasons
            closest = infeasible[0] if infeasible else None
            shortfall_note = ""
            if closest and closest.actual_arrival_buffer_minutes is not None:
                if closest.actual_arrival_buffer_minutes < 0:
                    shortfall_note = f"The earliest morning train ({closest.train_service.train_name}) arrives at the venue ~{abs(closest.actual_arrival_buffer_minutes)} minutes after your {requirements.meeting_time} meeting starts."
                else:
                    shortfall_note = f"The closest train ({closest.train_service.train_name}) provides only a {closest.actual_arrival_buffer_minutes}-minute buffer (you requested {requirements.required_arrival_buffer_minutes} mins)."

            tradeoff_explanation = (
                f"None of the {len(evaluations)} candidate train services satisfy your required arrival deadline "
                f"and {requirements.required_arrival_buffer_minutes}-minute buffer. {shortfall_note} "
                f"To reach your meeting in time, we recommend: "
                f"1) Taking an overnight sleeper/AC train the previous night (e.g. Chennai Mail), "
                f"2) Slightly relaxing the requested arrival buffer, or "
                f"3) Exploring alternative arrival stations closer to {requirements.destination_venue}."
            )

            return JourneyPlanResponse(
                status="no_feasible_journey",
                summary=(
                    f"No scheduled direct trains from {requirements.origin} can reach {requirements.destination_venue} "
                    f"before {requirements.meeting_time} on {requirements.meeting_date} with your required {requirements.required_arrival_buffer_minutes}-minute buffer."
                ),
                trip_requirements=requirements,
                resolved_origin=resolved_origin,
                resolved_destination=resolved_destination,
                candidate_origin_stations=candidate_origin_stations,
                candidate_destination_stations=candidate_destination_stations,
                best_match=None,
                feasible_alternatives=[],
                infeasible_options=infeasible,
                tradeoff_explanation=tradeoff_explanation,
                sources=sources_list,
                trace_id=trace_id,
                tool_calls_made=tool_calls_made,
                rounds_used=rounds_used,
            )
