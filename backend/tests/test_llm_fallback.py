"""Gemini -> local model (Ollama) fallback: cooldown policy, container wiring, provenance and health. Fakes and
`httpx.MockTransport` only; no network, no Ollama."""

import concurrent.futures
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agent.controller import AgentController
from app.clock import FixedClock
from app.config import Settings
from app.container import build_chat_llm, build_container, build_llm
from app.intent.extractor import IntentExtractor
from app.intent.llm import ExtractionContext
from app.intent.ollama import OllamaIntentProvider
from app.intent.rules import RuleBasedExtractor
from app.intent.schema import IntentUpdate
from app.knowledge.ingest import ingest
from app.llm import ollama as ollama_module
from app.llm.base import ChatMessage, Deadline, LLMError, LLMErrorKind, LLMTurn
from app.llm.fallback import (COOLDOWN_SECONDS, FALLBACK_ERRORS, MIN_FALLBACK_SECONDS, FallbackChatLLM,
                              FallbackIntentLLM)
from app.llm.ollama import OllamaCaller, OllamaChatLLM
from app.main import create_app
from app.stations.resolver import StationResolver
from app.providers.demo import DemoJourneyProvider
from tests.conftest import FIXED_NOW

USER = [ChatMessage(role="user", text="What is RAC?")]
OLLAMA_SETTINGS = Settings(_env_file=None, llm_provider="ollama")


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeChat:
    def __init__(self, name: str, *outcomes) -> None:
        self.name = name
        self.outcomes = list(outcomes)
        self.calls = 0

    def generate(self, messages, tools, deadline):
        self.calls += 1
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, LLMError):
            raise outcome
        return LLMTurn(text=outcome, model=self.name)


def test_constants():
    assert COOLDOWN_SECONDS == 60 and MIN_FALLBACK_SECONDS == 8.0
    assert FALLBACK_ERRORS == {LLMErrorKind.NOT_CONFIGURED, LLMErrorKind.AUTH, LLMErrorKind.ACCESS_DENIED,
                               LLMErrorKind.THROTTLED}


def test_primary_used_when_healthy():
    primary, secondary = FakeChat("gemini", "from gemini"), FakeChat("gemma4", "from gemma")
    llm = FallbackChatLLM(primary, secondary)
    assert llm.generate(USER, (), Deadline(20)).text == "from gemini"
    assert secondary.calls == 0
    assert llm.name == "gemini"
    assert llm.status() == {"active": "gemini", "primary_cooling_until": None}


def test_auth_error_falls_back_and_cools_down():
    clock = Clock()
    primary = FakeChat("gemini", LLMError(LLMErrorKind.AUTH), "from gemini")
    secondary = FakeChat("gemma4", "from gemma")
    llm = FallbackChatLLM(primary, secondary, clock=clock)
    turn = llm.generate(USER, (), Deadline(20))
    assert turn.text == "from gemma" and turn.model == "gemma4"
    assert llm.status() == {"active": "gemma4", "primary_cooling_until": clock.now + COOLDOWN_SECONDS}

    clock.now += 30  # still cooling: straight to the secondary
    assert llm.generate(USER, (), Deadline(20)).text == "from gemma"
    assert primary.calls == 1 and secondary.calls == 2

    clock.now += 31  # 61 s after the failure: the primary is tried again
    assert llm.generate(USER, (), Deadline(20)).text == "from gemini"
    assert primary.calls == 2
    assert llm.status() == {"active": "gemini", "primary_cooling_until": None}


def test_timeout_does_not_cool_down():
    primary = FakeChat("gemini", LLMError(LLMErrorKind.TIMEOUT), "from gemini")
    secondary = FakeChat("gemma4", "from gemma")
    llm = FallbackChatLLM(primary, secondary)
    with pytest.raises(LLMError) as err:
        llm.generate(USER, (), Deadline(20))
    assert err.value.kind is LLMErrorKind.TIMEOUT
    assert secondary.calls == 0
    assert llm.status()["primary_cooling_until"] is None
    assert llm.generate(USER, (), Deadline(20)).text == "from gemini"


