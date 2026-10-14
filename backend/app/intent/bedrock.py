"""Claude on AWS Bedrock via the Bedrock Runtime Converse API (boto3).

Structured output: the request forces a single tool ("record_journey_intent")
whose input schema is the IntentUpdate JSON schema, so the model must answer
with schema-shaped JSON. The result is still validated with Pydantic before use.

Credentials come only from the standard AWS credential chain (env vars,
AWS_PROFILE, SSO, instance/role credentials). Nothing is hard-coded here.
"""

import concurrent.futures
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
from app.config import Settings
from app.intent.llm import Deadline, ExtractionContext, LLMError, LLMErrorKind
from app.intent.prompt import (  # noqa: F401 - TOOL_SCHEMA / inline_refs re-exported for callers and tests
    SYSTEM_PROMPT,
    TOOL_NAME,
    TOOL_SCHEMA,
    inline_refs,
    parse_json_text,
    user_payload,
    validate_intent,
)
from app.intent.schema import IntentUpdate
from app.llm.base import run_blocking_with_deadline

# Bedrock calls are blocking (boto3); they run here so the caller can stop waiting at the turn deadline.
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="bedrock")

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
        self._deadline_seconds = settings.llm_overall_deadline_seconds
        self._client = client or self._build_client(settings)

    @staticmethod
    def _build_client(settings: Settings) -> Any:
        try:
            session = boto3.Session(profile_name=settings.aws_profile or None, region_name=settings.aws_region)
        except ProfileNotFound as exc:
            raise LLMError(LLMErrorKind.NOT_CONFIGURED, "AWS profile not found") from exc
        # Socket timeouts never exceed the turn deadline, so an abandoned call cannot hang around for long.
        timeout = min(settings.bedrock_timeout_seconds, settings.llm_overall_deadline_seconds)
        config = Config(
            connect_timeout=timeout,
            read_timeout=timeout,
            retries={"max_attempts": settings.bedrock_max_retries + 1, "mode": "standard"},
        )
        return session.client("bedrock-runtime", config=config)

    def build_request(self, message: str, context: ExtractionContext) -> dict[str, Any]:
        return {
            "modelId": self._model_id,
            "system": [{"text": SYSTEM_PROMPT}],
            "messages": [{"role": "user", "content": [{"text": user_payload(message, context)}]}],
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
        deadline = context.deadline or Deadline(self._deadline_seconds)
        response = self._call(self.build_request(message, context), deadline)
        return parse_response(response)

    def ping(self) -> str:
        """Minimal live call used by scripts/check_bedrock.py."""
        response = self._call({
            "modelId": self._model_id,
            "messages": [{"role": "user", "content": [{"text": "Reply with the single word: ok"}]}],
            "inferenceConfig": {"maxTokens": 10, "temperature": 0},
        }, Deadline(self._deadline_seconds))
        blocks = response.get("output", {}).get("message", {}).get("content", [])
        return "".join(b.get("text", "") for b in blocks).strip()

    def _call(self, request: dict[str, Any], deadline: Deadline) -> dict[str, Any]:
        try:
            return run_blocking_with_deadline(lambda: self._client.converse(**request), deadline, _EXECUTOR)
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
        raw = parse_json_text("".join(b.get("text", "") for b in blocks))
    return validate_intent(raw)
