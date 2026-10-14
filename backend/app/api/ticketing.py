"""
API router for Indian Railways ticketing guidance and its knowledge sources.

`POST /api/chat` runs the AgentController on `container.agent_llm` (Gemini when configured, otherwise the
rule-based agent; a scripted mock only via test injection).

Sessions and history: the caller may send the signed `X-Session-Token` it was issued (by this route or by
`POST /api/planner/sessions`). Without one, a new chat session is created and its token returned in
`session_token`; an invalid token is rejected (401). History is stored per (verified session, conversation_id),
so a conversation id is only meaningful together with the token that created it; a missing or expired one simply
starts an empty conversation.

Responses always carry `provenance` (`live` = Gemini, `fallback` = rule-based agent, `unavailable` = the LLM
failed). An LLM failure is a 200 with `status: "unavailable"`, `message: "guidance unavailable"` and official
`links`, never a 500.
"""

import logging
import secrets
from contextlib import closing
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from redis.exceptions import RedisError

from app.agent.controller import AgentController, AgentResponse
from app.agent.conversation_store import CONVERSATION_ID_PATTERN, new_conversation_id
from app.api.deps import enforce_message_limit, offload
from app.container import Container
from app.harness.errors import PlannerError
from app.knowledge.database import get_all_sources, get_connection
from app.llm.base import ChatMessage
from app.security.tokens import TOKEN_HEADER, InvalidSessionToken

log = logging.getLogger("railsaathi.ticketing")
router = APIRouter(prefix="/api", tags=["Ticketing Guidance"])

STORED_STATUSES = ("answered", "execution_limit_reached")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)
    conversation_id: Optional[str] = Field(default=None, pattern=CONVERSATION_ID_PATTERN)


def _read_sources(db_path) -> list:
    with closing(get_connection(db_path)) as conn:
        return get_all_sources(conn)


@router.get("/sources")
async def list_sources(request: Request):
    """Return all knowledge sources (official pages the guidance is attributed to)."""
    try:
        sources = await offload(_read_sources, request.app.state.container.settings.knowledge_db_path)
        for source in sources:
            source.pop("content_hash", None)
        return {"sources": sources, "count": len(sources)}
    except Exception:
        log.exception("Could not list ticketing sources")
        return {"sources": [], "count": 0, "error": "Knowledge sources are temporarily unavailable."}


def _chat_session(c: Container, token: str | None) -> tuple[str, str]:
    """(session_id, token): verify the caller's token, or issue a new chat session when none was sent."""
    if token is None:
        session_id = f"chat_{secrets.token_urlsafe(18)}"
        return session_id, c.signer.issue(session_id)
    try:
        return c.signer.verify(token), token
    except InvalidSessionToken as exc:
        raise PlannerError("invalid_session_token", "A valid session token is required.") from exc


def _load_history(c: Container, session_id: str, conversation_id: str) -> list[ChatMessage]:
    try:
        return c.conversations.load(session_id, conversation_id)
    except (RedisError, OSError):
        log.warning("Conversation history unavailable; answering without it", exc_info=True)
        return []


def _save_turn(c: Container, session_id: str, conversation_id: str, message: str, res: AgentResponse) -> None:
    if res.status not in STORED_STATUSES:
        return
    try:
        c.conversations.append_turn(session_id, conversation_id, message, res.answer)
    except (RedisError, OSError):
        log.warning("Could not store the conversation turn", exc_info=True)


def _turn(c: Container, session_id: str, conversation_id: str, message: str) -> AgentResponse:
    settings = c.settings
    controller = AgentController(c.agent_llm, str(settings.knowledge_db_path), max_rounds=settings.max_agent_rounds,
                                 max_tool_calls=settings.max_tool_calls,
                                 deadline_seconds=settings.llm_overall_deadline_seconds,
                                 goal_planner=c.goal_planner, now=c.clock.now)
    history = _load_history(c, session_id, conversation_id)
    res = controller.process_message(message, history)
    _save_turn(c, session_id, conversation_id, message, res)
    return res


@router.post("/chat")
async def ticketing_chat(request: Request, payload: ChatRequest):
    """Answer ticketing questions (classes, RAC/WL, Tatkal, refunds) and goal-based journey questions, grounded in
    the knowledge base with citations."""
    enforce_message_limit(request, payload.message)
    c: Container = request.app.state.container
    session_id, token = _chat_session(c, request.headers.get(TOKEN_HEADER))
    conversation_id = payload.conversation_id or new_conversation_id()
    res = await offload(_turn, c, session_id, conversation_id, payload.message)
    body = {
        "conversation_id": conversation_id,
        "session_token": token,
        "status": res.status,
        "answer": res.answer,
        "sources": res.sources,
        "provenance": res.provenance,
        "evidence_sufficient": res.evidence_sufficient,
        "trace_id": res.trace_id,
    }
    if res.status == "unavailable":
        body["message"] = res.message
        body["links"] = res.links
    return body
