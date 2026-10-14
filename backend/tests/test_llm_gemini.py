"""Gemini chat adapter, Gemini intent extraction and the overall LLM deadline.

The google-genai SDK is replaced by a fake client exposing `client.aio.models.generate_content`; no network."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from google.genai import errors, types

from app.agent.controller import AgentController
from app.config import DB_PATH, Settings
from app.container import build_chat_llm, build_llm
from app.intent.extractor import IntentExtractor
from app.intent.gemini import GeminiIntentProvider
from app.intent.llm import ExtractionContext
from app.intent.rules import RuleBasedExtractor
from app.llm.base import ChatMessage, Deadline, LLMError, LLMErrorKind, ToolCall, ToolResult, ToolSpec
from app.llm.gemini import GeminiChatLLM
from app.llm.mock import MockChatLLM

SETTINGS = Settings(_env_file=None, llm_provider="gemini", gcp_project="test-project", gcp_location="us-central1",
                    gemini_timeout_seconds=5.0, llm_overall_deadline_seconds=20.0)
TOOLS = [ToolSpec(name="search_ticketing_guidance", description="Search",
                  parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]})]
USER = [ChatMessage(role="user", text="What is RAC?")]


def _text(text: str) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(candidates=[types.Candidate(
        content=types.Content(role="model", parts=[types.Part.from_text(text=text)]))])


def _call(name: str, args: dict) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(candidates=[types.Candidate(
        content=types.Content(role="model", parts=[types.Part.from_function_call(name=name, args=args)]))])


def _server_error(code: int) -> errors.APIError:
    cls = errors.ServerError if code >= 500 else errors.ClientError
    return cls(code, {"error": {"code": code, "message": "secret upstream detail", "status": "X"}})


class FakeModels:
    """Scripted `aio.models`: each item is a response, an exception to raise, or a float = seconds to hang."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls: list[dict] = []

    async def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        item = self.script.pop(0) if self.script else _text("done")
        if isinstance(item, float):
            await asyncio.sleep(item)
            return _text("too late")
        if isinstance(item, BaseException):
            raise item
        return item


def _client(*script) -> tuple[SimpleNamespace, FakeModels]:
    models = FakeModels(*script)
    return SimpleNamespace(aio=SimpleNamespace(models=models)), models


def _chat(*script, settings: Settings = SETTINGS) -> tuple[GeminiChatLLM, FakeModels]:
    client, models = _client(*script)
    return GeminiChatLLM(settings, client=client, backoff_seconds=0.01), models


# --- GeminiChatLLM -------------------------------------------------------------------------------------------------

def test_text_turn():
    llm, models = _chat(_text("RAC means reservation against cancellation."))
    turn = llm.generate(USER, TOOLS, Deadline(5))
    assert turn.text.startswith("RAC means")
    assert not turn.tool_calls
    cfg = models.calls[0]["config"]
    assert cfg.tools[0].function_declarations[0].name == "search_ticketing_guidance"
    assert models.calls[0]["model"] == SETTINGS.gemini_model


def test_tool_call_turn_and_round_trip():
    llm, models = _chat(_call("search_ticketing_guidance", {"query": "RAC"}), _text("answer"))
    turn = llm.generate(USER, TOOLS, Deadline(5))
    assert turn.tool_calls == (ToolCall(name="search_ticketing_guidance", args={"query": "RAC"}),)
    history = [*USER, turn.as_message(),
               ChatMessage(role="tool", tool_results=(ToolResult(name="search_ticketing_guidance",
                                                                 response={"status": "ok"}),))]
    assert llm.generate(history, TOOLS, Deadline(5)).text == "answer"
    contents = models.calls[1]["contents"]
    assert [c.role for c in contents] == ["user", "model", "user"]
    assert contents[2].parts[0].function_response.name == "search_ticketing_guidance"


@pytest.mark.parametrize("code", [429, 500, 503])
def test_retries_on_429_and_5xx(code):
    llm, models = _chat(_server_error(code), _text("ok"))
    assert llm.generate(USER, TOOLS, Deadline(5)).text == "ok"
    assert len(models.calls) == 2


