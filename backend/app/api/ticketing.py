"""
API Router for Indian Railways Ticketing Guidance & Verified Sources
Powered by local knowledge database and deterministic safety checks.
"""

import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import enforce_message_limit
from app.config import DB_PATH
from app.knowledge.database import get_all_sources, get_connection
from app.agent.mock_llm import DevMockGeminiClient
from app.agent.controller import AgentController

router = APIRouter(prefix="/api", tags=["Ticketing Guidance"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)
    conversation_id: Optional[str] = None


@router.get("/sources")
def list_sources():
    """Return all verified Indian Railways knowledge sources."""
    try:
        with get_connection(DB_PATH) as conn:
            sources = get_all_sources(conn)
            return {"sources": sources, "count": len(sources)}
    except Exception as e:
        return {"sources": [], "error": str(e)}


@router.post("/chat")
def ticketing_chat(request: Request, payload: ChatRequest):
    """Answer IRCTC rules, RAC/WL queries, Tatkal timings, and refunds."""
    enforce_message_limit(request, payload.message)
    llm = DevMockGeminiClient()
    controller = AgentController(llm, str(DB_PATH))
    try:
        res = controller.process_message(payload.message)
        return {
            "conversation_id": payload.conversation_id or str(uuid.uuid4()),
            "answer": res.answer,
            "status": res.status,
            "sources": res.sources,
            "trace_id": res.trace_id,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ticketing guidance failed") from e
