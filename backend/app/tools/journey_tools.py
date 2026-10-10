"""
RailSathi AI — Journey Planner Tools

Registered tool declarations and handlers for the Goal-Based Train Journey Planner.
Enables function calling by Gemini / Agent Controller with strict validation and schemas.
"""

import json
import logging
from typing import Any

from app.journey.models import TripRequirements
from app.journey.location import LocationResolutionService
from app.journey.timetable import TrainSearchService
from app.journey.feasibility import JourneyFeasibilityEvaluator
from app.journey.ranking import JourneyRankingEngine
from app.journey.booking import BookingHandoffService, is_url_safe_and_allowlisted
from app.journey.planner import parse_requirements_from_text, JourneyPlanner

logger = logging.getLogger("railsaathi.tools.journey")

# Instantiate singleton services
_location_service = LocationResolutionService()
_train_service = TrainSearchService()
_feasibility_evaluator = JourneyFeasibilityEvaluator()
_ranking_engine = JourneyRankingEngine()
_booking_service = BookingHandoffService()
_planner = JourneyPlanner()

# Journey Tool Schemas for Gemini / Controller
JOURNEY_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "parse_trip_requirements": {
        "name": "parse_trip_requirements",
        "description": (
            "Extract structured travel requirements (origin, destination venue, date, "
            "meeting time, buffer minutes, preferred class, budget) from natural language passenger text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "user_text": {
                    "type": "string",
                    "description": "Passenger's natural language journey description or prompt.",
                },
            },
            "required": ["user_text"],
        },
    },
    "resolve_location": {
        "name": "resolve_location",
        "description": "Resolve a destination venue, address, or origin city to geographic coordinates.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Venue name, landmark, or city to resolve (e.g. 'Tidel Park, Chennai').",
                },
                "context_city": {
                    "type": "string",
                    "description": "Optional city context to disambiguate the venue.",
                },
            },
            "required": ["query"],
        },
    },
    "find_nearby_stations": {
        "name": "find_nearby_stations",
        "description": "Find candidate railway stations serving an origin city or destination venue area.",
        "parameters": {
            "type": "object",
            "properties": {
                "city_or_location": {
                    "type": "string",
                    "description": "City name or resolved location query.",
                },
            },
            "required": ["city_or_location"],
        },
    },
    "estimate_last_mile": {
        "name": "estimate_last_mile",
        "description": "Estimate travel duration and distance from a railway station to a venue.",
        "parameters": {
            "type": "object",
            "properties": {
                "station_code": {
                    "type": "string",
                    "description": "Railway station code (e.g. 'MAS', 'SBC', 'MS').",
                },
                "destination_venue": {
                    "type": "string",
                    "description": "Destination venue or landmark name.",
                },
            },
            "required": ["station_code", "destination_venue"],
        },
    },
    "search_trains": {
        "name": "search_trains",
        "description": "Search verified train services between sets of origin and destination station codes.",
        "parameters": {
            "type": "object",
            "properties": {
                "origin_stations": {
                    "type": "string",
                    "description": "Comma-separated list of origin station codes (e.g. 'SBC,YPR,SMVB').",
                },
                "destination_stations": {
                    "type": "string",
                    "description": "Comma-separated list of destination station codes (e.g. 'MAS,MS,TBM').",
                },
                "journey_date": {
                    "type": "string",
                    "description": "Journey date in YYYY-MM-DD format.",
                },
                "preferred_class": {
                    "type": "string",
                    "description": "Optional travel class code (e.g. '3A', '2A', 'CC').",
                },
            },
            "required": ["origin_stations", "destination_stations", "journey_date"],
        },
    },
    "get_train_details": {
        "name": "get_train_details",
        "description": "Retrieve verified schedule, stops, classes, and fares for a specific train number or name.",
        "parameters": {
            "type": "object",
            "properties": {
                "train_query": {
                    "type": "string",
                    "description": "5-digit train number (e.g. '20608') or train name (e.g. 'Vande Bharat').",
                },
            },
            "required": ["train_query"],
        },
    },
    "evaluate_journey_feasibility": {
        "name": "evaluate_journey_feasibility",
        "description": "Deterministically calculate deadline arrival buffer and feasibility for a candidate train.",
        "parameters": {
            "type": "object",
            "properties": {
                "train_number": {
                    "type": "string",
                    "description": "5-digit train number.",
                },
                "meeting_date": {
                    "type": "string",
                    "description": "Meeting date (YYYY-MM-DD).",
                },
                "meeting_time": {
                    "type": "string",
                    "description": "Meeting start time (HH:MM).",
                },
                "destination_venue": {
                    "type": "string",
                    "description": "Venue name.",
                },
                "required_buffer_minutes": {
                    "type": "integer",
                    "description": "Desired buffer at venue in minutes (default 45).",
                },
            },
            "required": ["train_number", "meeting_date", "meeting_time", "destination_venue"],
        },
    },
    "plan_goal_based_journey": {
        "name": "plan_goal_based_journey",
        "description": (
            "Complete goal-based journey planner tool. Extracts requirements, resolves locations and stations, "
            "searches schedules, calculates buffers, and returns ranked recommendations with booking links."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "passenger_prompt": {
                    "type": "string",
                    "description": "Complete passenger journey request.",
                },
                "origin": {
                    "type": "string",
                    "description": "Optional starting city.",
                },
                "destination_venue": {
                    "type": "string",
                    "description": "Optional destination venue.",
                },
                "meeting_date": {
                    "type": "string",
                    "description": "Optional date (YYYY-MM-DD).",
                },
                "meeting_time": {
                    "type": "string",
                    "description": "Optional meeting time (HH:MM).",
                },
                "preferred_class": {
                    "type": "string",
                    "description": "Optional preferred class.",
                },
                "preferred_train": {
                    "type": "string",
                    "description": "Optional preferred train.",
                },
                "buffer_minutes": {
                    "type": "integer",
                    "description": "Optional buffer minutes (default 45).",
                },
            },
            "required": ["passenger_prompt"],
        },
    },
}


