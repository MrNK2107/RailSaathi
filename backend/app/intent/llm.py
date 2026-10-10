"""Vendor-neutral LLM provider interface for intent extraction."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.intent.schema import IntentUpdate


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


class LLMError(Exception):
    def __init__(self, kind: LLMErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class ExtractionContext:
    language: str
    today_iso: str
    pending_field: str | None
    captured_fields: list[str]


class IntentLLM(Protocol):
    name: str

    def extract_intent(self, message: str, context: ExtractionContext) -> IntentUpdate: ...
