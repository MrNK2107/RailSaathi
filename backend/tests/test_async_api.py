"""Async handlers, the ticketing agent on the ChatLLM adapter, and the planner turn deadline end to end."""

import asyncio
import time
from types import SimpleNamespace

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.clock import FixedClock
from app.config import Settings
from app.container import build_container
from app.intent.gemini import GeminiIntentProvider
from app.llm.base import LLMError, LLMErrorKind, ToolCall
from app.llm.mock import MockChatLLM
from app.main import create_app
from tests.conftest import FIXED_NOW


def make_client(chat_llm=None, llm=None, **overrides) -> TestClient:
    settings = Settings(_env_file=None, **overrides)
    container = build_container(settings, clock=FixedClock(FIXED_NOW), use_configured_llm=False,
                                chat_llm=chat_llm, llm=llm)
    return TestClient(create_app(settings, container))


def test_every_api_handler_is_async():
    app = create_app(Settings(_env_file=None))
    sync = [r.path for r in app.routes if isinstance(r, APIRoute) and not asyncio.iscoroutinefunction(r.endpoint)]
    assert sync == []


def test_chat_uses_the_injected_chat_llm():
    llm = MockChatLLM([[ToolCall(name="search_ticketing_guidance", args={"query": "RAC"})], "RAC answer."])
    r = make_client(chat_llm=llm).post("/api/chat", json={"message": "What is RAC?"})
    assert r.status_code == 200
    assert r.json()["answer"] == "RAC answer."
    assert r.json()["status"] == "answered"


def test_chat_degrades_when_the_llm_fails():
    llm = MockChatLLM([LLMError(LLMErrorKind.THROTTLED)])
    r = make_client(chat_llm=llm).post("/api/chat", json={"message": "What is RAC?"})
    assert r.status_code == 200
    assert r.json()["status"] == "unavailable"


def test_chat_without_llm_uses_rule_based_agent_and_health_says_so():
    c = make_client()
    r = c.post("/api/chat", json={"message": "What does RAC mean?"})
    assert r.status_code == 200 and r.json()["status"] == "answered"
    chat = c.get("/api/health").json()["ai"]["chat"]
    assert chat["provider"] == "rules" and chat["llm"] is False


class _HangingModels:
    async def generate_content(self, **_):
        await asyncio.sleep(5)


def _slow_gemini_intent(deadline_seconds: float) -> GeminiIntentProvider:
    settings = Settings(_env_file=None, llm_provider="gemini", gcp_project="p",
                        llm_overall_deadline_seconds=deadline_seconds)
    return GeminiIntentProvider(settings, client=SimpleNamespace(aio=SimpleNamespace(models=_HangingModels())))


def test_planner_turn_carries_the_configured_deadline():
    # The minimum lock TTL validation forces deadline + 10 s <= lock TTL; 0.3 s keeps the test fast.
    c = make_client(llm=_slow_gemini_intent(0.3), llm_overall_deadline_seconds=0.3)
    created = c.post("/api/planner/sessions", json={"language": "en"}).json()
    c.headers["X-Session-Token"] = created["session_token"]
    started = time.monotonic()
    r = c.post(f"/api/planner/sessions/{created['session_id']}/messages",
               json={"message": "from Bengaluru to Chennai tomorrow"})
    assert time.monotonic() - started < 2.0
    assert r.status_code == 200
    assert r.json()["extraction"] == {"source": "rules", "fallback_reason": "timeout"}


def test_request_id_reaches_handlers_running_in_threads():
    r = make_client().get("/api/health", headers={"X-Request-Id": "abc-123"})
    assert r.headers["X-Request-Id"] == "abc-123"