def validate_journey_tool_args(tool_name: str, args: dict) -> tuple[bool, str | None]:
    """Validate journey tool arguments against schema."""
    if tool_name not in JOURNEY_TOOL_SCHEMAS:
        return False, f"Unknown journey tool: {tool_name}"

    schema = JOURNEY_TOOL_SCHEMAS[tool_name]
    required = schema["parameters"].get("required", [])

    for r in required:
        if r not in args or args[r] is None:
            return False, f"Missing required parameter '{r}' for tool '{tool_name}'"

    return True, None


def execute_journey_tool(tool_name: str, args: dict) -> dict[str, Any]:
    """Execute a registered journey tool with deterministic Python code."""
    valid, err = validate_journey_tool_args(tool_name, args)
    if not valid:
        return {"status": "error", "error": err, "tool_name": tool_name}

    try:
        if tool_name == "parse_trip_requirements":
            req = parse_requirements_from_text(args["user_text"])
            return {"status": "success", "requirements": req.model_dump(), "tool_name": tool_name}

        elif tool_name == "resolve_location":
            loc = _location_service.resolve_location(args["query"], context_city=args.get("context_city"))
            return {"status": "success", "resolved_location": loc.model_dump(), "tool_name": tool_name}

        elif tool_name == "find_nearby_stations":
            stations = _location_service.find_nearby_stations(args["city_or_location"])
            return {
                "status": "success",
                "stations": [s.model_dump() for s in stations],
                "total_stations": len(stations),
                "tool_name": tool_name,
            }

        elif tool_name == "estimate_last_mile":
            last_mile = _location_service.estimate_last_mile(
                station_code=args["station_code"],
                destination_venue=args["destination_venue"],
            )
            return {"status": "success", "last_mile": last_mile.model_dump(), "tool_name": tool_name}

        elif tool_name == "search_trains":
            origins = [s.strip() for s in args["origin_stations"].split(",") if s.strip()]
            dests = [s.strip() for s in args["destination_stations"].split(",") if s.strip()]
            trains = _train_service.search_trains(
                origin_stations=origins,
                destination_stations=dests,
                journey_date=args.get("journey_date"),
                preferred_class=args.get("preferred_class"),
            )
            return {
                "status": "success",
                "trains": [t.model_dump() for t in trains],
                "total_trains": len(trains),
                "tool_name": tool_name,
            }

        elif tool_name == "get_train_details":
            t = _train_service.get_train_by_number_or_name(args["train_query"])
            if t:
                return {"status": "success", "train": t.model_dump(), "tool_name": tool_name}
            return {
                "status": "not_found",
                "error": f"No train found matching query '{args['train_query']}'",
                "tool_name": tool_name,
            }

        elif tool_name == "evaluate_journey_feasibility":
            train = _train_service.get_train_by_number_or_name(args["train_number"])
            if not train:
                return {"status": "error", "error": f"Train {args['train_number']} not found", "tool_name": tool_name}
            
            req = TripRequirements(
                origin=train.origin_station_name,
                destination_venue=args["destination_venue"],
                meeting_date=args["meeting_date"],
                meeting_time=args["meeting_time"],
                required_arrival_buffer_minutes=int(args.get("required_buffer_minutes", 45)),
            )
            last_mile = _location_service.estimate_last_mile(
                station_code=train.destination_station_code,
                destination_venue=args["destination_venue"],
            )
            ev = _feasibility_evaluator.evaluate_candidate(train, req, last_mile)
            return {"status": "success", "evaluation": ev.model_dump(), "tool_name": tool_name}

        elif tool_name == "plan_goal_based_journey":
            # Extract requirements or override with structured args if provided
            req = parse_requirements_from_text(args["passenger_prompt"])
            if args.get("origin"):
                req.origin = args["origin"]
            if args.get("destination_venue"):
                req.destination_venue = args["destination_venue"]
            if args.get("meeting_date"):
                req.meeting_date = args["meeting_date"]
            if args.get("meeting_time"):
                req.meeting_time = args["meeting_time"]
            if args.get("preferred_class"):
                req.preferred_class = args["preferred_class"]
            if args.get("preferred_train"):
                req.preferred_train_name_or_number = args["preferred_train"]
            if args.get("buffer_minutes"):
                req.required_arrival_buffer_minutes = int(args["buffer_minutes"])

            res = _planner.plan_journey(req)
            return {"status": "success", "journey_plan": res.model_dump(), "tool_name": tool_name}

        return {"status": "error", "error": f"Unhandled tool: {tool_name}", "tool_name": tool_name}

    except Exception as e:
        logger.error(f"Error executing journey tool {tool_name}: {e}", exc_info=True)
        return {"status": "error", "error": f"{type(e).__name__}: {str(e)}", "tool_name": tool_name}