def test_gives_up_after_two_retries():
    llm, models = _chat(_server_error(503), _server_error(503), _server_error(503), _text("never"))
    with pytest.raises(LLMError) as err:
        llm.generate(USER, TOOLS, Deadline(5))
    assert len(models.calls) == 3
    assert err.value.kind is LLMErrorKind.MODEL_ERROR


def test_throttling_reported_after_retries():
    llm, _ = _chat(_server_error(429), _server_error(429), _server_error(429))
    with pytest.raises(LLMError) as err:
        llm.generate(USER, TOOLS, Deadline(5))
    assert err.value.kind is LLMErrorKind.THROTTLED


@pytest.mark.parametrize("code,kind", [(400, LLMErrorKind.MODEL_ERROR), (401, LLMErrorKind.AUTH),
                                       (403, LLMErrorKind.ACCESS_DENIED), (404, LLMErrorKind.MODEL_ERROR)])
def test_no_retry_on_4xx(code, kind):
    llm, models = _chat(_server_error(code), _text("never"))
    with pytest.raises(LLMError) as err:
        llm.generate(USER, TOOLS, Deadline(5))
    assert len(models.calls) == 1
    assert err.value.kind is kind


def test_error_messages_never_carry_upstream_text():
    llm, _ = _chat(_server_error(400))
    with pytest.raises(LLMError) as err:
        llm.generate(USER, TOOLS, Deadline(5))
    assert "secret upstream detail" not in str(err.value)
    llm, _ = _chat(RuntimeError("token=abc123 leaked"))
    with pytest.raises(LLMError) as err:
        llm.generate(USER, TOOLS, Deadline(5))
    assert "abc123" not in str(err.value)


def test_transport_errors_are_retried():
    llm, models = _chat(httpx.ConnectError("boom"), _text("ok"))
    assert llm.generate(USER, TOOLS, Deadline(5)).text == "ok"
    assert len(models.calls) == 2


def test_per_call_timeout_then_retry():
    settings = SETTINGS.model_copy(update={"gemini_timeout_seconds": 0.2})
    llm, models = _chat(5.0, _text("second try"), settings=settings)
    started = time.monotonic()
    assert llm.generate(USER, TOOLS, Deadline(5)).text == "second try"
    assert time.monotonic() - started < 2
    assert len(models.calls) == 2


def test_slow_llm_is_cut_off_at_the_overall_deadline():
    """Per-call timeout (5 s) is longer than the deadline: the deadline still wins, retries are not attempted."""
    llm, models = _chat(5.0, 5.0, 5.0)
    started = time.monotonic()
    with pytest.raises(LLMError) as err:
        llm.generate(USER, TOOLS, Deadline(0.3))
    elapsed = time.monotonic() - started
    assert err.value.kind is LLMErrorKind.TIMEOUT
    assert elapsed < 1.0
    assert len(models.calls) == 1


def test_expired_deadline_makes_no_call():
    llm, models = _chat(_text("never"))
    with pytest.raises(LLMError) as err:
        llm.generate(USER, TOOLS, Deadline(0))
    assert err.value.kind is LLMErrorKind.TIMEOUT
    assert models.calls == []


def test_backoff_is_clipped_to_the_deadline():
    client, models = _client(_server_error(503), _text("never"))
    llm = GeminiChatLLM(SETTINGS, client=client, backoff_seconds=10.0)
    started = time.monotonic()
    with pytest.raises(LLMError):
        llm.generate(USER, TOOLS, Deadline(0.5))
    assert time.monotonic() - started < 1.0
    assert len(models.calls) == 1


# --- Agent turn bounded by the deadline ------------------------------------------------------------------------------

def test_agent_turn_is_bounded_by_the_overall_deadline():
    llm, _ = _chat(5.0, 5.0, 5.0)
    controller = AgentController(llm, str(DB_PATH), deadline_seconds=0.3)
    started = time.monotonic()
    res = controller.process_message("What is RAC?")
    assert time.monotonic() - started < 1.0
    assert res.status == "service_unavailable"
    assert "abc" not in res.answer


