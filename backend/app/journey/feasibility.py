"""
RailSathi AI — Journey Feasibility Evaluator

Deterministic evaluation of candidate train journeys against passenger goals,
calculating deadline buffers, overnight schedules, hard constraints, and soft preferences.
"""

import logging
from datetime import datetime, date, time, timedelta
from typing import Any
from app.journey.models import (
    TripRequirements,
    TrainService,
    StationCandidate,
    LastMileEstimate,
    JourneyEvaluation,
    BookingHandoff,
)
from app.journey.booking import BookingHandoffService

logger = logging.getLogger("railsaathi.journey.feasibility")


def parse_iso_datetime(date_str: str, time_str: str) -> datetime:
    """Parse YYYY-MM-DD and HH:MM into a Python datetime object."""
    dt_str = f"{date_str.strip()} {time_str.strip()}"
    return datetime.strptime(dt_str, "%Y-%m-%d %H:%M")


class JourneyFeasibilityEvaluator:
    """Deterministic evaluator for candidate train feasibility."""

    def __init__(self):
        self.booking_service = BookingHandoffService()

    def evaluate_candidate(
        self,
        train: TrainService,
        requirements: TripRequirements,
        last_mile: LastMileEstimate,
    ) -> JourneyEvaluation:
        """
        Evaluate a single candidate train against the passenger's trip requirements.
        """
        candidate_id = f"cand-{train.train_number}-{train.origin_station_code}-{train.destination_station_code}"

        # 1. Parse meeting deadline datetime
        meeting_dt = parse_iso_datetime(requirements.meeting_date, requirements.meeting_time)

        # 2. Determine train departure date:
        # If train arrives next day (day_offset = 1), departure date is meeting_date - 1 day
        meeting_date_obj = datetime.strptime(requirements.meeting_date, "%Y-%m-%d").date()
        departure_date_obj = meeting_date_obj - timedelta(days=train.day_offset)
        departure_date_str = departure_date_obj.strftime("%Y-%m-%d")

        # 3. Calculate exact departure and arrival datetimes
        dep_dt = parse_iso_datetime(departure_date_str, train.departure_time)
        arr_date_obj = departure_date_obj + timedelta(days=train.day_offset)
        arr_date_str = arr_date_obj.strftime("%Y-%m-%d")
        arr_dt = parse_iso_datetime(arr_date_str, train.arrival_time)

        # 4. Deterministic Deadline & Buffer Formula:
        # latest_acceptable_station_arrival = meeting_start - requested_buffer - last_mile_duration
        requested_buffer = requirements.required_arrival_buffer_minutes
        last_mile_mins = last_mile.duration_minutes

        latest_station_arr_dt = meeting_dt - timedelta(minutes=requested_buffer + last_mile_mins)

        # Estimated venue arrival = station arrival + last mile transit
        venue_arr_dt = arr_dt + timedelta(minutes=last_mile_mins)

        # Actual arrival buffer before meeting = (meeting_dt - venue_arr_dt) in minutes
        actual_buffer_minutes = int((meeting_dt - venue_arr_dt).total_seconds() / 60)

        # 5. Check hard constraints
        hard_violations: list[str] = []
        is_feasible = True

        # Constraint A: Deadline & Buffer
        if arr_dt > latest_station_arr_dt:
            is_feasible = False
            shortfall = int((arr_dt - latest_station_arr_dt).total_seconds() / 60)
            hard_violations.append(
                f"Train reaches {train.destination_station_name} at {train.arrival_time}, "
                f"which is {shortfall} mins after the required station deadline ({latest_station_arr_dt.strftime('%H:%M')})."
            )

        # Constraint B: Train must arrive before or on the meeting date/time (cannot arrive after meeting started)
        if venue_arr_dt >= meeting_dt:
            if not any("deadline" in v.lower() for v in hard_violations):
                hard_violations.append(
                    f"Estimated venue arrival ({venue_arr_dt.strftime('%H:%M')}) is after the meeting starts ({meeting_dt.strftime('%H:%M')})."
                )
            is_feasible = False

        # Constraint C: Maximum Journey Duration (if specified as hard constraint)
        if requirements.maximum_journey_duration_minutes:
            if train.duration_minutes > requirements.maximum_journey_duration_minutes:
                if "max_duration" in requirements.hard_constraints:
                    is_feasible = False
                    hard_violations.append(
                        f"Journey duration ({train.duration_minutes} mins) exceeds maximum acceptable limit ({requirements.maximum_journey_duration_minutes} mins)."
                    )

        # 6. Evaluate Travel Classes and Fares
        applicable_classes = train.classes
        pref_class = requirements.preferred_class
        class_match = False
        recommended_class = None
        recommended_fare = None

        if pref_class and pref_class in applicable_classes:
            class_match = True
            recommended_class = pref_class
            recommended_fare = train.fares.get(pref_class)
        elif applicable_classes:
            # Pick best available class (e.g., 3A or CC preferred, else lowest)
            for c in ["3A", "CC", "2A", "SL", "3E", "2S", "1A", "EC"]:
                if c in applicable_classes:
                    recommended_class = c
                    recommended_fare = train.fares.get(c)
                    break
            if not recommended_class:
                recommended_class = applicable_classes[0]
                recommended_fare = train.fares.get(recommended_class)

        # Constraint D: Preferred class if strictly hard
        if pref_class and not class_match:
            if "preferred_class" in requirements.hard_constraints:
                is_feasible = False
                hard_violations.append(
                    f"Train does not offer preferred class '{pref_class}'. Available classes: {', '.join(applicable_classes)}."
                )

        # Constraint E: Budget Ceiling
        budget_match = True
        if requirements.budget_max is not None and recommended_fare is not None:
            if recommended_fare > requirements.budget_max:
                budget_match = False
                if "budget" in requirements.hard_constraints:
                    is_feasible = False
                    hard_violations.append(
                        f"Estimated fare (₹{recommended_fare}) exceeds maximum budget (₹{requirements.budget_max})."
                    )

        # 7. Check Preferred Train match
        is_pref_train = False
        pref_train_q = requirements.preferred_train_name_or_number
        if pref_train_q:
            pq = pref_train_q.strip().upper()
            if pq == train.train_number or pq in train.train_name.upper():
                is_pref_train = True

        # 8. Soft preferences and penalties
        soft_matches: list[str] = []
        soft_penalties: list[str] = []

        if is_pref_train:
            soft_matches.append(f"Matches passenger's preferred train: {train.train_name} ({train.train_number})")
        if class_match and pref_class:
            soft_matches.append(f"Offers preferred travel class: {pref_class}")
        elif pref_class:
            soft_penalties.append(f"Alternative class used: {recommended_class} (preferred was {pref_class})")

        if actual_buffer_minutes >= requested_buffer:
            extra_buffer = actual_buffer_minutes - requested_buffer
            soft_matches.append(f"Provides {actual_buffer_minutes}m buffer at venue ({extra_buffer}m extra margin)")
        
        # Early arrival penalty if arriving excessively early (> 8 hours early)
        if actual_buffer_minutes > 480:
            soft_penalties.append(f"Arrives {actual_buffer_minutes // 60} hours before meeting; requires extended wait")

        if recommended_fare and requirements.budget_max:
            if recommended_fare <= requirements.budget_max:
                soft_matches.append(f"Within budget: ₹{recommended_fare} (Max ₹{requirements.budget_max})")

        # 9. Scoring algorithm
        score = 0.0
        if is_feasible:
            # Base score for meeting all hard constraints
            score = 100.0

            # Buffer quality: optimal buffer between requested_buffer and requested_buffer + 60 mins
            if requested_buffer <= actual_buffer_minutes <= requested_buffer + 60:
                score += 25.0
            elif requested_buffer + 60 < actual_buffer_minutes <= requested_buffer + 180:
                score += 15.0
            elif actual_buffer_minutes > requested_buffer + 180:
                score += 5.0

            # Preferred train bonus
            if is_pref_train:
                score += 35.0

            # Class match bonus
            if class_match:
                score += 20.0

            # Duration bonus (faster train = higher score)
            duration_bonus = max(0.0, 15.0 - (train.duration_minutes / 60.0) * 1.5)
            score += duration_bonus

            # Proximity / shorter last mile
            if last_mile.distance_km < 15.0:
                score += 10.0
            elif last_mile.distance_km < 25.0:
                score += 5.0

            # Budget bonus (cheaper option within budget)
            if recommended_fare and requirements.budget_max:
                savings_pct = (requirements.budget_max - recommended_fare) / requirements.budget_max
                score += max(0.0, min(15.0, savings_pct * 15.0))
        else:
            # Negative or low score for infeasible
            score = -50.0 - len(hard_violations) * 20.0
            if actual_buffer_minutes < 0:
                score -= abs(actual_buffer_minutes) * 0.1

        # 10. Match Category and Explanation
        match_cat = "feasible_alternative" if is_feasible else "infeasible"
        
        if is_feasible:
            explanation = (
                f"Feasible journey: Departs {train.origin_station_name} at {train.departure_time} "
                f"({departure_date_str}), arrives {train.destination_station_name} at {train.arrival_time} "
                f"({arr_date_str}). Last-mile travel to {last_mile.destination_venue} takes ~{last_mile_mins} mins, "
                f"reaching venue by {venue_arr_dt.strftime('%H:%M')} with a comfortable {actual_buffer_minutes}-minute buffer."
            )
        else:
            explanation = (
                f"Does not meet requirements: {' '.join(hard_violations)}"
            )

        # 11. Create official booking handoff
        booking_handoff = None
        if recommended_class:
            booking_handoff = self.booking_service.create_booking_handoff(
                train=train,
                journey_date=departure_date_str,
                recommended_class=recommended_class,
                recommended_fare=recommended_fare,
            )

        return JourneyEvaluation(
            candidate_id=candidate_id,
            train_service=train,
            journey_date=departure_date_str,
            departure_datetime_iso=dep_dt.isoformat(),
            arrival_datetime_iso=arr_dt.isoformat(),
            meeting_datetime_iso=meeting_dt.isoformat(),
            last_mile_origin_station=train.destination_station_code,
            last_mile_destination_venue=last_mile.destination_venue,
            last_mile_duration_minutes=last_mile_mins,
            last_mile_distance_km=last_mile.distance_km,
            last_mile_mode=last_mile.transit_mode,
            latest_acceptable_station_arrival_iso=latest_station_arr_dt.isoformat(),
            actual_arrival_buffer_minutes=actual_buffer_minutes,
            is_feasible=is_feasible,
            is_preferred_train=is_pref_train,
            class_match=class_match,
            budget_match=budget_match,
            duration_match=(
                train.duration_minutes <= (requirements.maximum_journey_duration_minutes or 999999)
            ),
            hard_constraint_violations=hard_violations,
            soft_preference_matches=soft_matches,
            soft_preference_penalties=soft_penalties,
            score=round(score, 1),
            rank=0,
            match_category=match_cat,
            explanation=explanation,
            recommended_class=recommended_class,
            recommended_fare=recommended_fare,
            booking_handoff=booking_handoff,
        )
