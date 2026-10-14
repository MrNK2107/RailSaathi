"""Vendor-neutral LLM provider interface for intent extraction.

Error types live in `app.llm.base` (shared with the chat adapter) and are re-exported here."""

from dataclasses import dataclass
from typing import Protocol

from app.intent.schema import IntentUpdate
from app.llm.base import PERSISTENT_ERRORS, Deadline, LLMError, LLMErrorKind

__all__ = ["PERSISTENT_ERRORS", "Deadline", "ExtractionContext", "IntentLLM", "LLMError", "LLMErrorKind"]


@dataclass(frozen=True)
class ExtractionContext:
    language: str
    today_iso: str
    pending_field: str | None
    captured_fields: list[str]
    # Overall budget of the current planner turn. Providers create one from Settings when it is None.
    deadline: Deadline | None = None


class IntentLLM(Protocol):
    name: str

    def extract_intent(self, message: str, context: ExtractionContext) -> IntentUpdate: ...
