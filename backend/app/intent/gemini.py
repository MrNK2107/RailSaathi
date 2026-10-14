"""Planner intent extraction on Gemini (Vertex AI), implementing the `IntentLLM` Protocol.

Structured output: the response is constrained to JSON matching the IntentUpdate schema and is still validated
with Pydantic before use. Shares the retry, timeout and deadline handling of the chat adapter."""

from typing import Any

from app.config import Settings
from app.intent.llm import Deadline, ExtractionContext, LLMError, LLMErrorKind
from app.intent.prompt import JSON_SYSTEM_PROMPT, TOOL_SCHEMA, parse_json_text, user_payload, validate_intent
from app.intent.schema import IntentUpdate
from app.llm.gemini import GeminiCaller, gemini_credentials_available


class GeminiIntentProvider:
    name = "gemini"

    def __init__(self, settings: Settings, client: Any | None = None, backoff_seconds: float = 0.5) -> None:
        if client is None and not gemini_credentials_available(settings):
            raise LLMError(LLMErrorKind.NOT_CONFIGURED)
        self._caller = GeminiCaller(settings, client, backoff_seconds)
        self._deadline_seconds = settings.llm_overall_deadline_seconds

    def extract_intent(self, message: str, context: ExtractionContext) -> IntentUpdate:
        from google.genai import types

        config = types.GenerateContentConfig(
            temperature=0,
            max_output_tokens=800,
            system_instruction=JSON_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_json_schema=TOOL_SCHEMA,
        )
        contents = [types.Content(role="user", parts=[types.Part.from_text(text=user_payload(message, context))])]
        deadline = context.deadline or Deadline(self._deadline_seconds)
        response = self._caller.generate(contents, config, deadline)
        return validate_intent(parse_json_text(_text_of(response)))


def _text_of(response: Any) -> str:
    candidates = getattr(response, "candidates", None) or []
    if not candidates or candidates[0].content is None:
        return ""
    return "".join(p.text for p in candidates[0].content.parts or [] if p is not None and p.text
                   and not getattr(p, "thought", False))