def test_no_fallback_when_deadline_short():
    clock = Clock()
    primary = FakeChat("gemini", LLMError(LLMErrorKind.THROTTLED))
    secondary = FakeChat("gemma4", "from gemma")
    llm = FallbackChatLLM(primary, secondary)
    deadline = Deadline(3, clock=clock)
    assert deadline.remaining() == 3
    with pytest.raises(LLMError) as err:
        llm.generate(USER, (), deadline)
    assert err.value.kind is LLMErrorKind.THROTTLED
    assert secondary.calls == 0


# --- intent fallback ------------------------------------------------------------------------------------------

class FakeIntent:
    def __init__(self, name: str, outcome) -> None:
        self.name = name
        self.outcome = outcome
        self.calls = 0

    def extract_intent(self, message, context):
        self.calls += 1
        if isinstance(self.outcome, LLMError):
            raise self.outcome
        return self.outcome


UPDATE = IntentUpdate(intent="provide_details", origin_text="Chennai", destination_text="Madurai")


def _ctx(seconds: float = 20, clock=time.monotonic) -> ExtractionContext:
    return ExtractionContext(language="en", today_iso="2026-10-18", pending_field=None, captured_fields=[],
                             deadline=Deadline(seconds, clock=clock))


def test_intent_falls_back_and_names_the_answering_provider():
    primary, secondary = FakeIntent("gemini", LLMError(LLMErrorKind.AUTH)), FakeIntent("gemma4", UPDATE)
    llm = FallbackIntentLLM(primary, secondary)
    assert llm.name == "gemini"
    assert llm.extract_intent("Chennai to Madurai", _ctx()) == UPDATE
    assert llm.name == "gemma4"
    assert llm.status()["active"] == "gemma4"


def test_intent_no_fallback_when_deadline_short():
    clock = Clock()
    primary, secondary = FakeIntent("gemini", LLMError(LLMErrorKind.THROTTLED)), FakeIntent("gemma4", UPDATE)
    with pytest.raises(LLMError):
        FallbackIntentLLM(primary, secondary).extract_intent("x", _ctx(3, clock))
    assert secondary.calls == 0


def test_extractor_source_names_the_answering_provider_in_worker_threads():
    """The answering provider is held per call context, so the extractor (run in executor threads) reports the
    model that answered its own request, and a concurrent request on another thread is unaffected."""
    resolver = StationResolver(DemoJourneyProvider())
    gate = threading.Barrier(2)

    class Gated(FakeIntent):
        def extract_intent(self, message, context):
            gate.wait(timeout=5)  # both requests are in flight together
            return super().extract_intent(message, context)

    healthy = Gated("gemini", UPDATE)

    class AuthOnFail:
        """Primary that rejects its credentials only for the message 'fail'."""
        name = "gemini"

        def extract_intent(self, message, context):
            if message == "fail":
                gate.wait(timeout=5)
                raise LLMError(LLMErrorKind.AUTH)
            return healthy.extract_intent(message, context)

    llm = FallbackIntentLLM(AuthOnFail(), FakeIntent("gemma4", UPDATE))
    extractor = IntentExtractor(RuleBasedExtractor(resolver), llm)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        ok = pool.submit(extractor.extract, "ok", _ctx())
        failed = pool.submit(extractor.extract, "fail", _ctx())
        assert failed.result(timeout=10).source == "gemma4"
        assert ok.result(timeout=10).source == "gemini"
    assert llm.name == "gemini"  # this thread's context never saw a call


# --- container wiring -----------------------------------------------------------------------------------------

def test_build_chat_llm_ollama_only():
    llm, reason = build_chat_llm(OLLAMA_SETTINGS)
    assert isinstance(llm, OllamaChatLLM) and reason is None
    llm, reason = build_llm(OLLAMA_SETTINGS)
    assert isinstance(llm, OllamaIntentProvider) and reason is None


def test_build_chat_llm_gemini_unconfigured_uses_ollama():
    settings = Settings(_env_file=None, llm_provider="gemini", llm_fallback="ollama", gcp_project="",
                        gemini_api_key="")
    llm, reason = build_chat_llm(settings)
    assert isinstance(llm, OllamaChatLLM) and reason == "gemini_not_configured_using_ollama"
    llm, reason = build_llm(settings)
    assert isinstance(llm, OllamaIntentProvider) and reason == "gemini_not_configured_using_ollama"


