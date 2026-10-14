"""
API Router for Indian Railways Ticketing Guidance & Verified Sources
Powered by local knowledge database and deterministic safety checks.
"""

import logging
import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import enforce_message_limit, offload
from app.config import DB_PATH
from app.knowledge.database import get_all_sources, get_connection
from app.agent.controller import AgentController

log = logging.getLogger("railsaathi.ticketing")
router = APIRouter(prefix="/api", tags=["Ticketing Guidance"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)
    conversation_id: Optional[str] = None


def _read_sources() -> list:
    with get_connection(DB_PATH) as conn:
        return get_all_sources(conn)


@router.get("/sources")
async def list_sources():
    """Return all verified Indian Railways knowledge sources."""
    try:
        sources = await offload(_read_sources)
        return {"sources": sources, "count": len(sources)}
    except Exception:
        log.exception("Could not list ticketing sources")
        return {"sources": [], "error": "Knowledge sources are temporarily unavailable."}


@router.post("/chat")
async def ticketing_chat(request: Request, payload: ChatRequest):
    """Answer IRCTC rules, RAC/WL queries, Tatkal timings, and refunds.

    Uses Gemini when configured, otherwise the rule-based KeywordChatLLM. LLM failures degrade to a
    `service_unavailable` answer, never a 500."""
    enforce_message_limit(request, payload.message)
    container = request.app.state.container
    settings = container.settings
    controller = AgentController(container.agent_llm, str(DB_PATH), max_rounds=settings.max_agent_rounds,
                                 max_tool_calls=settings.max_tool_calls,
                                 deadline_seconds=settings.llm_overall_deadline_seconds)
    try:
        res = await offload(controller.process_message, payload.message)
        return {
            "conversation_id": payload.conversation_id or str(uuid.uuid4()),
            "answer": res.answer,
            "status": res.status,
            "sources": res.sources,
            "trace_id": res.trace_id,
        }
    except Exception as e:
        log.exception("Ticketing guidance failed")
        raise HTTPException(status_code=500, detail="Ticketing guidance failed") from e
