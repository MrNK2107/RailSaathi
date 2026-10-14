"""
RailSaathi AI — journey planning tool for the guidance agent.

One tool, `plan_goal_based_journey`, backed by the same `GoalPlanner` (and therefore the same JourneyProvider,
cache, quota and provenance) as `/api/journey/plan`. There is no separate timetable: the agent can only report
trains the provider returned.
"""

import logging
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from app.harness.errors import PlannerError
from app.journey.models import GoalPlanRequest

if TYPE_CHECKING:
    from app.journey.planner import GoalPlanner

logger = logging.getLogger("railsaathi.tools.journey")

JOURNEY_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "plan_goal_based_journey": {
        "name": "plan_goal_based_journey",
        "description": (
            "Plan trains that reach a meeting, exam or appointment on time. Uses the configured railway data "
            "provider, computes the latest acceptable station arrival from the meeting time, buffer and "
            "last-mile estimate, and returns ranked options with provenance and official booking links. If "
            "details are missing it returns the question to ask the passenger."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "passenger_prompt": {"type": "string", "description": "The passenger's journey request."},
                "origin": {"type": "string", "description": "Optional starting city or station."},
                "destination_venue": {"type": "string", "description": "Optional destination venue."},
                "destination_station": {"type": "string", "description": "Optional arrival station or city."},
                "meeting_date": {"type": "string", "description": "Optional meeting date (YYYY-MM-DD)."},
                "meeting_time": {"type": "string", "description": "Optional meeting time (HH:MM, 24-hour)."},
                "preferred_class": {"type": "string", "description": "Optional class code (SL, 3A, 2A, CC, EC, 2S)."},
                "preferred_train": {"type": "string", "description": "Optional train number or name."},
                "buffer_minutes": {"type": "integer", "description": "Optional buffer at the venue in minutes."},
            },
            "required": ["passenger_prompt"],
        },
    },
}


def validate_journey_tool_args(tool_name: str, args: dict) -> tuple[bool, str | None]:
    if tool_name not in JOURNEY_TOOL_SCHEMAS:
        return False, f"Unknown journey tool: {tool_name}"
    for name in JOURNEY_TOOL_SCHEMAS[tool_name]["parameters"].get("required", []):
        if args.get(name) is None:
            return False, f"Missing required parameter '{name}' for tool '{tool_name}'"
    return True, None


def _request(args: dict) -> GoalPlanRequest:
    fields = {
        "prompt": args.get("passenger_prompt"),
        "origin": args.get("origin"),
        "destination_venue": args.get("destination_venue"),
        "destination_station": args.get("destination_station"),
        "meeting_date": args.get("meeting_date"),
        "meeting_time": args.get("meeting_time"),
        "preferred_class": args.get("preferred_class") or None,
        "preferred_train_name_or_number": args.get("preferred_train"),
        "required_arrival_buffer_minutes": args.get("buffer_minutes"),
    }
    return GoalPlanRequest.model_validate({k: v for k, v in fields.items() if v not in (None, "")})


def execute_journey_tool(tool_name: str, args: dict, goal_planner: "GoalPlanner | None" = None) -> dict[str, Any]:
    valid, err = validate_journey_tool_args(tool_name, args)
    if not valid:
        return {"status": "error", "error": err, "error_code": "invalid_arguments", "tool_name": tool_name}
    if goal_planner is None:
        return {"status": "error", "error": "Journey planning is not available.", "error_code": "unavailable",
                "tool_name": tool_name}
    try:
        request = _request(args)
        req, missing = goal_planner.requirements_from_request(request)
        trace_id = goal_planner.new_trace_id()
        plan = goal_planner.clarification(missing, trace_id) if req is None else goal_planner.plan(req, trace_id)
        return {"status": "success", "journey_plan": plan.model_dump(mode="json"), "tool_name": tool_name}
    except ValidationError:
        return {"status": "error", "error": "Some journey details are invalid (check the date and time format).",
                "error_code": "invalid_arguments", "tool_name": tool_name}
    except PlannerError as exc:
        return {"status": "error", "error": exc.message, "error_code": "invalid_arguments", "tool_name": tool_name}
    except Exception as exc:  # noqa: BLE001 - tool failures are reported, never raised into the agent loop
        logger.error("Journey tool %s failed: %s", tool_name, type(exc).__name__, exc_info=True)
        return {"status": "error", "error": "The tool failed to run.", "tool_name": tool_name}
