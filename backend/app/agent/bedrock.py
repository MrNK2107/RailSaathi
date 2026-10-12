"""
RailSathi AI — AWS Bedrock LLM Client

Integrates AWS Bedrock (Claude 3.5 Sonnet / Haiku / Nova) using boto3 Converse API
with native tool calling and strict grounding against verified railway tools.
"""

import logging
from typing import Any
import boto3
from google.genai import types

from app.tools.registry import ALL_TOOL_SCHEMAS
from app.agent.llm import SYSTEM_INSTRUCTION

logger = logging.getLogger("railsaathi.bedrock")


def build_bedrock_tool_specs() -> list[dict[str, Any]]:
    """Convert ALL_TOOL_SCHEMAS to Bedrock toolConfig specification."""
    tools = []
    for name, schema in ALL_TOOL_SCHEMAS.items():
        tools.append({
            "toolSpec": {
                "name": name,
                "description": schema.get("description", ""),
                "inputSchema": {
                    "json": schema.get("parameters", {"type": "object", "properties": {}})
                }
            }
        })
    return tools


class BedrockResponse:
    """Standardized response matching AgentController expectations."""
    def __init__(self, text: str = "", function_calls: list[dict] | None = None):
        self.parts = []
        if function_calls:
            for fc in function_calls:
                call_mock = type("MockFunctionCall", (), {
                    "name": fc["name"],
                    "args": fc.get("args", {}),
                })()
                self.parts.append(type("MockPart", (), {
                    "function_call": call_mock,
                    "text": None,
                })())
        elif text:
            self.parts.append(type("MockPart", (), {
                "function_call": None,
                "text": text,
            })())

        content = types.Content(
            role="model",
            parts=[types.Part.from_text(text=text)] if text else [],
        )
        content.parts = self.parts
        self.candidates = [type("MockCandidate", (), {"content": content})()]


class BedrockClient:
    """AWS Bedrock runtime client with Converse API and tool calling."""

    def __init__(
        self,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        aws_session_token: str | None = None,
        region_name: str = "us-west-2",
        model_id: str = "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ):
        self.model_id = model_id
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.tools = build_bedrock_tool_specs()

        session_kwargs: dict[str, Any] = {
            "region_name": region_name,
            "aws_access_key_id": aws_access_key_id,
            "aws_secret_access_key": aws_secret_access_key,
        }
        if aws_session_token:
            session_kwargs["aws_session_token"] = aws_session_token

        session = boto3.Session(**session_kwargs)
        self.client = session.client("bedrock-runtime")
        logger.info(f"BedrockClient initialized: model={model_id} region={region_name}")

    def generate(self, contents: list[types.Content]) -> BedrockResponse:
        """Translate conversation contents to Bedrock Converse format and call model."""
        messages = []
        for c in contents:
            role = "user" if c.role == "user" else "assistant"
            content_blocks = []

            for p in c.parts:
                if getattr(p, "text", None):
                    content_blocks.append({"text": p.text})
                elif getattr(p, "function_response", None):
                    fr = p.function_response
                    content_blocks.append({
                        "toolResult": {
                            "toolUseId": f"tu_{fr.name[:15]}",
                            "content": [{"json": fr.response}],
                            "status": "success",
                        }
                    })

            if content_blocks:
                messages.append({"role": role, "content": content_blocks})

        if not messages:
            messages = [{"role": "user", "content": [{"text": "Hello"}]}]

        try:
            response = self.client.converse(
                modelId=self.model_id,
                messages=messages,
                system=[{"text": SYSTEM_INSTRUCTION}],
                inferenceConfig={
                    "temperature": self.temperature,
                    "maxTokens": self.max_tokens,
                },
                toolConfig={"tools": self.tools} if self.tools else None,
            )

            output_msg = response.get("output", {}).get("message", {})
            output_content = output_msg.get("content", [])

            function_calls = []
            text_parts = []

            for block in output_content:
                if "toolUse" in block:
                    tu = block["toolUse"]
                    function_calls.append({
                        "name": tu.get("name"),
                        "args": tu.get("input", {}),
                    })
                elif "text" in block:
                    text_parts.append(block["text"])

            if function_calls:
                return BedrockResponse(function_calls=function_calls)
            else:
                return BedrockResponse(text="\n".join(text_parts))

        except Exception as e:
            logger.error(f"Bedrock API call failed: {e}", exc_info=True)
            raise e

    def is_function_call(self, response: Any) -> bool:
        if not response.candidates:
            return False
        parts = response.candidates[0].content.parts
        return any(bool(getattr(p, "function_call", None)) for p in parts if p)

    def get_function_calls(self, response: Any) -> list[dict]:
        calls = []
        if not response.candidates:
            return calls
        for part in response.candidates[0].content.parts:
            if part and getattr(part, "function_call", None):
                fc = part.function_call
                calls.append({
                    "name": fc.name,
                    "args": dict(fc.args) if fc.args else {},
                })
        return calls

    def get_text(self, response: Any) -> str:
        if not response.candidates:
            return ""
        parts = response.candidates[0].content.parts
        text_parts = [part.text for part in parts if part and getattr(part, "text", None)]
        return "\n".join(text_parts)

    def build_user_content(self, message: str) -> types.Content:
        return types.Content(role="user", parts=[types.Part.from_text(text=message)])

    def build_model_content(self, response: Any) -> types.Content:
        if response.candidates:
            return response.candidates[0].content
        return types.Content(role="model", parts=[types.Part.from_text(text="")])

    def build_function_response_content(self, function_responses: list[dict]) -> types.Content:
        parts = []
        for fr in function_responses:
            parts.append(types.Part.from_function_response(
                name=fr["name"],
                response=fr["response"],
            ))
        return types.Content(role="user", parts=parts)
