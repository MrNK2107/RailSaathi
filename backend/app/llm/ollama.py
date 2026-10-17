"""A local model served by Ollama (`/api/chat`). Development only: `Settings.ollama_configured` is False in
production, so nothing builds this there.

The server runs one model on one machine, so requests are serialised with a module-level lock. Calls reuse the
shared retry/deadline helpers like `GeminiCaller`: the blocking httpx call runs on an executor thread and the retry
loop is bounded by the turn deadline. Error messages are the fixed `SAFE_MESSAGES`.
"""

import asyncio
import concurrent.futures
import json
import logging
import threading
from collections.abc import Sequence
from typing import Any

import httpx

from app.config import Settings
from app.infra.async_bridge import run_sync
from app.llm.base import (
    ChatMessage,
    Deadline,
    LLMError,
    LLMErrorKind,
    LLMTurn,
    ToolCall,
    ToolSpec,
    call_with_retries,
)
from app.providers.errors import ProviderError

log = logging.getLogger("railsaathi.llm.ollama")
_BRIDGE_SLACK_SECONDS = 1.0
_LOCK = threading.Lock()  # one request at a time against the local model
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="ollama")


def provider_name(settings: Settings) -> str:
    """Short model name used as the provider label (`gemma4:latest` -> `gemma4`)."""
    return settings.ollama_model.split(":")[0]


def classify(exc: BaseException) -> tuple[LLMError, bool]:
    """Map a transport/HTTP exception to (sanitised LLMError, retryable). A refused connection or a missing model
    means Ollama is not set up (not retried); 429, 5xx and timeouts are."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 404:
            return LLMError(LLMErrorKind.NOT_CONFIGURED), False
        if code == 429:
            return LLMError(LLMErrorKind.THROTTLED), True
        if code >= 500:
            return LLMError(LLMErrorKind.MODEL_ERROR), True
        return LLMError(LLMErrorKind.MODEL_ERROR), False
    if isinstance(exc, httpx.ConnectError):
        return LLMError(LLMErrorKind.NOT_CONFIGURED), False
    if isinstance(exc, httpx.TimeoutException):
        return LLMError(LLMErrorKind.TIMEOUT), True
    if isinstance(exc, httpx.TransportError):
        return LLMError(LLMErrorKind.MODEL_ERROR), True
    log.warning("Unexpected Ollama failure: %s", type(exc).__name__)
    return LLMError(LLMErrorKind.MODEL_ERROR), False


class OllamaCaller:
    """Shared call path for the local model: serialised, retried, bounded by the turn deadline."""

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None,
                 backoff_seconds: float = 0.2, max_retries: int = 1) -> None:
        self.model = settings.ollama_model
        self._url = settings.ollama_url.rstrip("/")
        self._num_ctx = settings.ollama_num_ctx
        self._keep_alive = settings.ollama_keep_alive
        self._per_call_timeout = settings.ollama_timeout_seconds
        self._transport = transport
        self._backoff = backoff_seconds
        self._max_retries = max_retries

    def _post(self, payload: dict[str, Any], budget: Deadline) -> dict[str, Any]:
        """One attempt within `budget` (the per-call timeout clipped to the turn deadline). Waiting for the model
        lock counts against it: a request queued behind another gives up instead of running past its turn."""
        body = {**payload, "model": self.model, "stream": False, "think": False,
                "keep_alive": self._keep_alive,
                "options": {**(payload.get("options") or {}), "num_ctx": self._num_ctx}}
        if not _LOCK.acquire(timeout=budget.remaining()):
            raise LLMError(LLMErrorKind.TIMEOUT)
        try:
            timeout = max(budget.remaining(), 0.001)  # what is left after the lock wait
            with httpx.Client(transport=self._transport, timeout=timeout) as client:
                response = client.post(f"{self._url}/api/chat", json=body)
                response.raise_for_status()
                return response.json()
        finally:
            _LOCK.release()

    def chat(self, payload: dict[str, Any], deadline: Deadline) -> dict[str, Any]:
        if deadline.expired:
            raise LLMError(LLMErrorKind.TIMEOUT)

        async def attempt() -> dict[str, Any]:
            budget = Deadline(deadline.clip(self._per_call_timeout))
            return await asyncio.get_running_loop().run_in_executor(_EXECUTOR, self._post, payload, budget)

        coro = call_with_retries(attempt, deadline=deadline, per_call_timeout=self._per_call_timeout,
                                 max_retries=self._max_retries, classify=classify,
                                 backoff_seconds=self._backoff, provider="ollama")
        try:
            return run_sync(coro, timeout=deadline.remaining() + _BRIDGE_SLACK_SECONDS)
        except ProviderError as exc:  # bridge backstop fired
            raise LLMError(LLMErrorKind.TIMEOUT) from exc


def to_messages(messages: Sequence[ChatMessage], system: str | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"role": "system", "content": system}] if system else []
    for m in messages:
        if m.role == "user":
            out.append({"role": "user", "content": m.text})
        elif m.role == "assistant":  # provider_state belongs to another provider; rebuilt from text and calls
            item: dict[str, Any] = {"role": "assistant", "content": m.text}
            if m.tool_calls:
                item["tool_calls"] = [{"function": {"name": c.name, "arguments": c.args}} for c in m.tool_calls]
            out.append(item)
        else:
            out += [{"role": "tool", "tool_name": r.name, "content": json.dumps(r.response, ensure_ascii=False)}
                    for r in m.tool_results]
    return out


def to_tools(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    return [{"type": "function", "function": {
        "name": t.name, "description": t.description,
        "parameters": t.parameters or {"type": "object", "properties": {}}}} for t in tools]


def to_turn(data: dict[str, Any], model: str | None = None) -> LLMTurn:
    message = data.get("message") or {}
    calls = []
    for raw in message.get("tool_calls") or []:
        fn = raw.get("function") or {}
        args = fn.get("arguments") or {}
        if isinstance(args, str):  # some models return the arguments as a JSON string
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        calls.append(ToolCall(name=fn.get("name") or "", args=dict(args) if isinstance(args, dict) else {}))
    return LLMTurn(text=message.get("content") or "", tool_calls=tuple(calls), model=model)


class OllamaChatLLM:
    """`ChatLLM` on a local Ollama model with native tool calling."""

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None,
                 system_instruction: str | None = None) -> None:
        self.name = provider_name(settings)
        self._caller = OllamaCaller(settings, transport)
        self._system = system_instruction

    def generate(self, messages: Sequence[ChatMessage], tools: Sequence[ToolSpec], deadline: Deadline) -> LLMTurn:
        payload: dict[str, Any] = {"messages": to_messages(messages, self._system)}
        if tools:
            payload["tools"] = to_tools(tools)
        return to_turn(self._caller.chat(payload, deadline), model=f"{self.name} (local)")
