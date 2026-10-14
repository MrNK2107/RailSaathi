"""
RailSaathi AI — goal-based journey planner.

Deterministic pipeline: requirements (structured fields and/or a parsed prompt, never hidden defaults) ->
origin/destination resolution (StationResolver + venue directory) -> provider search through
`provider_adapter` -> feasibility -> ranking. Dates are timezone-aware via the injected `Clock`; meetings in the
past or beyond the planning window are rejected.
"""

import re
import uuid
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.clock import Clock
from app.domain.enums import TravelClass
from app.harness.errors import PlannerError
from app.journey.feasibility import JourneyFeasibilityEvaluator
from app.journey.models import (
    GoalPlanRequest,
    JourneyPlanResponse,
    LastMileEstimate,
    ResolvedPlace,
    StationCandidate,
    TripRequirements,
)
from app.journey.provider_adapter import ProviderJourneyAdapter
from app.journey.ranking import JourneyRankingEngine, plan_sources
from app.journey.venues import Venue, VenueDirectory, estimate_last_mile_minutes
from app.providers.base import JourneyProvider
from app.stations.resolver import StationResolver

DEFAULT_BUFFER_MINUTES = 45


@dataclass(frozen=True)
class _Ask:
    """A clarification the planner needs before it can search."""

    question: str
    field: str
    candidates: list[str] = dataclass_field(default_factory=list)

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MONTH_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_STOP = r"(?=\s+(?:to|in|on|at|by|before|from|for|and|tomorrow|today)\b|\s*[.,;!?]|$)"
_PLACE = r"([A-Za-z][A-Za-z0-9&'\- ]*?)"
_VENUE_PATTERNS = [rf"\b(?:meeting|appointment|event|interview|conference|exam)\s+at\s+{_PLACE}{_STOP}",
                   rf"\b(?:reach|reaching|get to|going to)\s+{_PLACE}{_STOP}",
                   rf"\bto\s+{_PLACE}{_STOP}"]
_ORIGIN_PATTERN = rf"\b(?:from|leaving|departing|start from|starting from)\s+{_PLACE}{_STOP}"
_TRAIN_TYPES = ["vande bharat", "jan shatabdi", "shatabdi", "rajdhani", "duronto", "garib rath", "tejas",
                "humsafar"]
_CLASS_PATTERNS = [
    (r"\b(ac\s*3[\s-]*tier|3a|3[\s-]*ac|third\s*ac)\b", TravelClass.THREE_A),
    (r"\b(ac\s*2[\s-]*tier|2a|2[\s-]*ac|second\s*ac)\b", TravelClass.TWO_A),
    (r"\b(executive\s*chair\s*car|ec)\b", TravelClass.EC),
    (r"\b(ac\s*chair\s*car|cc|chair\s*car)\b", TravelClass.CC),
    (r"\b(sleeper|sl)\b", TravelClass.SL),
    (r"\b(second\s*sitting|2s)\b", TravelClass.TWO_S),
]


def _resolve_day_month(day: int, month: int, year: int | None, today: date) -> date | None:
    try:
        if year is not None:
            return date(year, month, day)
        candidate = date(today.year, month, day)
        return candidate if candidate >= today else date(today.year + 1, month, day)
    except ValueError:
        return None


def _parse_date(text: str, today: date) -> date | None:
    lowered = text.lower()
    iso = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None
    m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH_RE}\b(?:,?\s+(\d{{4}}))?", lowered)
    if m:
        return _resolve_day_month(int(m.group(1)), MONTHS[m.group(2)[:3]], int(m.group(3)) if m.group(3) else None,
                                  today)
    m = re.search(rf"\b{_MONTH_RE}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}}))?", lowered)
    if m:
        return _resolve_day_month(int(m.group(2)), MONTHS[m.group(1)[:3]], int(m.group(3)) if m.group(3) else None,
                                  today)
    if re.search(r"\bday after tomorrow\b", lowered):
        return today + timedelta(days=2)
    if re.search(r"\btomorrow\b", lowered):
        return today + timedelta(days=1)
    if re.search(r"\btoday\b", lowered):
        return today
    return None


