"""Planner intent extraction on a local Ollama model (development only), implementing the `IntentLLM` Protocol.

Structured output: Ollama constrains the reply to the IntentUpdate JSON schema (`format`), and the result is still
validated with Pydantic before use. Shares the serialised call path and deadline handling of the chat adapter."""

from typing import Any

import httpx

from app.config import Settings
from app.intent.llm import Deadline, ExtractionContext
from app.intent.prompt import JSON_SYSTEM_PROMPT, TOOL_SCHEMA, parse_json_text, user_payload, validate_intent
from app.intent.schema import IntentUpdate
from app.llm.ollama import OllamaCaller, provider_name


class OllamaIntentProvider:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self.name = provider_name(settings)
        self._caller = OllamaCaller(settings, transport)
        self._deadline_seconds = settings.llm_overall_deadline_seconds

    def extract_intent(self, message: str, context: ExtractionContext) -> IntentUpdate:
        payload: dict[str, Any] = {
            "messages": [{"role": "system", "content": JSON_SYSTEM_PROMPT},
                         {"role": "user", "content": user_payload(message, context)}],
            "format": TOOL_SCHEMA,
            "options": {"temperature": 0, "num_predict": 800},
        }
        deadline = context.deadline or Deadline(self._deadline_seconds)
        data = self._caller.chat(payload, deadline)
        return validate_intent(parse_json_text((data.get("message") or {}).get("content") or ""))
