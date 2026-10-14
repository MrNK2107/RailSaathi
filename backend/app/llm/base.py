"""Vendor-neutral LLM primitives shared by the chat agent and planner intent extraction.

- `ChatLLM`: `generate(messages, tools, deadline) -> LLMTurn` (text or tool calls).
- `Deadline`: one monotonic budget for a whole planner/agent turn. Every LLM path clips its per-call timeout,
  retries and backoff to `deadline.remaining()`, so a turn can never outlive the session lock TTL
  (validated in config.py against `llm_overall_deadline_seconds`).
- `LLMError`: carries a kind and a fixed, client-safe message. Upstream exception text is never put in it.
- `call_with_retries`: per-call timeout, retry on transient failures with exponential backoff, all bounded by
  the deadline.
"""

import asyncio
import concurrent.futures
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Protocol, TypeVar

log = logging.getLogger("railsaathi.llm")
T = TypeVar("T")


class LLMErrorKind(StrEnum):
    NOT_CONFIGURED = "not_configured"
    AUTH = "auth_failed"
    ACCESS_DENIED = "access_denied"
    THROTTLED = "throttled"
    TIMEOUT = "timeout"
    MODEL_ERROR = "model_error"
    INVALID_OUTPUT = "invalid_output"


# Errors that will not fix themselves on the next request: pause the provider.
PERSISTENT_ERRORS = frozenset({LLMErrorKind.NOT_CONFIGURED, LLMErrorKind.AUTH, LLMErrorKind.ACCESS_DENIED})

# Fixed, client-safe messages. Never interpolate exception text into an LLMError.
SAFE_MESSAGES = {
    LLMErrorKind.NOT_CONFIGURED: "The language model is not configured.",
    LLMErrorKind.AUTH: "The language model rejected the service credentials.",
    LLMErrorKind.ACCESS_DENIED: "The service is not allowed to use the language model.",
    LLMErrorKind.THROTTLED: "The language model is busy. Please try again shortly.",
    LLMErrorKind.TIMEOUT: "The language model did not respond in time.",
    LLMErrorKind.MODEL_ERROR: "The language model returned an error.",
    LLMErrorKind.INVALID_OUTPUT: "The language model returned an unusable answer.",
}


class LLMError(Exception):
    def __init__(self, kind: LLMErrorKind, message: str | None = None) -> None:
        super().__init__(message or SAFE_MESSAGES[kind])
        self.kind = kind


class Deadline:
    """Absolute monotonic deadline for one turn."""

    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.seconds = seconds
        self._expires = clock() + max(0.0, seconds)

    def remaining(self) -> float:
        return max(0.0, self._expires - self._clock())

    @property
    def expired(self) -> bool:
        return self.remaining() <= 0.0

    def clip(self, timeout: float) -> float:
        return min(timeout, self.remaining())


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    id: str | None = None


@dataclass(frozen=True)
class ToolResult:
    name: str
    response: dict[str, Any]
    call_id: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema of the arguments object


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["user", "assistant", "tool"]
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_results: tuple[ToolResult, ...] = ()
    # Opaque provider-native content of an assistant turn (e.g. Gemini Content with thought signatures),
    # replayed verbatim by the same provider and ignored by others.
    provider_state: Any = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class LLMTurn:
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    provider_state: Any = field(default=None, compare=False, repr=False)

    @property
    def is_tool_call(self) -> bool:
        return bool(self.tool_calls)

    def as_message(self) -> ChatMessage:
        return ChatMessage(role="assistant", text=self.text, tool_calls=self.tool_calls,
                           provider_state=self.provider_state)


class ChatLLM(Protocol):
    name: str

    def generate(self, messages: Sequence[ChatMessage], tools: Sequence[ToolSpec], deadline: Deadline) -> LLMTurn: ...


def tool_specs(schemas: dict[str, dict[str, Any]], allowed: set[str] | None = None) -> list[ToolSpec]:
    """Registry schemas (`{"name", "description", "parameters"}`) -> ToolSpecs."""
    return [ToolSpec(name=s["name"], description=s.get("description", ""),
                     parameters=s.get("parameters") or {"type": "object", "properties": {}})
            for name, s in schemas.items() if allowed is None or name in allowed]


Classifier = Callable[[BaseException], tuple[LLMError, bool]]  # -> (sanitised error, retryable)


async def call_with_retries(attempt: Callable[[], Awaitable[T]], *, deadline: Deadline, per_call_timeout: float,
                            max_retries: int, classify: Classifier, backoff_seconds: float = 0.5,
                            provider: str = "llm") -> T:
    """Run `attempt()` with a per-call timeout clipped to the deadline; retry transient failures with
    exponential backoff while the deadline allows. Raises a sanitised LLMError."""
    last: LLMError | None = None
    for index in range(max_retries + 1):
        remaining = deadline.remaining()
        if remaining <= 0:
            break
        try:
            return await asyncio.wait_for(attempt(), timeout=min(per_call_timeout, remaining))
        except LLMError as err:  # already sanitised (e.g. invalid output): not retried
            raise err
        except TimeoutError:
            last, retryable = LLMError(LLMErrorKind.TIMEOUT), True
        except Exception as exc:  # noqa: BLE001 - classified and sanitised below
            last, retryable = classify(exc)
        log.warning("%s call failed (%s, attempt %d)", provider, last.kind.value, index + 1)
        if not retryable or index == max_retries:
            raise last
        delay = backoff_seconds * (2 ** index)
        if delay >= deadline.remaining():
            break
        await asyncio.sleep(delay)
    # Deadline exhausted. Report the last failure kind (a throttled call stays "throttled"); none -> timeout.
    log.warning("%s turn deadline exhausted", provider)
    raise last or LLMError(LLMErrorKind.TIMEOUT)


def run_blocking_with_deadline(fn: Callable[[], T], deadline: Deadline, executor: concurrent.futures.Executor) -> T:
    """Run a blocking SDK call in `executor` and stop waiting when the deadline passes.

    The abandoned call keeps running in its worker until the SDK's own (clipped) socket timeouts end it, but the
    turn returns on time and the session lock is released."""
    remaining = deadline.remaining()
    if remaining <= 0:
        raise LLMError(LLMErrorKind.TIMEOUT)
    future = executor.submit(fn)
    try:
        return future.result(timeout=remaining)
    except concurrent.futures.TimeoutError as exc:
        future.cancel()
        raise LLMError(LLMErrorKind.TIMEOUT) from exc
