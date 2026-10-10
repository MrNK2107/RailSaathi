"""Manually verify the live Bedrock connection (not part of the automated tests).

Usage (from backend/):  uv run python scripts/check_bedrock.py
Reads LLM settings from backend/.env and the standard AWS credential chain.
Prints no credentials.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.intent.bedrock import BedrockIntentProvider  # noqa: E402
from app.intent.llm import ExtractionContext, LLMError  # noqa: E402


def main() -> int:
    settings = Settings()
    print(f"LLM_PROVIDER={settings.llm_provider}  AWS_REGION={settings.aws_region or '(unset)'}  "
          f"BEDROCK_MODEL_ID={settings.bedrock_model_id or '(unset)'}  AWS_PROFILE={settings.aws_profile or '(default chain)'}")
    if not settings.bedrock_configured:
        print("Not configured: set LLM_PROVIDER=bedrock, AWS_REGION and BEDROCK_MODEL_ID in backend/.env")
        return 2
    try:
        provider = BedrockIntentProvider(settings)
        print(f"1/2 Basic Converse call... reply: {provider.ping()!r}")
        ctx = ExtractionContext(language="en", today_iso="", pending_field=None, captured_fields=[])
        update = provider.extract_intent(
            "I need to reach Chennai before 9 AM tomorrow from Coimbatore with my mother", ctx)
        print("2/2 Structured extraction OK:")
        print(update.model_dump_json(indent=2, exclude_defaults=True))
    except LLMError as err:
        print(f"FAILED: {err.kind.value} — {err}")
        hints = {
            "auth_failed": "Run `aws sts get-caller-identity` and fix your credentials / SSO login.",
            "access_denied": "Grant bedrock:InvokeModel for this model/inference profile and enable model access in the Bedrock console.",
            "model_error": "Check BEDROCK_MODEL_ID matches an ID/inference profile listed for this region.",
            "timeout": "Check network access to bedrock-runtime.<region>.amazonaws.com or raise BEDROCK_TIMEOUT_SECONDS.",
            "throttled": "Retry later or request a quota increase.",
        }
        print("Hint:", hints.get(err.kind.value, "See docs/BEDROCK_SETUP.md"))
        return 1
    print("Bedrock is working. Restart the backend to use it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
