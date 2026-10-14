"""
RailSaathi AI — journey feasibility evaluator.

Deterministic evaluation of provider candidates against the passenger's meeting: timezone-aware deadline and
buffer arithmetic, already-departed trains, hard constraints and soft preferences.

Deadline formula: latest acceptable station arrival = meeting start - requested buffer - last-mile time.
When the last-mile time is unknown it is not invented: it counts as zero and the evaluation says so.
"""

from datetime import datetime, timedelta

from app.journey.booking import BookingHandoffService
from app.journey.models import JourneyEvaluation, LastMileEstimate, TrainCandidate, TripRequirements

CLASS_ORDER = ["3A", "CC", "2A", "SL", "3E", "2S", "1A", "EC"]
EARLY_ARRIVAL_PENALTY_MINUTES = 480


def _hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _when(dt: datetime) -> str:
    return dt.strftime("%H:%M on %d %b")


class JourneyFeasibilityEvaluator:
    def __init__(self) -> None:
        self.booking_service = BookingHandoffService()

    def evaluate_candidate(
        self,
        candidate: TrainCandidate,
        requirements: TripRequirements,
        meeting_dt: datetime,
        last_mile: LastMileEstimate,
        now: datetime,
    ) -> JourneyEvaluation:
        tz = meeting_dt.tzinfo
        dep_dt = candidate.departure.astimezone(tz)
        arr_dt = candidate.arrival.astimezone(tz)
        departure_date = dep_dt.date()

        requested_buffer = requirements.required_arrival_buffer_minutes
        last_mile_mins = last_mile.duration_minutes or 0
        latest_station_arr = meeting_dt - timedelta(minutes=requested_buffer + last_mile_mins)
        venue_arr = arr_dt + timedelta(minutes=last_mile_mins)
        actual_buffer = int((meeting_dt - venue_arr).total_seconds() // 60)

        violations: list[str] = []
        if candidate.departure <= now:
            violations.append(f"This train has already departed ({_when(dep_dt)}).")
        if arr_dt > latest_station_arr:
            shortfall = int((arr_dt - latest_station_arr).total_seconds() // 60)
            violations.append(
                f"Reaches {candidate.destination_name} at {_when(arr_dt)}, {shortfall} min after the latest "
                f"acceptable station arrival ({_when(latest_station_arr)})."
            )
        elif venue_arr >= meeting_dt:
            violations.append(f"Estimated venue arrival ({_when(venue_arr)}) is after the meeting starts.")

        max_duration = requirements.maximum_journey_duration_minutes
        duration_match = max_duration is None or candidate.duration_minutes <= max_duration
        if not duration_match and "max_duration" in requirements.hard_constraints:
            violations.append(
                f"Journey duration ({candidate.duration_minutes} min) exceeds the {max_duration}-min limit.")

        pref_class = str(requirements.preferred_class) if requirements.preferred_class else None
        class_match = bool(pref_class and pref_class in candidate.classes)
        if class_match:
            recommended_class = pref_class
        else:
            recommended_class = next((c for c in CLASS_ORDER if c in candidate.classes),
                                     candidate.classes[0] if candidate.classes else None)
        recommended_fare = candidate.fares.get(recommended_class) if recommended_class else None
        if pref_class and not class_match and "preferred_class" in requirements.hard_constraints:
            offered = ", ".join(candidate.classes) or "not listed by the data source"
            violations.append(f"Does not offer class {pref_class} (classes: {offered}).")

        budget_match = True
        if requirements.budget_max is not None and recommended_fare is not None:
            budget_match = recommended_fare <= requirements.budget_max
            if not budget_match and "budget" in requirements.hard_constraints:
                violations.append(f"Fare ₹{recommended_fare:.0f} exceeds the ₹{requirements.budget_max:.0f} budget.")

        is_pref_train = False
        if requirements.preferred_train_name_or_number:
            q = requirements.preferred_train_name_or_number.strip().upper()
            is_pref_train = any(q == leg.train_number.upper() or q in leg.train_name.upper()
                                for leg in candidate.legs)

        matches: list[str] = []
        penalties: list[str] = []
        if is_pref_train:
            matches.append(f"Matches your preferred train ({candidate.train_number}).")
        if class_match:
            matches.append(f"Offers your preferred class {pref_class}.")
        elif pref_class:
            penalties.append(
                f"Preferred class {pref_class} not listed; {recommended_class or 'class unknown'} shown instead.")
        if actual_buffer >= requested_buffer:
            matches.append(f"Leaves a {actual_buffer}-min buffer before the meeting.")
        if actual_buffer > EARLY_ARRIVAL_PENALTY_MINUTES:
            penalties.append(f"Arrives about {actual_buffer // 60} hours before the meeting.")
        if requirements.budget_max is not None and recommended_fare is not None and budget_match:
            matches.append(f"Within budget: ₹{recommended_fare:.0f} (max ₹{requirements.budget_max:.0f}).")
        if last_mile.duration_minutes is None:
            penalties.append("Station-to-venue travel time is unknown and is not included in the buffer.")

        is_feasible = not violations
        score = self._score(is_feasible, actual_buffer, requested_buffer, is_pref_train, class_match,
                            candidate, last_mile, recommended_fare, requirements, len(violations))

        if is_feasible:
            lm = (f"about {last_mile_mins} min by {last_mile.transit_mode} to {last_mile.destination_venue}"
                  if last_mile.duration_minutes is not None else "the onward trip to the venue is not estimated")
            explanation = (
                f"Departs {candidate.origin_name} at {_when(dep_dt)} and reaches {candidate.destination_name} at "
                f"{_when(arr_dt)}; {lm}. Estimated buffer before the meeting: {actual_buffer} min."
            )
        else:
            explanation = "Does not meet your requirements: " + " ".join(violations)

        # Booking links only for trains the passenger can actually take (feasible, not departed).
        handoff = self.booking_service.create_booking_handoff(
            candidate, departure_date, recommended_class, recommended_fare) if is_feasible else None
        return JourneyEvaluation(
            candidate_id=f"cand-{candidate.option_id}",
            candidate=candidate,
            journey_date=departure_date,
            meeting_datetime=meeting_dt,
            last_mile_origin_station=candidate.destination_code,
            last_mile_destination_venue=last_mile.destination_venue,
            last_mile_duration_minutes=last_mile.duration_minutes,
            last_mile_distance_km=last_mile.distance_km,
            last_mile_mode=last_mile.transit_mode if last_mile.duration_minutes is not None else None,
            latest_acceptable_station_arrival=latest_station_arr,
            actual_arrival_buffer_minutes=actual_buffer,
            is_feasible=is_feasible,
            is_preferred_train=is_pref_train,
            class_match=class_match,
            budget_match=budget_match,
            duration_match=duration_match,
            hard_constraint_violations=violations,
            soft_preference_matches=matches,
            soft_preference_penalties=penalties,
            score=round(score, 1),
            match_category="feasible_alternative" if is_feasible else "infeasible",
            explanation=explanation,
            recommended_class=recommended_class,
            recommended_fare=recommended_fare,
            booking_handoff=handoff,
        )

    @staticmethod
    def _score(feasible: bool, actual: int, requested: int, preferred: bool, class_match: bool,
               candidate: TrainCandidate, last_mile: LastMileEstimate, fare: float | None,
               req: TripRequirements, n_violations: int) -> float:
        if not feasible:
            score = -50.0 - n_violations * 20.0
            return score - abs(actual) * 0.1 if actual < 0 else score
        score = 100.0
        if requested <= actual <= requested + 60:
            score += 25.0
        elif actual <= requested + 180:
            score += 15.0
        else:
            score += 5.0
        if preferred:
            score += 35.0
        if class_match:
            score += 20.0
        score += max(0.0, 15.0 - (candidate.duration_minutes / 60.0) * 1.5)
        if last_mile.distance_km is not None:
            score += 10.0 if last_mile.distance_km < 15.0 else 5.0 if last_mile.distance_km < 25.0 else 0.0
        if fare is not None and req.budget_max:
            score += max(0.0, min(15.0, (req.budget_max - fare) / req.budget_max * 15.0))
        return score
