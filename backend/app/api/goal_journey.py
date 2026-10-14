"""
API Router for Goal-Based Journey Planning
Evaluates timetable schedules against meeting deadlines and last-mile cab buffer.
"""

import uuid
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.api.deps import enforce_message_limit
from app.journey.planner import JourneyPlanner, parse_requirements_from_text
from app.journey.models import TripRequirements

router = APIRouter(prefix="/api/journey", tags=["Goal Journey Planner"])

journey_planner = JourneyPlanner()
journey_plans_store: Dict[str, Any] = {}


class GoalPlanRequest(BaseModel):
    prompt: Optional[str] = None
    origin: Optional[str] = None
    destination_venue: Optional[str] = None
    destination_city: Optional[str] = None
    meeting_date: Optional[str] = None
    meeting_time: Optional[str] = None
    required_arrival_buffer_minutes: Optional[int] = 45
    preferred_class: Optional[str] = None
    preferred_train_name_or_number: Optional[str] = None
    budget_max: Optional[float] = None


@router.post("/plan")
def plan_journey(request: Request, payload: GoalPlanRequest):
    """
    Accept free-text meeting prompt or structured constraints,
    deterministically evaluate timetables, buffers, and last-mile taxis,
    and output ranked train recommendations with IRCTC booking handoffs.
    """
    enforce_message_limit(request, payload.prompt, "prompt")
    trace_id = f"plan-{uuid.uuid4().hex[:10]}"
    try:
        if payload.prompt and not payload.origin:
            req = parse_requirements_from_text(payload.prompt)
        else:
            req = TripRequirements(
                origin=payload.origin or "Bengaluru",
                destination_city=payload.destination_city or "Chennai",
                destination_venue=payload.destination_venue or "Central Hub",
                meeting_date=payload.meeting_date or "2026-10-25",
                meeting_time=payload.meeting_time or "10:00",
                required_arrival_buffer_minutes=payload.required_arrival_buffer_minutes or 45,
                preferred_class=payload.preferred_class,
                preferred_train_name_or_number=payload.preferred_train_name_or_number,
                budget_max=payload.budget_max,
            )

        res = journey_planner.plan_journey(req, trace_id=trace_id)
        plan_dict = res.model_dump()
        journey_plans_store[trace_id] = plan_dict
        return plan_dict
    except Exception as e:
        raise HTTPException(status_code=500, detail="Journey planning failed") from e


@router.post("/refine")
def refine_journey(data: Dict[str, Any]):
    """Refine existing trip requirements (e.g. buffer, class, time)."""
    base_req_data = data.get("requirements") or {}
    trace_id = data.get("trace_id") or f"refine-{uuid.uuid4().hex[:10]}"
    try:
        req = TripRequirements(**base_req_data)
        if data.get("meeting_time"):
            req.meeting_time = str(data["meeting_time"]).strip()
        if data.get("required_arrival_buffer_minutes") is not None:
            req.required_arrival_buffer_minutes = int(data["required_arrival_buffer_minutes"])
        if data.get("preferred_class") is not None:
            req.preferred_class = str(data["preferred_class"]).strip() or None
        if data.get("budget_max") is not None:
            req.budget_max = float(data["budget_max"]) if data["budget_max"] != "" else None

        res = journey_planner.plan_journey(req, trace_id=trace_id)
        plan_dict = res.model_dump()
        journey_plans_store[trace_id] = plan_dict
        return plan_dict
    except Exception as e:
        raise HTTPException(status_code=500, detail="Journey planning failed") from e


@router.get("/options/{request_id}")
def get_journey_option(request_id: str):
    plan = journey_plans_store.get(request_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan
