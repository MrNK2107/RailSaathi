"""Gemini through the google-genai SDK.

Production uses Vertex AI (`vertexai=True`, project/location from Settings) with the Cloud Run service account's
credentials; no API key. Outside production an API key may be used for local experiments when no project is set.

Calls use the SDK's async client on the shared background loop (`infra/async_bridge.py`), so a per-call timeout
or the turn deadline cancels the HTTP request itself instead of abandoning a thread.
"""

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, TypeVar

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

log = logging.getLogger("railsaathi.llm.gemini")
T = TypeVar("T")
# Seconds the bridge waits beyond the deadline before giving up on the loop itself (the coroutine is already
# bounded by asyncio.wait_for; this is only a backstop).
_BRIDGE_SLACK_SECONDS = 1.0


def gemini_credentials_available(settings: Settings) -> bool:
    return bool(settings.gcp_project) or (bool(settings.gemini_api_key) and not settings.is_production)


def build_genai_client(settings: Settings) -> Any:
    """Vertex AI client (no network here; credentials are resolved lazily on the first call)."""
    from google import genai

    if settings.gcp_project:
        return genai.Client(vertexai=True, project=settings.gcp_project, location=settings.gcp_location)
    if settings.gemini_api_key and not settings.is_production:
        return genai.Client(api_key=settings.gemini_api_key)
    raise LLMError(LLMErrorKind.NOT_CONFIGURED, "Gemini needs GOOGLE_CLOUD_PROJECT (Vertex AI)")


def classify(exc: BaseException) -> tuple[LLMError, bool]:
    """Map an SDK/transport exception to (sanitised LLMError, retryable). 429 and 5xx are retried; other 4xx
    are not. Transport failures and timeouts are retried (they behave like 503/504)."""
    from google.auth.exceptions import GoogleAuthError
    from google.genai import errors

    if isinstance(exc, errors.APIError):
        code = int(getattr(exc, "code", 0) or 0)
        if code == 429:
            return LLMError(LLMErrorKind.THROTTLED), True
        if code >= 500:
            return LLMError(LLMErrorKind.MODEL_ERROR), True
        if code == 401:
            return LLMError(LLMErrorKind.AUTH), False
        if code == 403:
            return LLMError(LLMErrorKind.ACCESS_DENIED), False
        return LLMError(LLMErrorKind.MODEL_ERROR), False
    if isinstance(exc, httpx.TimeoutException):
        return LLMError(LLMErrorKind.TIMEOUT), True
    if isinstance(exc, httpx.TransportError):
        return LLMError(LLMErrorKind.MODEL_ERROR), True
    if isinstance(exc, GoogleAuthError):
        return LLMError(LLMErrorKind.AUTH), False
    log.warning("Unexpected Gemini failure: %s", type(exc).__name__)
    return LLMError(LLMErrorKind.MODEL_ERROR), False


class GeminiCaller:
    """Shared call path for every Gemini use: retries, per-call timeout and the turn deadline."""

    def __init__(self, settings: Settings, client: Any | None = None, backoff_seconds: float = 0.5) -> None:
        self.model = settings.gemini_model
        self._settings = settings
        self._client = client
        self._per_call_timeout = settings.gemini_timeout_seconds
        self._max_retries = settings.gemini_max_retries
        self._backoff = backoff_seconds

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = build_genai_client(self._settings)
        return self._client

    def generate(self, contents: Any, config: Any, deadline: Deadline) -> Any:
        client = self.client

        def attempt() -> Awaitable[Any]:
            return client.aio.models.generate_content(model=self.model, contents=contents, config=config)

        return self._run(attempt, deadline)

    def _run(self, attempt: Callable[[], Awaitable[T]], deadline: Deadline) -> T:
        if deadline.expired:
            raise LLMError(LLMErrorKind.TIMEOUT)
        coro = call_with_retries(attempt, deadline=deadline, per_call_timeout=self._per_call_timeout,
                                 max_retries=self._max_retries, classify=classify,
                                 backoff_seconds=self._backoff, provider="gemini")
        try:
            return run_sync(coro, timeout=deadline.remaining() + _BRIDGE_SLACK_SECONDS)
        except ProviderError as exc:  # bridge backstop fired
            raise LLMError(LLMErrorKind.TIMEOUT) from exc


def _schema_or_empty(parameters: dict[str, Any]) -> dict[str, Any]:
    return parameters or {"type": "object", "properties": {}}


def to_contents(messages: Sequence[ChatMessage]) -> list[Any]:
    from google.genai import types

    contents = []
    for m in messages:
        if m.role == "user":
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=m.text)]))
        elif m.role == "assistant":
            if isinstance(m.provider_state, types.Content):
                contents.append(m.provider_state)  # keeps thought signatures intact
                continue
            parts = [types.Part.from_text(text=m.text)] if m.text else []
            parts += [types.Part.from_function_call(name=c.name, args=c.args) for c in m.tool_calls]
            contents.append(types.Content(role="model", parts=parts or [types.Part.from_text(text="")]))
        else:
            contents.append(types.Content(role="user", parts=[
                types.Part.from_function_response(name=r.name, response=r.response) for r in m.tool_results]))
    return contents


def to_turn(response: Any) -> LLMTurn:
    candidates = getattr(response, "candidates", None) or []
    if not candidates or candidates[0].content is None:
        return LLMTurn()
    content = candidates[0].content
    texts, calls = [], []
    for part in content.parts or []:
        if part is None:
            continue
        if part.function_call:
            fc = part.function_call
            calls.append(ToolCall(name=fc.name or "", args=dict(fc.args or {}), id=getattr(fc, "id", None)))
        elif part.text and not getattr(part, "thought", False):
            texts.append(part.text)
    return LLMTurn(text="\n".join(texts), tool_calls=tuple(calls), provider_state=content)


class GeminiChatLLM:
    """`ChatLLM` on Gemini with native function calling."""

    name = "gemini"

    def __init__(self, settings: Settings, client: Any | None = None, system_instruction: str | None = None,
                 backoff_seconds: float = 0.5) -> None:
        self._caller = GeminiCaller(settings, client, backoff_seconds)
        self._system = system_instruction
        self._temperature = settings.gemini_temperature
        self._max_tokens = settings.gemini_max_output_tokens

    def generate(self, messages: Sequence[ChatMessage], tools: Sequence[ToolSpec], deadline: Deadline) -> LLMTurn:
        from google.genai import types

        declarations = [types.FunctionDeclaration(name=t.name, description=t.description,
                                                  parameters_json_schema=_schema_or_empty(t.parameters))
                        for t in tools]
        config = types.GenerateContentConfig(
            temperature=self._temperature,
            max_output_tokens=self._max_tokens,
            system_instruction=self._system,
            tools=[types.Tool(function_declarations=declarations)] if declarations else None,
            # Tools are validated and executed by AgentController, never by the SDK.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        return to_turn(self._caller.generate(to_contents(messages), config, deadline))