def test_build_wraps_gemini_with_ollama_fallback():
    settings = Settings(_env_file=None, llm_provider="gemini", llm_fallback="ollama", gcp_project="p")
    chat, reason = build_chat_llm(settings)
    assert isinstance(chat, FallbackChatLLM) and reason is None and chat.name == "gemini"
    intent, reason = build_llm(settings)
    assert isinstance(intent, FallbackIntentLLM) and reason is None


def test_production_never_builds_ollama():
    prod = dict(_env_file=None, app_env="production", session_signing_key="k" * 32)
    assert build_chat_llm(Settings(**prod, llm_provider="ollama")) == (None, "llm_disabled")
    assert build_llm(Settings(**prod, llm_provider="ollama")) == (None, "llm_disabled")
    chat, _ = build_chat_llm(Settings(**prod, llm_provider="gemini", llm_fallback="ollama", gcp_project="p"))
    assert chat.name == "gemini" and not isinstance(chat, FallbackChatLLM)
    intent, _ = build_llm(Settings(**prod, llm_provider="gemini", llm_fallback="ollama", gcp_project="p"))
    assert intent.name == "gemini" and not isinstance(intent, FallbackIntentLLM)


# --- provenance and health ------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("kb") / "knowledge.db"
    ingest(path)
    return str(path)


def test_provenance_names_local_model(db):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "RAC means a shared berth."}})

    llm = OllamaChatLLM(OLLAMA_SETTINGS, transport=httpx.MockTransport(handler))
    res = AgentController(llm, db, now=lambda: FIXED_NOW).process_message("What is RAC?")
    assert res.status == "answered"
    assert res.provenance["source"].startswith("gemma4 (local) over the RailSaathi knowledge base (curated ")


def test_provenance_names_the_model_that_answered_after_fallback(db):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "RAC means a shared berth."}})

    llm = FallbackChatLLM(FakeChat("gemini", LLMError(LLMErrorKind.AUTH)),
                          OllamaChatLLM(OLLAMA_SETTINGS, transport=httpx.MockTransport(handler)))
    res = AgentController(llm, db, now=lambda: FIXED_NOW).process_message("What is RAC?")
    assert res.provenance["source"].startswith("gemma4 (local) over")


def test_gemini_turns_are_labelled_gemini():
    from app.llm.gemini import to_turn

    assert to_turn(object()).model == "gemini"


def test_health_reports_active_model():
    settings = Settings(_env_file=None)
    chat = FallbackChatLLM(FakeChat("gemini", "x"), FakeChat("gemma4", "y"))
    container = build_container(settings, clock=FixedClock(FIXED_NOW), use_configured_llm=False, chat_llm=chat)
    body = TestClient(create_app(settings, container)).get("/api/health").json()
    assert body["ai"]["chat"]["active"] == "gemini"
    assert body["ai"]["chat"]["primary_cooling_until"] is None
    assert body["llm"]["chat"]["active"] == "gemini"


# --- Ollama lock wait counts against the call's deadline -------------------------------------------------------

def test_ollama_lock_wait_counts_against_deadline():
    """A request queued behind another one gives up when its turn's budget is spent, instead of running late."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={"message": {"content": "ok"}})

    caller = OllamaCaller(OLLAMA_SETTINGS, httpx.MockTransport(handler))
    assert ollama_module._LOCK.acquire(timeout=1)  # another request holds the local model
    try:
        started = time.monotonic()
        with pytest.raises(LLMError) as err:
            caller.chat({"messages": []}, Deadline(0.5))
        assert err.value.kind is LLMErrorKind.TIMEOUT
        assert time.monotonic() - started < 1.5
        time.sleep(0.3)  # the queued attempt's budget is gone before the lock frees up
    finally:
        ollama_module._LOCK.release()
    time.sleep(0.3)
    assert calls == []  # the abandoned attempt never reached the model
    assert caller.chat({"messages": []}, Deadline(5))["message"]["content"] == "ok"
