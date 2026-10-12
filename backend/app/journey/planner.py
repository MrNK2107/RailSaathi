"""
RailSathi AI — Journey Planner Orchestrator

End-to-end deterministic pipeline for planning goal-based train journeys.
Connects requirement extraction, location resolution, timetable discovery,
feasibility evaluation, ranking, and official booking handoffs.
"""

import re
import uuid
import logging

from app.journey.models import (
    TripRequirements,
    JourneyEvaluation,
    JourneyPlanResponse,
)
from app.journey.location import LocationResolutionService
from app.journey.timetable import TrainSearchService
from app.journey.feasibility import JourneyFeasibilityEvaluator
from app.journey.ranking import JourneyRankingEngine

logger = logging.getLogger("railsaathi.journey.planner")


def parse_requirements_from_text(text: str) -> TripRequirements:
    """
    Deterministic rule-based requirement extractor from natural language prompts.
    Extracts origin, destination venue, date, time, buffer, preferred train, class, and budget.
    """
    t = text.strip()
    t_lower = t.lower()

    # 1. Origin extraction
    origin = "Bengaluru"  # default if not detected
    origin_matches = re.findall(
        r"(?:from|leaving|departing|travelling from|traveling from|start from)\s+([A-Za-z\s]+?)(?:\s+to|\s+at|\s+on|\.|\,|$)",
        t,
        re.IGNORECASE
    )
    if origin_matches:
        origin = origin_matches[0].strip().title()
    elif "from bengaluru" in t_lower or "from bangalore" in t_lower:
        origin = "Bengaluru"
    elif "from chennai" in t_lower:
        origin = "Chennai"
    elif "from delhi" in t_lower or "from new delhi" in t_lower:
        origin = "Delhi"
    elif "from mumbai" in t_lower:
        origin = "Mumbai"
    elif "from hyderabad" in t_lower or "from secunderabad" in t_lower:
        origin = "Hyderabad"

    # 2. Destination Venue extraction
    destination_venue = "Tidel Park"
    venue_matches = re.findall(
        r"(?:meeting at|appointment at|event at|reaching|reach|destination|venue|to)\s+([A-Za-z0-9\s]+?)(?:\s+in|\s+at|\s+on|\s+before|\.|\,|$)",
        t,
        re.IGNORECASE
    )
    if venue_matches:
        destination_venue = venue_matches[0].strip().title()
    elif "tidel park" in t_lower:
        destination_venue = "Tidel Park"
    elif "iit madras" in t_lower:
        destination_venue = "IIT Madras"
    elif "whitefield" in t_lower:
        destination_venue = "Whitefield"
    elif "electronic city" in t_lower:
        destination_venue = "Electronic City"
    elif "cyber city" in t_lower:
        destination_venue = "Cyber City Gurugram"
    elif "bkc" in t_lower or "bandra kurla" in t_lower:
        destination_venue = "Bandra Kurla Complex (BKC)"
    elif "hitec city" in t_lower:
        destination_venue = "HITEC City"

    # Destination City
    dest_city = None
    if "in chennai" in t_lower or "chennai" in t_lower:
        dest_city = "Chennai"
    elif "in bengaluru" in t_lower or "in bangalore" in t_lower or "bengaluru" in t_lower:
        dest_city = "Bengaluru"
    elif "in delhi" in t_lower or "delhi" in t_lower:
        dest_city = "Delhi"
    elif "in mumbai" in t_lower or "mumbai" in t_lower:
        dest_city = "Mumbai"
    elif "in hyderabad" in t_lower or "hyderabad" in t_lower:
        dest_city = "Hyderabad"

    # 3. Date extraction (YYYY-MM-DD or DD Month or relative "tomorrow")
    # Default to a realistic target date
    meeting_date = "2026-10-25"

    # Check for patterns like "25 October", "25th Oct", "2026-10-25"
    iso_date_match = re.search(r"\b(202\d-\d{2}-\d{2})\b", t)
    if iso_date_match:
        meeting_date = iso_date_match.group(1)
    else:
        month_match = re.search(
            r"(\d{1,2})(?:st|nd|rd|th)?\s+(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)(?:\s+(202\d))?",
            t_lower
        )
        if month_match:
            day = int(month_match.group(1))
            month_str = month_match.group(2)[:3]
            year = int(month_match.group(3)) if month_match.group(3) else 2026
            months = {
                "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
            }
            m_num = months.get(month_str, 10)
            meeting_date = f"{year:04d}-{m_num:02d}-{day:02d}"

    # 4. Time extraction (e.g. 10:00 AM, 10 AM, 14:30)
    meeting_time = "10:00"
    time_match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)", t_lower)
    if time_match:
        hour = int(time_match.group(1))
        mins = int(time_match.group(2)) if time_match.group(2) else 0
        ampm = time_match.group(3).replace(".", "")
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        meeting_time = f"{hour:02d}:{mins:02d}"
    else:
        # 24-hr format like 10:00 or 14:30
        time_24_match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", t)
        if time_24_match:
            meeting_time = f"{int(time_24_match.group(1)):02d}:{int(time_24_match.group(2)):02d}"

    # 5. Buffer minutes (e.g. "45 minutes early", "at least 1 hour early", "30 mins buffer")
    buffer_minutes = 45
    buffer_match = re.search(r"(\d+)\s*(?:minutes?|mins?)\s*(?:early|buffer|before)", t_lower)
    if buffer_match:
        buffer_minutes = int(buffer_match.group(1))
    elif "1 hour early" in t_lower or "an hour early" in t_lower:
        buffer_minutes = 60
    elif "2 hours early" in t_lower:
        buffer_minutes = 120

    # 6. Preferred Class (e.g. "AC 3-tier", "3A", "CC", "2A", "Sleeper", "SL")
    preferred_class = None
    if re.search(r"\b(ac\s*3[\s-]*tier|3a|3[\s-]*ac|third\s*ac)\b", t_lower):
        preferred_class = "3A"
    elif re.search(r"\b(ac\s*2[\s-]*tier|2a|2[\s-]*ac|second\s*ac)\b", t_lower):
        preferred_class = "2A"
    elif re.search(r"\b(ac\s*chair\s*car|cc|chair\s*car)\b", t_lower):
        preferred_class = "CC"
    elif re.search(r"\b(1a|1[\s-]*ac|first\s*ac)\b", t_lower):
        preferred_class = "1A"
    elif re.search(r"\b(sleeper|sl)\b", t_lower):
        preferred_class = "SL"
    elif re.search(r"\b(3e|3[\s-]*economy|ac\s*3\s*economy)\b", t_lower):
        preferred_class = "3E"

    # 7. Preferred Train (e.g. "Vande Bharat", "Shatabdi", "12678", "Lalbagh")
    preferred_train = None
    if "vande bharat" in t_lower:
        preferred_train = "Vande Bharat"
    elif "shatabdi" in t_lower:
        preferred_train = "Shatabdi"
    elif "brindavan" in t_lower:
        preferred_train = "Brindavan Express"
    elif "lalbagh" in t_lower:
        preferred_train = "Lalbagh Express"
    elif "chennai mail" in t_lower:
        preferred_train = "Chennai Mail"
    elif "rajdhani" in t_lower:
        preferred_train = "Rajdhani Express"

    # Train number pattern (5 digits)
    train_num_match = re.search(r"\b(1\d{4}|2\d{4})\b", t)
    if train_num_match:
        preferred_train = train_num_match.group(1)

    # 8. Budget constraints (e.g. "under 1500", "budget of 1000", "affordable")
    budget_max = None
    budget_match = re.search(r"(?:under|less than|budget of|max(?:imum)?|within|below)\s*(?:rs\.?|inr|₹)?\s*(\d+)", t_lower)
    if budget_match:
        budget_max = float(budget_match.group(1))

    soft_preferences = []
    if "affordable" in t_lower or "cheap" in t_lower:
        soft_preferences.append("prefer_affordable")
    if preferred_class:
        soft_preferences.append(f"prefer_class_{preferred_class}")
    if preferred_train:
        soft_preferences.append(f"prefer_train_{preferred_train}")

    missing_fields = []
    if not origin:
        missing_fields.append("origin")
    if not destination_venue:
        missing_fields.append("destination_venue")

    return TripRequirements(
        origin=origin,
        destination_venue=destination_venue,
        destination_city=dest_city,
        meeting_date=meeting_date,
        meeting_time=meeting_time,
        required_arrival_buffer_minutes=buffer_minutes,
        preferred_train_name_or_number=preferred_train,
        preferred_class=preferred_class,
        budget_max=budget_max,
        hard_constraints=["deadline", "arrival_buffer"],
        soft_preferences=soft_preferences,
        missing_required_fields=missing_fields,
    )


