"""Intent extraction orchestrator: optional LLM first, deterministic rules as fallback."""

import logging
import time
from dataclasses import dataclass

from app.intent.llm import PERSISTENT_ERRORS, ExtractionContext, IntentLLM, LLMError
from app.intent.rules import RuleBasedExtractor
from app.intent.schema import IntentUpdate

log = logging.getLogger("railsaathi.intent")
PAUSE_SECONDS = 300


@dataclass(frozen=True)
class ExtractionResult:
    update: IntentUpdate
    source: str  # "bedrock" | "rules"
    fallback_reason: str | None = None


class IntentExtractor:
    def __init__(self, rules: RuleBasedExtractor, llm: IntentLLM | None = None,
                 llm_unavailable_reason: str | None = None) -> None:
        self._rules = rules
        self._llm = llm
        self._unavailable_reason = llm_unavailable_reason
        self._paused_until = 0.0
        self._last_error: str | None = None

    @property
    def llm_status(self) -> dict:
        if self._llm is None:
            return {"provider": None, "active": False, "reason": self._unavailable_reason or "not_configured"}
        paused = time.monotonic() < self._paused_until
        return {"provider": self._llm.name, "active": not paused, "last_error": self._last_error}

    def extract(self, message: str, context: ExtractionContext) -> ExtractionResult:
        if self._llm is None:
            return ExtractionResult(self._rules.extract(message, context.pending_field), "rules",
                                    self._unavailable_reason or "llm_not_configured")
        if time.monotonic() < self._paused_until:
            return ExtractionResult(self._rules.extract(message, context.pending_field), "rules",
                                    f"llm_paused:{self._last_error}")
        try:
            update = self._llm.extract_intent(message, context)
        except LLMError as err:
            self._last_error = err.kind.value
            if err.kind in PERSISTENT_ERRORS:
                self._paused_until = time.monotonic() + PAUSE_SECONDS
            log.warning("LLM extraction failed (%s); using rule-based fallback", err.kind.value)
            return ExtractionResult(self._rules.extract(message, context.pending_field), "rules", err.kind.value)
        self._last_error = None
        rules_update = self._rules.extract(message, context.pending_field)
        if not update.has_details() and update.intent in ("provide_details", "other"):
            if rules_update.has_details() or rules_update.intent != "provide_details":
                return ExtractionResult(rules_update, "rules", "llm_empty_result")
        filled = backfill(update, rules_update)
        source = self._llm.name if filled is update else f"{self._llm.name}+rules"
        return ExtractionResult(filled, source)


# Core fields the deterministic extractor may fill when the LLM left them empty.
BACKFILL_FIELDS = (
    "origin_text", "destination_text", "date_text", "date_anchor",
    "arrival_deadline_text", "deadline_strict", "passenger_count",
)


# Planning-policy fields decided by deterministic rules, not the LLM.
# date_anchor: a stated arrival deadline ("reach before 9 am tomorrow") means the date is the arrival day.
RULE_AUTHORITATIVE_FIELDS = ("date_anchor",)


def backfill(llm_update: IntentUpdate, rules_update: IntentUpdate) -> IntentUpdate:
    """Fill gaps in the LLM result from the rule-based result, and apply rule-owned policy fields.
    Otherwise never overrides an LLM value."""
    gaps = {
        name: getattr(rules_update, name)
        for name in BACKFILL_FIELDS
        if getattr(llm_update, name) is None and getattr(rules_update, name) is not None
    }
    policy = {
        name: getattr(rules_update, name)
        for name in RULE_AUTHORITATIVE_FIELDS
        if getattr(rules_update, name) is not None and getattr(rules_update, name) != getattr(llm_update, name)
    }
    changes = {**gaps, **policy}
    return llm_update.model_copy(update=changes) if changes else llm_update
