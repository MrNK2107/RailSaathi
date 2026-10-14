"""Provider-independent pieces of LLM intent extraction: the system prompt, the IntentUpdate JSON schema
(self-contained, no $refs), the request payload and validation of the model's raw output."""

import json
from typing import Any

from pydantic import ValidationError

from app.intent.llm import ExtractionContext, LLMError, LLMErrorKind
from app.intent.schema import IntentUpdate

TOOL_NAME = "record_journey_intent"
SYSTEM_PROMPT = """You extract Indian Railways journey-planning details from a passenger's message.
The message may be English, Tamil script, or Tamil written in English letters (Tanglish).
Rules:
- Call the record_journey_intent tool exactly once. Use null / empty lists for anything not stated.
- Copy place names exactly as the passenger wrote them. Never pick or invent a station.
- Copy dates and times as the passenger said them (e.g. "tomorrow", "9 am", "நாளை"). Do not compute calendar dates.
- Keep day and clock time separate: the day/date goes in date_text ("tomorrow") and only the clock
  time goes in arrival_deadline_text ("9 am"). Never put words like "tomorrow" in a time field.
- date_anchor is "arrival" when the passenger says when they must reach/arrive; "departure" only when
  the date clearly refers to leaving.
- Add a passenger need only when the passenger states it. Do not infer needs from relationships
  (e.g. "with my mother" does NOT imply elderly or assistance unless they say so).
- passenger_count counts the speaker plus every companion they mention ("I am travelling with my
  mother" = 2). Leave it null if the number of companions is unclear (e.g. "with my kids").
- deadline_strict is false only when the passenger signals flexibility ("ideally", "around").
- budget_strict / class_strict / transfer_strict / assistance_mandatory are true only when the passenger
  explicitly says it is mandatory ("must", "only", "essential"). "She needs assistance" is a request
  (needs_add=["assistance_requested"]), not mandatory.
- If the assistant was waiting for a specific field (pending_field) and the message is a bare answer, fill that field.
- Never invent trains, fares, schedules, availability or bookings. You only interpret the request."""

# Providers that answer with JSON instead of a tool call get the same rules with this ending.
JSON_SYSTEM_PROMPT = SYSTEM_PROMPT.replace(
    "- Call the record_journey_intent tool exactly once.",
    "- Answer with one JSON object matching the response schema.",
)


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline Pydantic $defs so the schema is self-contained."""
    defs = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].split("/")[-1]])
            return {k: walk(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


TOOL_SCHEMA = inline_refs(IntentUpdate.model_json_schema())


def user_payload(message: str, context: ExtractionContext) -> str:
    return json.dumps({
        "passenger_message": message,
        "language": context.language,
        "pending_field": context.pending_field,
        "already_captured_fields": context.captured_fields,
    }, ensure_ascii=False)


def parse_json_text(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(LLMErrorKind.INVALID_OUTPUT, "Model did not return structured output") from exc


def validate_intent(raw: Any) -> IntentUpdate:
    try:
        return IntentUpdate.model_validate(raw)
    except ValidationError as exc:
        raise LLMError(LLMErrorKind.INVALID_OUTPUT,
                       f"Model output failed schema validation ({exc.error_count()} errors)") from exc
