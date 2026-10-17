"""Gemini first, a local model (Ollama, development only) when Gemini cannot answer.

Policy, shared by the chat agent and planner intent extraction:
- An `LLMError` in `FALLBACK_ERRORS` from the primary starts a cooldown of `COOLDOWN_SECONDS`, during which every
  call goes straight to the secondary. The failed call itself is retried on the secondary only if the turn deadline
  has at least `MIN_FALLBACK_SECONDS` left; otherwise the error is re-raised.
- Other errors (timeouts, model errors, invalid output) are re-raised and start no cooldown: the primary is up.
- `name` is the provider that answered the current call, held in a `ContextVar` so concurrent requests (and the
  executor threads extraction runs in) each see their own answer; it defaults to the primary's name.
"""

import contextvars
import itertools
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import TypeVar

from app.intent.llm import ExtractionContext, IntentLLM
from app.intent.schema import IntentUpdate
from app.llm.base import PERSISTENT_ERRORS, ChatLLM, ChatMessage, Deadline, LLMError, LLMErrorKind, LLMTurn, ToolSpec

COOLDOWN_SECONDS = 60
FALLBACK_ERRORS = PERSISTENT_ERRORS | {LLMErrorKind.THROTTLED}
# A mid-turn retry on the secondary model only happens if the deadline has at least this much left.
# Adjust after the Task 11 latency measurement.
MIN_FALLBACK_SECONDS = 8.0

T = TypeVar("T")
_ids = itertools.count()


class _Fallback:
    def __init__(self, primary, secondary, clock: Callable[[], float] = time.monotonic) -> None:
        self.primary = primary
        self.secondary = secondary
        self._clock = clock
        self._cooling_until: float | None = None
        self._answered: contextvars.ContextVar[str | None] = contextvars.ContextVar(
            f"llm_fallback_answered_{next(_ids)}", default=None)

    @property
    def name(self) -> str:
        return self._answered.get() or self.primary.name

    def _cooling(self) -> bool:
        if self._cooling_until is not None and self._clock() >= self._cooling_until:
            self._cooling_until = None
        return self._cooling_until is not None

    def status(self) -> dict:
        cooling = self._cooling()
        return {"active": self.secondary.name if cooling else self.primary.name,
                "primary_cooling_until": self._cooling_until}

    def _call(self, call: Callable[[object], T], deadline: Deadline | None) -> T:
        if not self._cooling():
            try:
                result = call(self.primary)
                self._answered.set(self.primary.name)
                return result
            except LLMError as err:
                if err.kind not in FALLBACK_ERRORS:
                    raise
                self._cooling_until = self._clock() + COOLDOWN_SECONDS
                if deadline is not None and deadline.remaining() < MIN_FALLBACK_SECONDS:
                    raise
        result = call(self.secondary)
        self._answered.set(self.secondary.name)
        return result


class FallbackChatLLM(_Fallback):
    """`ChatLLM` that answers on `primary`, or on `secondary` while the primary is failing persistently."""

    def __init__(self, primary: ChatLLM, secondary: ChatLLM, clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__(primary, secondary, clock)

    def generate(self, messages: Sequence[ChatMessage], tools: Sequence[ToolSpec], deadline: Deadline) -> LLMTurn:
        return self._call(lambda llm: llm.generate(messages, tools, deadline), deadline)


class FallbackIntentLLM(_Fallback):
    """`IntentLLM` with the same policy. `deadline_seconds` bounds both providers with one budget when the
    context carries no deadline (each provider would otherwise start its own)."""

    def __init__(self, primary: IntentLLM, secondary: IntentLLM, clock: Callable[[], float] = time.monotonic,
                 deadline_seconds: float | None = None) -> None:
        super().__init__(primary, secondary, clock)
        self._deadline_seconds = deadline_seconds

    def extract_intent(self, message: str, context: ExtractionContext) -> IntentUpdate:
        if context.deadline is None and self._deadline_seconds is not None:
            context = replace(context, deadline=Deadline(self._deadline_seconds))
        return self._call(lambda llm: llm.extract_intent(message, context), context.deadline)
