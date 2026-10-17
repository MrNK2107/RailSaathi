"""Ollama chat adapter (dev-only local model). `httpx.MockTransport` stands in for the server; no network."""

import json
import time

import httpx

from app.config import Settings
from app.llm.base import ChatMessage, Deadline, LLMError, LLMErrorKind, ToolCall, ToolResult, ToolSpec
from app.llm.ollama import OllamaChatLLM

SETTINGS = Settings(_env_file=None, llm_provider="ollama")
TOOLS = [ToolSpec(name="search_ticketing_guidance", description="Search",
                  parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]})]
USER = [ChatMessage(role="user", text="What is RAC?")]


def _llm(handler, **kw) -> OllamaChatLLM:
    return OllamaChatLLM(SETTINGS, transport=httpx.MockTransport(handler), **kw)


def _reply(message: dict):
    return lambda request: httpx.Response(200, json={"message": message})


def test_request_shape():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "ok"}})

    _llm(handler, system_instruction="Be brief.").generate(USER, TOOLS, Deadline(10))
    body = seen["body"]
    assert seen["path"] == "/api/chat"
    assert body["model"] == "gemma4:latest"
    assert body["stream"] is False and body["think"] is False
    assert body["options"]["num_ctx"] == 8192
    assert body["keep_alive"] == "10m"
    assert body["tools"][0]["function"]["name"] == "search_ticketing_guidance"
    assert body["messages"][0] == {"role": "system", "content": "Be brief."}


def test_text_reply():
    turn = _llm(_reply({"role": "assistant", "content": "RAC means..."})).generate(USER, TOOLS, Deadline(10))
    assert turn.text == "RAC means..."
    assert not turn.tool_calls


def test_tool_call_reply():
    call = {"function": {"name": "search_ticketing_guidance", "arguments": {"query": "RAC"}}}
    turn = _llm(_reply({"role": "assistant", "content": "", "tool_calls": [call]})).generate(USER, TOOLS, Deadline(10))
    assert turn.tool_calls[0] == ToolCall(name="search_ticketing_guidance", args={"query": "RAC"})


def test_tool_results_become_tool_role_messages():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["messages"] = json.loads(request.content)["messages"]
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "done"}})

    history = [*USER,
               ChatMessage(role="assistant", tool_calls=(ToolCall(name="search_ticketing_guidance", args={"query": "RAC"}),)),
               ChatMessage(role="tool", tool_results=(ToolResult(name="search_ticketing_guidance",
                                                                 response={"hits": 1}),))]
    _llm(handler).generate(history, TOOLS, Deadline(10))
    assert seen["messages"][-1] == {"role": "tool", "tool_name": "search_ticketing_guidance",
                                    "content": json.dumps({"hits": 1})}
    assert seen["messages"][-2]["tool_calls"][0]["function"]["arguments"] == {"query": "RAC"}


def test_connection_refused_is_not_configured():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    started = time.monotonic()
    try:
        _llm(handler).generate(USER, TOOLS, Deadline(10))
        raise AssertionError("expected LLMError")
    except LLMError as err:
        assert err.kind == LLMErrorKind.NOT_CONFIGURED
        assert "refused" not in str(err)
    assert time.monotonic() - started < 1.0


def test_missing_model_is_not_configured():
    try:
        _llm(lambda request: httpx.Response(404, json={"error": "model not found"})).generate(USER, TOOLS, Deadline(10))
        raise AssertionError("expected LLMError")
    except LLMError as err:
        assert err.kind == LLMErrorKind.NOT_CONFIGURED


def test_server_error_is_model_error_after_retry():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(500, text="boom")

    try:
        _llm(handler).generate(USER, TOOLS, Deadline(10))
        raise AssertionError("expected LLMError")
    except LLMError as err:
        assert err.kind == LLMErrorKind.MODEL_ERROR
    assert len(calls) == 2


def test_ollama_ignores_foreign_provider_state():
    history = [*USER, ChatMessage(role="assistant", text="hi", provider_state=object())]
    turn = _llm(_reply({"role": "assistant", "content": "ok"})).generate(history, TOOLS, Deadline(10))
    assert turn.text == "ok"


def test_ollama_configured_false_in_production():
    assert Settings(_env_file=None, app_env="production", llm_provider="ollama").ollama_configured is False
    assert Settings(_env_file=None, llm_provider="ollama").ollama_configured is True
    assert Settings(_env_file=None, llm_provider="gemini", llm_fallback="ollama").ollama_configured is True
    assert Settings(_env_file=None).ollama_configured is False