def test_agent_runs_tools_through_the_adapter():
    llm = MockChatLLM([
        [ToolCall(name="search_ticketing_guidance", args={"query": "RAC"})],
        "RAC lets you board with a shared berth.",
    ])
    res = AgentController(llm, str(DB_PATH)).process_message("What is RAC?")
    assert res.status == "answered"
    assert res.answer.startswith("RAC lets you")
    assert res.tool_calls_made == 1
    assert llm.calls[1][-1].role == "tool"


# --- Gemini intent extraction ----------------------------------------------------------------------------------------

CTX = ExtractionContext(language="en", today_iso="2026-10-10", pending_field=None, captured_fields=[])


def test_gemini_intent_parses_json_output():
    client, models = _client(_text('{"intent": "provide_details", "destination_text": "Chennai", '
                                   '"date_text": "tomorrow"}'))
    provider = GeminiIntentProvider(SETTINGS, client=client)
    update = provider.extract_intent("to Chennai tomorrow", CTX)
    assert update.destination_text == "Chennai"
    cfg = models.calls[0]["config"]
    assert cfg.response_mime_type == "application/json"
    assert cfg.response_json_schema


def test_gemini_intent_invalid_output():
    client, _ = _client(_text("not json"))
    with pytest.raises(LLMError) as err:
        GeminiIntentProvider(SETTINGS, client=client).extract_intent("x", CTX)
    assert err.value.kind is LLMErrorKind.INVALID_OUTPUT


def test_slow_gemini_intent_falls_back_to_rules_within_the_deadline(resolver):
    client, _ = _client(5.0, 5.0, 5.0)
    extractor = IntentExtractor(RuleBasedExtractor(resolver), GeminiIntentProvider(SETTINGS, client=client))
    ctx = ExtractionContext(language="en", today_iso="2026-10-10", pending_field=None, captured_fields=[],
                            deadline=Deadline(0.3))
    started = time.monotonic()
    result = extractor.extract("from Bengaluru to Chennai tomorrow", ctx)
    assert time.monotonic() - started < 1.0
    assert result.source == "rules"
    assert result.fallback_reason == "timeout"


def test_slow_bedrock_is_cut_off_at_the_deadline():
    from app.intent.bedrock import BedrockIntentProvider

    bedrock = Settings(_env_file=None, llm_provider="bedrock", aws_region="us-east-1", bedrock_model_id="m")
    client = MagicMock()
    client.converse.side_effect = lambda **_: time.sleep(3)
    provider = BedrockIntentProvider(bedrock, client=client)
    ctx = ExtractionContext(language="en", today_iso="2026-10-10", pending_field=None, captured_fields=[],
                            deadline=Deadline(0.3))
    started = time.monotonic()
    with pytest.raises(LLMError) as err:
        provider.extract_intent("x", ctx)
    assert time.monotonic() - started < 1.0
    assert err.value.kind is LLMErrorKind.TIMEOUT


# --- Container wiring ------------------------------------------------------------------------------------------------

def test_build_llm_chooses_gemini_without_network():
    llm, reason = build_llm(SETTINGS)
    assert reason is None and llm.name == "gemini"


def test_build_llm_gemini_without_project_degrades():
    llm, reason = build_llm(Settings(_env_file=None, llm_provider="gemini", app_env="production",
                                     gemini_api_key="k"))
    assert llm is None and reason == "gemini_not_configured"


def test_build_chat_llm():
    llm, reason = build_chat_llm(SETTINGS)
    assert isinstance(llm, GeminiChatLLM) and reason is None
    llm, reason = build_chat_llm(Settings(_env_file=None))
    assert llm is None and reason == "llm_disabled"
    llm, reason = build_chat_llm(Settings(_env_file=None, llm_provider="bedrock", aws_region="x",
                                          bedrock_model_id="y"))
    assert llm is None and reason == "chat_bedrock_not_supported"