class JourneyPlanner:
    """End-to-end Goal-Based Train Journey Planner."""

    def __init__(self):
        self.location_service = LocationResolutionService()
        self.train_service = TrainSearchService()
        self.feasibility_evaluator = JourneyFeasibilityEvaluator()
        self.ranking_engine = JourneyRankingEngine()

    def plan_journey(
        self,
        requirements: TripRequirements,
        trace_id: str | None = None,
    ) -> JourneyPlanResponse:
        """
        Execute full journey planning workflow:
        1. Resolve origin & destination locations
        2. Find candidate stations
        3. Search train schedules
        4. Calculate last mile & evaluate feasibility
        5. Rank candidates & synthesize recommendations
        """
        tid = trace_id or f"trace-plan-{uuid.uuid4().hex[:10]}"

        # Step 1: Resolve Locations
        resolved_origin = self.location_service.resolve_location(requirements.origin)
        resolved_dest = self.location_service.resolve_location(
            requirements.destination_venue,
            context_city=requirements.destination_city
        )

        # Step 2: Find Candidate Stations
        origin_stations = self.location_service.find_nearby_stations(resolved_origin)
        dest_stations = self.location_service.find_nearby_stations(resolved_dest)

        if not origin_stations or not dest_stations:
            return self.ranking_engine.rank_and_assemble_plan(
                requirements=requirements,
                evaluations=[],
                resolved_origin=resolved_origin,
                resolved_destination=resolved_dest,
                candidate_origin_stations=origin_stations,
                candidate_destination_stations=dest_stations,
                trace_id=tid,
                tool_calls_made=3,
                rounds_used=1,
            )

        origin_codes = [s.station_code for s in origin_stations]
        dest_codes = [s.station_code for s in dest_stations]

        # Step 3: Search Verified Train Schedules
        candidate_trains = self.train_service.search_trains(
            origin_stations=origin_codes,
            destination_stations=dest_codes,
            journey_date=requirements.meeting_date,
            preferred_class=requirements.preferred_class,
            preferred_train_query=requirements.preferred_train_name_or_number,
        )

        # Also search for preferred train explicitly if named and not in initial batch
        if requirements.preferred_train_name_or_number:
            pref_t = self.train_service.get_train_by_number_or_name(
                requirements.preferred_train_name_or_number
            )
            if pref_t and not any(t.train_number == pref_t.train_number for t in candidate_trains):
                candidate_trains.append(pref_t)

        # Step 4: Calculate Last-Mile & Evaluate Feasibility
        evaluations: list[JourneyEvaluation] = []
        for train in candidate_trains:
            # Calculate last mile from this train's destination station to the venue
            last_mile = self.location_service.estimate_last_mile(
                station_code=train.destination_station_code,
                destination_venue=requirements.destination_venue,
                venue_location=resolved_dest,
            )

            ev = self.feasibility_evaluator.evaluate_candidate(
                train=train,
                requirements=requirements,
                last_mile=last_mile,
            )
            evaluations.append(ev)

        # Step 5: Deterministic Ranking & Assembly
        return self.ranking_engine.rank_and_assemble_plan(
            requirements=requirements,
            evaluations=evaluations,
            resolved_origin=resolved_origin,
            resolved_destination=resolved_dest,
            candidate_origin_stations=origin_stations,
            candidate_destination_stations=dest_stations,
            trace_id=tid,
            tool_calls_made=len(candidate_trains) + 4,
            rounds_used=1,
        )
