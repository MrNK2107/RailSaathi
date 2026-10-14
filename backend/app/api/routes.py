"""Planner REST endpoints. Thin layer: all logic lives in PlannerService."""

from uuid import UUID

from fastapi import APIRouter, Body, Depends, Request

from app.api.schemas import (
    ConfirmRequest,
    CreateSessionRequest,
    ErrorResponse,
    ExtractionInfo,
    HealthResponse,
    JourneyPatch,
    MessageRequest,
    PlannerResponse,
    ReassessRequest,
    SelectRequest,
    data_notice,
)
from app.api.deps import enforce_message_limit, verify_session_token
from app.container import Container
from app.domain.enums import (
    BudgetPriority,
    PassengerNeed,
    TransferPreference,
    TravelClass,
    WorkflowStatus as S,
)
from app.harness.errors import PlannerError
from app.harness.planner import PlannerResult

ERRORS = {code: {"model": ErrorResponse} for code in (401, 404, 409, 410, 422, 429)}
router = APIRouter(prefix="/api")


def _c(request: Request) -> Container:
    return request.app.state.container


def _respond(result: PlannerResult) -> PlannerResponse:
    s = result.state
    return PlannerResponse(
        session_id=s.session_id,
        assistant_message=result.assistant_message,
        status=s.status,
        state=s,
        missing_fields=s.missing_fields,
        validation_errors=s.validation_errors,
        recommendations_ready=bool(s.recommendations and s.recommendations.recommendations),
        confirmation_required=s.status == S.AWAITING_CONFIRMATION,
        data_mode=s.data_mode,
        data_notice=data_notice(s.data_mode),
        extraction=ExtractionInfo(source=result.extraction_source, fallback_reason=result.fallback_reason)
        if result.extraction_source else None,
        handoff=s.confirmation.handoff if s.confirmation and s.status == S.CONFIRMED else None,
    )


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health(request: Request) -> HealthResponse:
    c = _c(request)
    return HealthResponse(
        status="ok", api_version=c.settings.api_version, data_mode=c.provider.data_mode,
        data_provider=c.data_provider_status,
        ai={"llm_provider_setting": c.settings.llm_provider, "bedrock_configured": c.settings.bedrock_configured,
            **c.extractor.llm_status, "fallback": "rule_based_extractor"},
    )


@router.get("/planner/reference", tags=["planner"])
def reference(request: Request) -> dict:
    """Lookup values for the frontend edit form (places, classes, needs, demo events)."""
    c = _c(request)
    return {
        "places": [p.model_dump() for p in c.resolver.all_places()],
        "classes": [t.value for t in TravelClass],
        "passenger_needs": [n.value for n in PassengerNeed],
        "budget_priorities": [b.value for b in BudgetPriority],
        "transfer_preferences": [t.value for t in TransferPreference],
        "disruption_events": [e.model_dump(mode="json") for e in c.disruptions.list_events()],
        "data_mode": c.provider.data_mode.value,
        "data_notice": data_notice(c.provider.data_mode),
    }


@router.post("/planner/sessions", response_model=PlannerResponse, status_code=201, tags=["planner"])
def create_session(request: Request, body: CreateSessionRequest = Body(default_factory=CreateSessionRequest)):
    c = _c(request)
    response = _respond(c.planner.create_session(body.language))
    response.session_token = c.signer.issue(response.session_id)
    return response


@router.get("/planner/sessions/{session_id}", response_model=PlannerResponse, responses=ERRORS, dependencies=[Depends(verify_session_token)], tags=["planner"])
def get_session(request: Request, session_id: UUID):
    state = _c(request).planner.get(str(session_id))
    return _respond(PlannerResult(state, ""))


@router.post("/planner/sessions/{session_id}/messages", response_model=PlannerResponse, responses=ERRORS, dependencies=[Depends(verify_session_token)], tags=["planner"])
def post_message(request: Request, session_id: UUID, body: MessageRequest):
    enforce_message_limit(request, body.message)
    return _respond(_c(request).planner.handle_message(str(session_id), body.message, body.language))


@router.patch("/planner/sessions/{session_id}/journey", response_model=PlannerResponse, responses=ERRORS, dependencies=[Depends(verify_session_token)], tags=["planner"])
def patch_journey(request: Request, session_id: UUID, body: JourneyPatch):
    provided = body.model_dump(exclude_unset=True)
    places = {k: provided.pop(k) for k in ("origin", "destination") if k in provided}
    clear_places = {k: None for k, v in places.items() if v is None}
    resolve = {k: v for k, v in places.items() if v is not None}
    return _respond(_c(request).planner.patch_journey(str(session_id), {**provided, **clear_places}, resolve))


@router.post("/planner/sessions/{session_id}/recommendations", response_model=PlannerResponse, responses=ERRORS, dependencies=[Depends(verify_session_token)], tags=["planner"])
def recommendations(request: Request, session_id: UUID):
    return _respond(_c(request).planner.recommend(str(session_id)))


@router.post("/planner/sessions/{session_id}/select", response_model=PlannerResponse, responses=ERRORS, dependencies=[Depends(verify_session_token)], tags=["planner"])
def select(request: Request, session_id: UUID, body: SelectRequest):
    return _respond(_c(request).planner.select(str(session_id), body.option_id))


@router.post("/planner/sessions/{session_id}/confirm", response_model=PlannerResponse, responses=ERRORS, dependencies=[Depends(verify_session_token)], tags=["planner"])
def confirm(request: Request, session_id: UUID, body: ConfirmRequest = Body(default_factory=ConfirmRequest)):
    return _respond(_c(request).planner.confirm(str(session_id), body.option_id))


@router.post("/planner/sessions/{session_id}/reassess", response_model=PlannerResponse, responses=ERRORS, dependencies=[Depends(verify_session_token)], tags=["planner"])
def reassess(request: Request, session_id: UUID, body: ReassessRequest = Body(default_factory=ReassessRequest)):
    return _respond(_c(request).planner.reassess(str(session_id), body.event_id))


@router.post("/planner/sessions/{session_id}/cancel", response_model=PlannerResponse, responses=ERRORS, dependencies=[Depends(verify_session_token)], tags=["planner"])
def cancel(request: Request, session_id: UUID):
    return _respond(_c(request).planner.cancel(str(session_id)))


@router.get("/planner/sessions/{session_id}/handoff", responses=ERRORS, dependencies=[Depends(verify_session_token)], tags=["integration"])
def handoff(request: Request, session_id: UUID) -> dict:
    state = _c(request).planner.get(str(session_id))
    if state.status != S.CONFIRMED or not state.confirmation:
        raise PlannerError("not_ready", "No confirmed plan is available for handoff.")
    return state.confirmation.handoff


@router.get("/planner/sessions/{session_id}/audit", responses=ERRORS, dependencies=[Depends(verify_session_token)], tags=["planner"])
def audit(request: Request, session_id: UUID) -> list[dict]:
    c = _c(request)
    c.planner.get(str(session_id))
    return [e.model_dump(mode="json") for e in c.audit.list(str(session_id))]


@router.get("/planner/disruption-events", tags=["planner"])
def disruption_events(request: Request) -> list[dict]:
    return [e.model_dump(mode="json") for e in _c(request).disruptions.list_events()]
