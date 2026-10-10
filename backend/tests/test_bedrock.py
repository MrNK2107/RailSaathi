"""Bedrock adapter tests. All AWS calls are stubbed; no live AWS access is needed."""

from unittest.mock import MagicMock

import boto3
import pytest
from botocore.exceptions import EndpointConnectionError, NoCredentialsError, ReadTimeoutError
from botocore.stub import ANY, Stubber

from app.config import Settings
from app.domain.enums import BudgetPriority
from app.intent.bedrock import TOOL_NAME, TOOL_SCHEMA, BedrockIntentProvider
from app.intent.extractor import IntentExtractor
from app.intent.llm import ExtractionContext, LLMError, LLMErrorKind
from app.intent.rules import RuleBasedExtractor

SETTINGS = Settings(_env_file=None, llm_provider="bedrock", aws_region="us-east-1",
                    bedrock_model_id="test-model-id-placeholder")
CTX = ExtractionContext(language="en", today_iso="2026-10-10", pending_field=None, captured_fields=[])


def _client():
    return boto3.client("bedrock-runtime", region_name="us-east-1",
                        aws_access_key_id="testing", aws_secret_access_key="testing")


def _tool_response(payload: dict) -> dict:
    return {
        "output": {"message": {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": "tu-1", "name": TOOL_NAME, "input": payload}}]}},
        "stopReason": "tool_use",
        "usage": {"inputTokens": 10, "outputTokens": 10, "totalTokens": 20},
        "metrics": {"latencyMs": 5},
    }


@pytest.fixture
def stubbed():
    client = _client()
    with Stubber(client) as stub:
        yield BedrockIntentProvider(SETTINGS, client=client), stub


def test_structured_tool_output_is_validated(stubbed):
    provider, stub = stubbed
    stub.add_response("converse", _tool_response({
        "intent": "provide_details", "destination_text": "Chennai", "date_text": "tomorrow",
        "arrival_deadline_text": "9 am", "budget_priority": "minimize_cost", "needs_add": ["assistance_requested"],
    }), {"modelId": "test-model-id-placeholder", "system": ANY, "messages": ANY,
         "toolConfig": ANY, "inferenceConfig": ANY})
    update = provider.extract_intent("reach Chennai before 9 am tomorrow, cheapest", CTX)
    assert update.destination_text == "Chennai"
    assert update.budget_priority is BudgetPriority.MINIMIZE_COST


def test_request_forces_tool_and_has_no_credentials(stubbed):
    provider, _ = stubbed
    req = provider.build_request("hi", CTX)
    assert req["toolConfig"]["toolChoice"] == {"tool": {"name": TOOL_NAME}}
    assert "$defs" not in str(TOOL_SCHEMA) and "$ref" not in str(TOOL_SCHEMA)
    assert "testing" not in str(req)


def test_invalid_model_output_rejected(stubbed):
    provider, stub = stubbed
    stub.add_response("converse", _tool_response({"passenger_count": "lots", "budget_priority": "free"}))
    with pytest.raises(LLMError) as err:
        provider.extract_intent("x", CTX)
    assert err.value.kind is LLMErrorKind.INVALID_OUTPUT


@pytest.mark.parametrize("code,kind", [
    ("AccessDeniedException", LLMErrorKind.ACCESS_DENIED),
    ("UnrecognizedClientException", LLMErrorKind.AUTH),
    ("ExpiredTokenException", LLMErrorKind.AUTH),
    ("ThrottlingException", LLMErrorKind.THROTTLED),
    ("ModelTimeoutException", LLMErrorKind.TIMEOUT),
    ("ModelErrorException", LLMErrorKind.MODEL_ERROR),
    ("ValidationException", LLMErrorKind.MODEL_ERROR),
    ("ResourceNotFoundException", LLMErrorKind.MODEL_ERROR),
])
def test_client_errors_are_mapped(stubbed, code, kind):
    provider, stub = stubbed
    stub.add_client_error("converse", service_error_code=code, http_status_code=400)
    with pytest.raises(LLMError) as err:
        provider.extract_intent("x", CTX)
    assert err.value.kind is kind


@pytest.mark.parametrize("exc,kind", [
    (NoCredentialsError(), LLMErrorKind.AUTH),
    (ReadTimeoutError(endpoint_url="https://bedrock"), LLMErrorKind.TIMEOUT),
    (EndpointConnectionError(endpoint_url="https://bedrock"), LLMErrorKind.TIMEOUT),
])
def test_transport_errors_are_mapped(exc, kind):
    client = MagicMock()
    client.converse.side_effect = exc
    with pytest.raises(LLMError) as err:
        BedrockIntentProvider(SETTINGS, client=client).extract_intent("x", CTX)
    assert err.value.kind is kind


def test_missing_configuration_raises_not_configured():
    with pytest.raises(LLMError) as err:
        BedrockIntentProvider(Settings(_env_file=None, llm_provider="bedrock"))
    assert err.value.kind is LLMErrorKind.NOT_CONFIGURED


# ---- orchestrator fallback ----------------------------------------------------

def test_extractor_falls_back_to_rules_and_pauses_on_access_denied(resolver):
    llm = MagicMock()
    llm.name = "bedrock"
    llm.extract_intent.side_effect = LLMError(LLMErrorKind.ACCESS_DENIED, "denied")
    extractor = IntentExtractor(RuleBasedExtractor(resolver), llm)
    first = extractor.extract("from Coimbatore to Chennai", CTX)
    assert first.source == "rules" and first.fallback_reason == "access_denied"
    assert first.update.origin_text == "Coimbatore"
    second = extractor.extract("tomorrow", CTX)
    assert second.fallback_reason.startswith("llm_paused")
    assert llm.extract_intent.call_count == 1
    assert extractor.llm_status["active"] is False


def test_extractor_throttling_does_not_pause(resolver):
    llm = MagicMock()
    llm.name = "bedrock"
    llm.extract_intent.side_effect = LLMError(LLMErrorKind.THROTTLED, "slow down")
    extractor = IntentExtractor(RuleBasedExtractor(resolver), llm)
    extractor.extract("to Chennai", CTX)
    extractor.extract("to Chennai", CTX)
    assert llm.extract_intent.call_count == 2


def test_extractor_uses_llm_when_available(resolver):
    from app.intent.schema import IntentUpdate
    llm = MagicMock()
    llm.name = "bedrock"
    llm.extract_intent.return_value = IntentUpdate(destination_text="Madurai")
    result = IntentExtractor(RuleBasedExtractor(resolver), llm).extract("Madurai poganum", CTX)
    assert result.source == "bedrock" and result.update.destination_text == "Madurai"


def test_extractor_without_llm(resolver):
    result = IntentExtractor(RuleBasedExtractor(resolver), None, "llm_not_configured").extract("to Salem", CTX)
    assert result.source == "rules" and result.fallback_reason == "llm_not_configured"


# ---- wiring and live-check helper ------------------------------------------------

def test_container_builds_bedrock_provider_without_network_when_configured():
    from app.container import build_llm
    llm, reason = build_llm(SETTINGS)
    assert reason is None and llm.name == "bedrock"


def test_container_falls_back_when_bedrock_selected_but_incomplete():
    from app.container import build_llm
    llm, reason = build_llm(Settings(_env_file=None, llm_provider="bedrock", aws_region="us-east-1"))
    assert llm is None and reason == "bedrock_not_configured"


def test_unknown_aws_profile_reported_as_not_configured():
    with pytest.raises(LLMError) as err:
        BedrockIntentProvider(Settings(_env_file=None, llm_provider="bedrock", aws_region="us-east-1",
                                       bedrock_model_id="m", aws_profile="does-not-exist-railsaathi"))
    assert err.value.kind is LLMErrorKind.NOT_CONFIGURED


def test_ping_returns_text(stubbed):
    provider, stub = stubbed
    stub.add_response("converse", {
        "output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}},
        "stopReason": "end_turn", "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
        "metrics": {"latencyMs": 1},
    })
    assert provider.ping() == "ok"


def test_plain_json_text_output_is_accepted(stubbed):
    provider, stub = stubbed
    stub.add_response("converse", {
        "output": {"message": {"role": "assistant", "content": [{"text": '{"destination_text": "Salem"}'}]}},
        "stopReason": "end_turn", "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
        "metrics": {"latencyMs": 1},
    })
    assert provider.extract_intent("x", CTX).destination_text == "Salem"


def test_rules_backfill_fields_the_llm_left_empty(resolver):
    """Regression: Claude returned arrival_deadline_text='9 AM tomorrow' with no date_text."""
    from app.intent.schema import IntentUpdate
    llm = MagicMock()
    llm.name = "bedrock"
    llm.extract_intent.return_value = IntentUpdate(
        destination_text="Chennai", arrival_deadline_text="9 AM tomorrow", deadline_strict=True)
    result = IntentExtractor(RuleBasedExtractor(resolver), llm).extract(
        "I need to reach Chennai before 9 AM tomorrow.", CTX)
    assert result.update.date_text == "tomorrow"
    assert result.update.arrival_deadline_text == "9 AM tomorrow"  # LLM value kept, never overridden
    assert result.source == "bedrock+rules"


def test_backfill_keeps_llm_values(resolver):
    from app.intent.extractor import backfill
    from app.intent.schema import IntentUpdate
    merged = backfill(IntentUpdate(destination_text="Madurai", passenger_count=3),
                      IntentUpdate(destination_text="Chennai", passenger_count=2, date_text="today"))
    assert (merged.destination_text, merged.passenger_count, merged.date_text) == ("Madurai", 3, "today")


def test_rules_own_date_anchor_policy(resolver):
    """Regression: Claude labelled 'tomorrow, must reach before 4 am' as a departure date."""
    from app.domain.enums import DateAnchor
    from app.intent.schema import IntentUpdate
    llm = MagicMock()
    llm.name = "bedrock"
    llm.extract_intent.return_value = IntentUpdate(
        destination_text="Chennai", date_text="tomorrow", date_anchor=DateAnchor.DEPARTURE,
        arrival_deadline_text="4 am", deadline_strict=True)
    result = IntentExtractor(RuleBasedExtractor(resolver), llm).extract(
        "from Coimbatore to Chennai tomorrow, must reach before 4 am, 1 passenger", CTX)
    assert result.update.date_anchor is DateAnchor.ARRIVAL
