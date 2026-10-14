"""
API router for goal-based journey planning ("reach my meeting on time").

Plans come from the container's JourneyProvider (one journey data path) and always carry `provenance`. Every
route needs the signed `X-Session-Token` issued by `POST /api/planner/sessions`; plan ids are server-issued,
stored in the PlanStore (Redis when configured) and bound to that session, so `/refine` and `/options` treat a
foreign plan id exactly like an unknown one.
"""

import logging

from fastapi import APIRouter, Path, Request
from pydantic import ValidationError

from app.api.deps import enforce_message_limit, offload
from app.container import Container
from app.harness.errors import PlannerError, safe_validation_errors
from app.journey.models import PLAN_ID_PATTERN, GoalPlanRequest, JourneyPlanResponse, RefineRequest, TripRequirements
from app.journey.plan_store import load_owned, new_plan_id
from app.security.tokens import TOKEN_HEADER, InvalidSessionToken

log = logging.getLogger("railsaathi.journey")
router = APIRouter(prefix="/api/journey", tags=["Goal Journey Planner"])

FREE_TEXT_FIELDS = ("prompt", "origin", "destination_venue", "destination_station", "preferred_train_name_or_number")


def _c(request: Request) -> Container:
    return request.app.state.container


def _session_owner(request: Request) -> str:
    """The session id the caller's signed token was issued for (plans are bound to it)."""
    try:
        return _c(request).signer.verify(request.headers.get(TOKEN_HEADER))
    except InvalidSessionToken as exc:
        raise PlannerError("invalid_session_token", "A valid session token is required.") from exc


def _enforce_limits(request: Request, body: GoalPlanRequest | RefineRequest) -> None:
    for name in FREE_TEXT_FIELDS:
        value = getattr(body, name, None)
        if isinstance(value, str):
            enforce_message_limit(request, value, name)


def _plan_and_store(c: Container, req: TripRequirements, owner: str, plan_id: str | None) -> JourneyPlanResponse:
    planner = c.goal_planner
    response = planner.plan(req, planner.new_trace_id())
    if response.status == "clarification_required":
        return response
    response.plan_id = plan_id or new_plan_id()
    c.plan_store.save(response.plan_id, owner, {"requirements": req.model_dump(mode="json"),
                                                "response": response.model_dump(mode="json")})
    return response


def _plan(c: Container, body: GoalPlanRequest, owner: str) -> JourneyPlanResponse:
    planner = c.goal_planner
    try:
        req, missing = planner.requirements_from_request(body)
    except ValidationError as exc:  # a parsed prompt value failed validation
        raise PlannerError("validation_failed", "The request is invalid.",
                           {"errors": safe_validation_errors(exc)}) from exc
    if req is None:
        return planner.clarification(missing, planner.new_trace_id())
    return _plan_and_store(c, req, owner, None)


def _refine(c: Container, body: RefineRequest, owner: str) -> JourneyPlanResponse:
    stored = load_owned(c.plan_store, body.plan_id, owner)
    if stored is None:
        raise PlannerError("plan_not_found", "This plan does not exist or has expired. Please plan again.")
    changes = {name: getattr(body, name) for name in body.model_fields_set if name != "plan_id"}
    try:
        req = TripRequirements.model_validate({**stored["requirements"], **changes})
    except ValidationError as exc:
        raise PlannerError("validation_failed", "The request is invalid.",
                           {"errors": safe_validation_errors(exc)}) from exc
    if "required_arrival_buffer_minutes" in changes:
        req.assumptions = [a for a in req.assumptions if "buffer" not in a.lower()]
    return _plan_and_store(c, req, owner, body.plan_id)


def _options(c: Container, plan_id: str, owner: str) -> dict:
    stored = load_owned(c.plan_store, plan_id, owner)
    if stored is None:
        raise PlannerError("plan_not_found", "This plan does not exist or has expired. Please plan again.")
    return stored["response"]


@router.post("/plan", response_model=JourneyPlanResponse)
async def plan_journey(request: Request, payload: GoalPlanRequest) -> JourneyPlanResponse:
    """Plan trains that reach a meeting on time from a prompt and/or structured fields. Missing details are asked
    for (`clarification_required`), never defaulted."""
    _enforce_limits(request, payload)
    owner = _session_owner(request)
    return await offload(_plan, _c(request), payload, owner)


@router.post("/refine", response_model=JourneyPlanResponse)
async def refine_journey(request: Request, payload: RefineRequest) -> JourneyPlanResponse:
    """Change the meeting time/date, buffer, class, preferred train or budget of a plan you own and re-plan."""
    _enforce_limits(request, payload)
    owner = _session_owner(request)
    return await offload(_refine, _c(request), payload, owner)


@router.get("/options/{plan_id}", response_model=JourneyPlanResponse)
async def get_journey_option(request: Request, plan_id: str = Path(pattern=PLAN_ID_PATTERN)) -> dict:
    owner = _session_owner(request)
    return await offload(_options, _c(request), plan_id, owner)