def _parse_time(text: str) -> str | None:
    lowered = text.lower()
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)", lowered)
    if m:
        hour, mins = int(m.group(1)), int(m.group(2) or 0)
        if not (1 <= hour <= 12 and mins < 60):
            return None
        pm = m.group(3).startswith("p")
        hour = (hour % 12) + (12 if pm else 0)
        return f"{hour:02d}:{mins:02d}"
    m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def parse_requirements_from_text(text: str, today: date) -> dict:
    """Extract only what the prompt states. Missing fields stay missing (the planner asks for them)."""
    found: dict = {}
    lowered = text.lower()
    m = re.search(_ORIGIN_PATTERN, text, re.IGNORECASE)
    if m:
        found["origin"] = m.group(1).strip()
    for pattern in _VENUE_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m and m.group(1).strip().lower() != found.get("origin", "").lower():
            found["destination_venue"] = m.group(1).strip()
            break
    if (d := _parse_date(text, today)) is not None:
        found["meeting_date"] = d
    if (t := _parse_time(text)) is not None:
        found["meeting_time"] = t

    m = re.search(r"(\d+)\s*(?:minutes?|mins?)\s*(?:early|buffer|before)", lowered)
    if m:
        found["required_arrival_buffer_minutes"] = min(int(m.group(1)), 720)
    elif m := re.search(r"\b(an|1|2|3)\s+hours?\s+(?:early|before|buffer)", lowered):
        found["required_arrival_buffer_minutes"] = 60 * (1 if m.group(1) == "an" else int(m.group(1)))

    for pattern, cls in _CLASS_PATTERNS:
        if re.search(pattern, lowered):
            found["preferred_class"] = cls
            break

    budget = re.search(r"(?:under|less than|budget of|max(?:imum)?|within|below)\s*(?:rs\.?|inr|₹)?\s*(\d+)", lowered)
    if budget:
        found["budget_max"] = float(budget.group(1))
    without_budget = lowered[:budget.start()] + lowered[budget.end():] if budget else lowered
    number = re.search(r"\b(\d{5})\b", without_budget)
    if number:
        found["preferred_train_name_or_number"] = number.group(1)
    else:
        named = next((t for t in _TRAIN_TYPES if t in lowered), None)
        if named:
            found["preferred_train_name_or_number"] = named.title()
    return found


class GoalPlanner:
    """End-to-end goal-based planner over the container's JourneyProvider."""

    def __init__(self, provider: JourneyProvider, resolver: StationResolver, venues: VenueDirectory, clock: Clock,
                 tz: str, max_planning_days: int) -> None:
        self._provider = provider
        self._resolver = resolver
        self._venues = venues
        self._clock = clock
        self._tz = ZoneInfo(tz)
        self._max_days = max_planning_days
        self._adapter = ProviderJourneyAdapter(provider, tz, clock)
        self._evaluator = JourneyFeasibilityEvaluator()
        self._ranking = JourneyRankingEngine()

    @staticmethod
    def new_trace_id() -> str:
        return f"plan-{uuid.uuid4().hex[:10]}"

    # ---- requirements -------------------------------------------------------------------------------------
    def requirements_from_request(self, request: GoalPlanRequest) -> tuple[TripRequirements | None, list[str]]:
        """(requirements, missing_fields). Structured fields override whatever the prompt says."""
        parsed = parse_requirements_from_text(request.prompt, self._clock.now().astimezone(self._tz).date()) if request.prompt else {}
        merged = {**parsed, **request.model_dump(exclude_none=True, exclude={"prompt"})}
        missing = [f for f in ("origin",) if not merged.get(f)]
        if not merged.get("destination_venue") and not merged.get("destination_station"):
            missing.append("destination_venue")
        missing += [f for f in ("meeting_date", "meeting_time") if not merged.get(f)]
        if missing:
            return None, missing
        if "required_arrival_buffer_minutes" not in merged:
            merged["required_arrival_buffer_minutes"] = DEFAULT_BUFFER_MINUTES
            merged["assumptions"] = [f"Assumed a {DEFAULT_BUFFER_MINUTES}-minute buffer at the venue before the "
                                     "meeting. Change it if you need more or less time."]
        return TripRequirements.model_validate(merged), []

    def clarification(self, missing: list[str], trace_id: str, question: str | None = None,
                      requirements: TripRequirements | None = None,
                      candidates: list[str] | None = None) -> JourneyPlanResponse:
        labels = {"origin": "where you are starting from", "destination_venue": "the venue or destination",
                  "destination_station": "the arrival station", "meeting_date": "the meeting date",
                  "meeting_time": "the meeting time"}
        question = question or "Please tell me " + ", ".join(labels.get(f, f) for f in missing) + "."
        provenance = self._provider.provenance()
        return JourneyPlanResponse(status="clarification_required", summary=question, provenance=provenance,
                                   trip_requirements=requirements, clarification_question=question,
                                   missing_fields=missing, place_candidates=candidates or [],
                                   sources=plan_sources(provenance), trace_id=trace_id)

    # ---- planning -----------------------------------------------------------------------------------------
    def meeting_datetime(self, req: TripRequirements) -> datetime:
        return datetime.combine(req.meeting_date, time.fromisoformat(req.meeting_time), tzinfo=self._tz)

    def check_dates(self, req: TripRequirements) -> datetime:
        meeting_dt = self.meeting_datetime(req)
        now = self._clock.now()
        if meeting_dt <= now:
            raise PlannerError("meeting_in_past", "The meeting time has already passed. Choose a future date and time.",
                               {"field": "meeting_date"})
        if req.meeting_date > now.astimezone(self._tz).date() + timedelta(days=self._max_days):
            raise PlannerError("date_out_of_range", f"Meetings can be planned up to {self._max_days} days ahead.",
                               {"field": "meeting_date", "max_days": self._max_days})
        return meeting_dt

    def plan(self, req: TripRequirements, trace_id: str) -> JourneyPlanResponse:
        meeting_dt = self.check_dates(req)
        now = self._clock.now()

        origin = self._resolve(req.origin, "origin")
        if isinstance(origin, _Ask):
            return self.clarification([origin.field], trace_id, origin.question, req, origin.candidates)
        destination, venue = self._resolve_destination(req)
        if isinstance(destination, _Ask):
            return self.clarification([destination.field], trace_id, destination.question, req,
                                      destination.candidates)

        today = now.astimezone(self._tz).date()
        dates = [d for d in (req.meeting_date - timedelta(days=1), req.meeting_date) if d >= today]
        result = self._adapter.search(origin.station_codes, destination.station_codes, dates)
        origin_stations = [self._station(code, None) for code in origin.station_codes]
        dest_stations = [self._station(code, venue) for code in destination.station_codes]
        provenance = result.provenance or self._provider.provenance()

        if result.error:
            return JourneyPlanResponse(
                status="provider_unavailable", summary=provenance.note, provenance=provenance, trip_requirements=req,
                resolved_origin=origin, resolved_destination=destination, candidate_origin_stations=origin_stations,
                candidate_destination_stations=dest_stations, sources=plan_sources(provenance), trace_id=trace_id)

        evaluations = [
            self._evaluator.evaluate_candidate(c, req, meeting_dt, self._last_mile(c.destination_code, venue), now)
            for c in result.candidates
        ]
        return self._ranking.rank_and_assemble_plan(req, evaluations, provenance, origin, destination,
                                                    origin_stations, dest_stations, trace_id)

    # ---- resolution helpers -------------------------------------------------------------------------------
    def _resolve(self, query: str, field: str) -> ResolvedPlace | _Ask:
        res = self._resolver.resolve(query)
        if res.status == "resolved" and res.place is not None:
            return ResolvedPlace(query=query, display_name=res.place.label, kind=res.place.kind,
                                 station_codes=list(res.place.station_codes), source="station catalogue")
        if res.status == "ambiguous":
            labels = [p.label for p in res.candidates]
            return _Ask(f"Which place did you mean by '{query}'? Options: {', '.join(labels)}.", field, labels)
        return _Ask(f"I could not find a station or city called '{query}'. Please give a nearby railway station.",
                    field)

    def _resolve_destination(self, req: TripRequirements) -> tuple[ResolvedPlace | _Ask, Venue | None]:
        venue = self._venues.find(req.destination_venue) if req.destination_venue else None
        if req.destination_station:
            return self._resolve(req.destination_station, "destination_station"), venue
        assert req.destination_venue is not None  # requirements guarantee a venue or a station
        if venue is not None:
            codes = [s.code for s in venue.access_stations if self._provider.station(s.code) is not None]
            if codes:
                return ResolvedPlace(query=req.destination_venue, display_name=venue.name, kind="venue",
                                     city=venue.city, station_codes=codes, source="venue directory"), venue
        else:
            place = self._resolve(req.destination_venue, "destination_station")  # free text naming a station/city
            if isinstance(place, ResolvedPlace):
                return place, None
        question = (f"I don't have '{req.destination_venue}' in my venue list. Which railway station should I plan "
                    "your arrival at? You can also tell me how long the trip from that station to the venue takes.")
        return _Ask(question, "destination_station"), None

    def _station(self, code: str, venue: Venue | None) -> StationCandidate:
        record = self._provider.station(code)
        distance = venue.distance_to(code) if venue else None
        return StationCandidate(
            station_code=code, station_name=record.name if record else code, distance_to_venue_km=distance,
            estimated_last_mile_minutes=estimate_last_mile_minutes(distance) if distance is not None else None,
            last_mile_mode="cab" if distance is not None else None)

    @staticmethod
    def _last_mile(station_code: str, venue: Venue | None) -> LastMileEstimate:
        distance = venue.distance_to(station_code) if venue else None
        if venue is None or distance is None:
            return LastMileEstimate(station_code=station_code, destination_venue=venue.name if venue else None,
                                    distance_km=None, duration_minutes=None, transit_mode=None, confidence="unknown")
        return LastMileEstimate(station_code=station_code, destination_venue=venue.name, distance_km=distance,
                                duration_minutes=estimate_last_mile_minutes(distance))
