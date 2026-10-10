"""Claude on AWS Bedrock via the Bedrock Runtime Converse API (boto3).

Structured output: the request forces a single tool ("record_journey_intent")
whose input schema is the IntentUpdate JSON schema, so the model must answer
with schema-shaped JSON. The result is still validated with Pydantic before use.

Credentials come only from the standard AWS credential chain (env vars,
AWS_PROFILE, SSO, instance/role credentials). Nothing is hard-coded here.
"""

import json
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    NoCredentialsError,
    NoRegionError,
    PartialCredentialsError,
    ProfileNotFound,
    ReadTimeoutError,
)
from pydantic import ValidationError

from app.config import Settings
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

_ERROR_MAP = {
    "AccessDeniedException": LLMErrorKind.ACCESS_DENIED,
    "UnrecognizedClientException": LLMErrorKind.AUTH,
    "ExpiredTokenException": LLMErrorKind.AUTH,
    "InvalidSignatureException": LLMErrorKind.AUTH,
    "ThrottlingException": LLMErrorKind.THROTTLED,
    "ServiceQuotaExceededException": LLMErrorKind.THROTTLED,
    "TooManyRequestsException": LLMErrorKind.THROTTLED,
    "ModelTimeoutException": LLMErrorKind.TIMEOUT,
}


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline Pydantic $defs so the tool schema is self-contained."""
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


def map_client_error(err: ClientError) -> LLMError:
    code = err.response.get("Error", {}).get("Code", "Unknown")
    kind = _ERROR_MAP.get(code, LLMErrorKind.MODEL_ERROR)
    return LLMError(kind, f"Bedrock error {code}")


class BedrockIntentProvider:
    name = "bedrock"

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        if not (settings.aws_region and settings.bedrock_model_id):
            raise LLMError(LLMErrorKind.NOT_CONFIGURED, "AWS_REGION and BEDROCK_MODEL_ID must be set")
        self._model_id = settings.bedrock_model_id
        self._client = client or self._build_client(settings)

    @staticmethod
    def _build_client(settings: Settings) -> Any:
        try:
            session = boto3.Session(profile_name=settings.aws_profile or None, region_name=settings.aws_region)
        except ProfileNotFound as exc:
            raise LLMError(LLMErrorKind.NOT_CONFIGURED, f"AWS profile not found: {exc}") from exc
        config = Config(
            connect_timeout=settings.bedrock_timeout_seconds,
            read_timeout=settings.bedrock_timeout_seconds,
            retries={"max_attempts": settings.bedrock_max_retries + 1, "mode": "standard"},
        )
        return session.client("bedrock-runtime", config=config)

    def build_request(self, message: str, context: ExtractionContext) -> dict[str, Any]:
        payload = {
            "passenger_message": message,
            "language": context.language,
            "pending_field": context.pending_field,
            "already_captured_fields": context.captured_fields,
        }
        return {
            "modelId": self._model_id,
            "system": [{"text": SYSTEM_PROMPT}],
            "messages": [{"role": "user", "content": [{"text": json.dumps(payload, ensure_ascii=False)}]}],
            "toolConfig": {
                "tools": [{"toolSpec": {
                    "name": TOOL_NAME,
                    "description": "Record the structured journey intent extracted from the passenger message.",
                    "inputSchema": {"json": TOOL_SCHEMA},
                }}],
                "toolChoice": {"tool": {"name": TOOL_NAME}},
            },
            "inferenceConfig": {"maxTokens": 800, "temperature": 0},
        }

    def extract_intent(self, message: str, context: ExtractionContext) -> IntentUpdate:
        response = self._call(self.build_request(message, context))
        return parse_response(response)

    def ping(self) -> str:
        """Minimal live call used by scripts/check_bedrock.py."""
        response = self._call({
            "modelId": self._model_id,
            "messages": [{"role": "user", "content": [{"text": "Reply with the single word: ok"}]}],
            "inferenceConfig": {"maxTokens": 10, "temperature": 0},
        })
        blocks = response.get("output", {}).get("message", {}).get("content", [])
        return "".join(b.get("text", "") for b in blocks).strip()

    def _call(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._client.converse(**request)
        except ClientError as exc:
            raise map_client_error(exc) from exc
        except (NoCredentialsError, PartialCredentialsError) as exc:
            raise LLMError(LLMErrorKind.AUTH, "AWS credentials not found or incomplete") from exc
        except NoRegionError as exc:
            raise LLMError(LLMErrorKind.NOT_CONFIGURED, "AWS region not configured") from exc
        except (ReadTimeoutError, ConnectTimeoutError, EndpointConnectionError) as exc:
            raise LLMError(LLMErrorKind.TIMEOUT, "Bedrock request timed out or endpoint unreachable") from exc
        except BotoCoreError as exc:
            raise LLMError(LLMErrorKind.MODEL_ERROR, f"Bedrock client error: {type(exc).__name__}") from exc


def parse_response(response: dict[str, Any]) -> IntentUpdate:
    blocks = response.get("output", {}).get("message", {}).get("content", [])
    raw: Any = next((b["toolUse"]["input"] for b in blocks if "toolUse" in b), None)
    if raw is None:
        text = "".join(b.get("text", "") for b in blocks)
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(LLMErrorKind.INVALID_OUTPUT, "Model did not return structured output") from exc
    try:
        return IntentUpdate.model_validate(raw)
    except ValidationError as exc:
        raise LLMError(LLMErrorKind.INVALID_OUTPUT, f"Model output failed schema validation ({exc.error_count()} errors)") from exc
