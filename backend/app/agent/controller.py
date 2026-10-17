"""
RailSathi AI — Deterministic Agent Controller

Orchestrates the LLM <-> tool loop with:
- Budgets: `max_rounds` and `max_tool_calls` (Settings.max_agent_rounds / max_tool_calls) plus one overall turn
  `Deadline` (Settings.llm_overall_deadline_seconds) shared by every LLM call of the turn.
- Tool allowlisting and argument validation.
- Prompt-injection mitigations (`agent/fencing.py`): every tool result reaches the model as a fenced, escaped,
  length-capped UNTRUSTED block; tool errors reach it only as typed codes; URLs in the final answer are filtered
  through a code-enforced allowlist.
- Evidence tracking, source citations and provenance.
- Honest degradation: any LLM failure (error, timeout, deadline) yields status "unavailable" with official links and
  provenance mode `unavailable`, never an invented answer and never a 500.
"""

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from app.agent.fencing import (
    ToolErrorCode,
    fence_tool_output,
    safe_tool_name,
    sanitize_output,
    sanitize_tool_result,
    tool_error,
    truncate_answer,
)
from app.domain.enums import DataMode
from app.domain.options import DataProvenance
from app.knowledge.seed_data import AS_OF as KNOWLEDGE_AS_OF
from app.llm.base import ChatLLM, ChatMessage, Deadline, LLMError, LLMErrorKind, ToolResult, tool_specs
from app.tools.registry import (
    ALL_TOOL_SCHEMAS,
    execute_any_tool as execute_tool,
    get_all_tool_names as get_tool_names,
    validate_any_tool_args as validate_tool_args,
)

DEFAULT_DEADLINE_SECONDS = 20.0
UNAVAILABLE_MESSAGE = "guidance unavailable"
UNAVAILABLE_ANSWER = ("AI ticketing guidance is unavailable right now. Please use the official Indian Railways and "
                      "IRCTC links below, or try again later.")
LIMIT_ANSWER = "I reached my processing limit for this question. Please ask a more specific question."
EMPTY_ANSWER = "I wasn't able to generate a response. Please try rephrasing your question."
LLM_FAILED_NOTE = "The AI guidance service could not answer; use the official links."
INCOMPLETE_NOTE = "Ticketing guidance could not be completed; use the official links."
GUIDANCE_NOTE = "AI guidance, not official. Verify current rules on the cited official pages before acting."


def _oldest_as_of(sources: list[dict]) -> date | None:
    dates = []
    for source in sources:
        try:
            dates.append(date.fromisoformat(str(source.get("as_of") or "")[:10]))
        except ValueError:
            continue
    return min(dates) if dates else None

_IR_STATIC = "https://www.indianrail.gov.in/enquiry/StaticPages/StaticEnquiry.jsp?StaticPage="
OFFICIAL_LINKS: list[dict[str, str]] = [
    {"title": "IRCTC e-ticketing (official booking site)", "url": "https://www.irctc.co.in/nget/train-search"},
    {"title": "PNR status (Indian Railways enquiry)",
     "url": "https://www.indianrail.gov.in/enquiry/PNR/PnrEnquiry.html?locale=en"},
    {"title": "Refund rules (Indian Railways enquiry)", "url": _IR_STATIC + "refund_Rules.html&locale=en"},
    {"title": "Tatkal scheme (Indian Railways enquiry)", "url": _IR_STATIC + "tatkal_Scheme.html&locale=en"},
]

logger = logging.getLogger("railsaathi.controller")


@dataclass
class TraceEntry:
    """A single entry in the execution trace."""
    step: int
    event: str  # "llm_call", "tool_call", "error", "budget_exceeded"
    tool_name: str | None = None
    tool_args: dict | None = None
    result_status: str | None = None
    source_ids: list[str] = field(default_factory=list)
    duration_ms: float | None = None
    detail: str | None = None


@dataclass
class AgentResponse:
    """The final structured response from the agent."""
    answer: str
    status: str  # "answered", "execution_limit_reached", "unavailable", "error"
    sources: list[dict] = field(default_factory=list)
    trace_id: str = ""
    trace: list[dict] = field(default_factory=list)
    tool_calls_made: int = 0
    rounds_used: int = 0
    evidence_sufficient: bool = True
    provenance: dict[str, Any] = field(default_factory=dict)
    links: list[dict[str, str]] = field(default_factory=list)  # official links, set when unavailable
    message: str | None = None  # short machine-friendly status message ("guidance unavailable")


class _TurnFailed(Exception):
    """An LLM call of this turn failed or the turn deadline passed."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


class AgentController:
    """
    Deterministic controller that manages the LLM <-> tool lifecycle.

    Independent of the HTTP routes; talks to any `ChatLLM` (Gemini, the rule-based KeywordChatLLM, or a scripted
    MockChatLLM in tests). All LLM calls of the turn share one `Deadline`: no LLM call or retry outlives it, and no
    new round starts after it has passed. Tool execution relies on each tool's own timeouts.
    """

    def __init__(
        self,
        llm: ChatLLM,
        db_path: str,
        max_rounds: int = 4,
        max_tool_calls: int = 6,
        allowed_tools: list[str] | None = None,
        deadline_seconds: float = DEFAULT_DEADLINE_SECONDS,
        goal_planner: Any = None,
        now: Callable[[], datetime] | None = None,
        deadline_clock: Callable[[], float] = time.monotonic,
    ):
        self.llm = llm
        self.db_path = str(db_path)
        self.max_rounds = max_rounds
        self.max_tool_calls = max_tool_calls
        self.allowed_tools = set(allowed_tools or get_tool_names())
        self.tools = tool_specs(ALL_TOOL_SCHEMAS, self.allowed_tools)
        self.deadline_seconds = deadline_seconds
        self.goal_planner = goal_planner  # journey tool backend (the container's GoalPlanner)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._deadline_clock = deadline_clock
        self.trace: list[TraceEntry] = []
        self.step_counter = 0
        self._answered_by: str | None = None  # `LLMTurn.model` of the latest turn (the model that answered)

    @property
    def _rule_based(self) -> bool:
        return getattr(self.llm, "name", "") == "rules"

    def process_message(self, message: str, history: list[ChatMessage] | None = None) -> AgentResponse:
        """Answer one passenger message. `history` holds earlier user/assistant text turns of the conversation."""
        trace_id = f"trace-{uuid.uuid4().hex[:12]}"
        deadline = Deadline(self.deadline_seconds, clock=self._deadline_clock)
        self.trace = []
        self.step_counter = 0
        self._answered_by = None

        if not message or not message.strip():
            return AgentResponse(answer="Please provide a question about Indian Railways ticketing.",
                                 status="error", trace_id=trace_id)
        if len(message) > 2000:
            return AgentResponse(answer="Your message is too long. Please keep questions under 2000 characters.",
                                 status="error", trace_id=trace_id)

        contents: list[ChatMessage] = list(history) if history else []
        contents.append(ChatMessage(role="user", text=message))
        state = {"tool_calls": 0, "sources": {}, "evidence_sufficient": True}

        try:
            for round_num in range(self.max_rounds):
                response = self._generate(contents, self.tools, deadline, round_num + 1)
                if not response.is_tool_call:
                    return self._final(response.text or EMPTY_ANSWER, "answered", trace_id, state, round_num + 1)
                results = [self._run_tool_call(call, state) for call in response.tool_calls]
                contents.append(response.as_message())
                contents.append(ChatMessage(role="tool", tool_results=tuple(results)))

            self._add_trace("budget_exceeded", detail=f"Round budget ({self.max_rounds}) exhausted")
            # One last call without tools so the model must answer from the evidence gathered so far.
            final = self._generate(contents, (), deadline, self.max_rounds + 1)
            return self._final(final.text or LIMIT_ANSWER, "execution_limit_reached", trace_id, state,
                               self.max_rounds)
        except _TurnFailed as failed:
            logger.warning("[%s] agent turn degraded: %s", trace_id, failed.kind)
            return self._unavailable(trace_id, state)
        except Exception as e:  # noqa: BLE001 - never a 500; degrade honestly
            self._add_trace("error", detail=f"Unexpected error: {type(e).__name__}")
            logger.error("[%s] Controller error: %s", trace_id, type(e).__name__, exc_info=True)
            return self._unavailable(trace_id, state, INCOMPLETE_NOTE)

    # --- steps ----------------------------------------------------------------------------------------------

    def _generate(self, contents: list[ChatMessage], tools, deadline: Deadline, round_no: int):
        if deadline.expired:
            self._add_trace("error", detail="Turn deadline exceeded")
            raise _TurnFailed(LLMErrorKind.TIMEOUT.value)
        t0 = time.time()
        try:
            response = self.llm.generate(contents, tools, deadline)
        except Exception as e:  # noqa: BLE001 - adapter errors are sanitised LLMErrors; anything else too
            kind = e.kind.value if isinstance(e, LLMError) else type(e).__name__
            self._add_trace("error", detail=f"LLM call failed: {kind}")
            raise _TurnFailed(kind) from e
        self._add_trace("llm_call", duration_ms=(time.time() - t0) * 1000, detail=f"Round {round_no}")
        self._answered_by = getattr(response, "model", None)
        return response

    def _run_tool_call(self, call, state: dict) -> ToolResult:
        name, args = call.name, dict(call.args or {})
        if state["tool_calls"] >= self.max_tool_calls:
            self._add_trace("budget_exceeded", detail=f"Tool call budget ({self.max_tool_calls}) exhausted")
            return self._tool_result(name, call.id, tool_error(ToolErrorCode.BUDGET_EXHAUSTED))
        if name not in self.allowed_tools:
            self._add_trace("error", tool_name=safe_tool_name(name), detail="Tool not allowed")
            return self._tool_result(name, call.id, tool_error(ToolErrorCode.UNKNOWN_TOOL))
        is_valid, _ = validate_tool_args(name, args)
        if not is_valid:
            self._add_trace("error", tool_name=name, tool_args=self._redact_args(args), detail="Invalid args")
            return self._tool_result(name, call.id, tool_error(ToolErrorCode.INVALID_ARGUMENTS))

        t0 = time.time()
        result = execute_tool(name, args, self.db_path, self.goal_planner)
        state["tool_calls"] += 1

        raw_sources = list(result.get("sources", []))
        if isinstance(result.get("journey_plan"), dict):
            raw_sources.extend(result["journey_plan"].get("sources", []))
        source_ids = []
        for source in raw_sources:
            sid = source.get("source_id", "") if isinstance(source, dict) else ""
            if sid:
                state["sources"][sid] = {
                    "source_id": sid,
                    "title": source.get("title", ""),
                    "url": source.get("source_url", ""),
                    "publisher": source.get("publisher", ""),
                    "last_verified_at": source.get("last_verified_at", ""),
                    "as_of": source.get("as_of") or source.get("last_verified_at", ""),
                }
                source_ids.append(sid)
        if not result.get("evidence_sufficient", True):
            state["evidence_sufficient"] = False

        self._add_trace("tool_call", tool_name=name, tool_args=self._redact_args(args),
                        result_status=result.get("status", "unknown"), source_ids=source_ids,
                        duration_ms=(time.time() - t0) * 1000)
        return self._tool_result(name, call.id, result)

    @staticmethod
    def _tool_result(name: str, call_id: str | None, result: dict) -> ToolResult:
        """The model sees only the fenced, sanitised payload; trusted rule code gets the structured result."""
        safe_name = safe_tool_name(name)
        fenced = fence_tool_output(safe_name, sanitize_tool_result(result))
        return ToolResult(name=safe_name, response={"untrusted_tool_output": fenced}, call_id=call_id, data=result)

    def _provenance(self, mode: DataMode, note: str, sources: list[dict] | None = None) -> dict[str, Any]:
        if mode is DataMode.UNAVAILABLE:
            return DataProvenance(mode=mode, source="RailSaathi ticketing guidance", as_of=self._now(),
                                  note=note).model_dump(mode="json")
        # The guidance comes from a static, curated knowledge base, never a live feed: as_of is the oldest cited
        # source's date (or the knowledge base's curation date when nothing was cited).
        as_of = _oldest_as_of(sources or []) or date.fromisoformat(KNOWLEDGE_AS_OF)
        curated = f"curated {KNOWLEDGE_AS_OF}"
        source = (f"RailSaathi rule-based guidance over the RailSaathi knowledge base ({curated})" if self._rule_based
                  else f"{self._answered_by or getattr(self.llm, 'name', 'LLM')} over the RailSaathi knowledge base "
                       f"({curated})")
        return DataProvenance(mode=mode, source=source, as_of=datetime(as_of.year, as_of.month, as_of.day,
                                                                       tzinfo=timezone.utc),
                              note=note).model_dump(mode="json")

    def _final(self, text: str, status: str, trace_id: str, state: dict, rounds: int) -> AgentResponse:
        # `cached`: answers are generated over a curated snapshot of official pages, so they are as old as that
        # snapshot; `fallback` when the rule-based agent answered instead of the LLM.
        mode = DataMode.FALLBACK if self._rule_based else DataMode.CACHED
        kb_note = f"From RailSaathi's curated knowledge base (sources as of {KNOWLEDGE_AS_OF}), not a live feed. "
        note = kb_note + GUIDANCE_NOTE if not self._rule_based else (
            "Rule-based guidance (the AI model is not configured). " + kb_note + GUIDANCE_NOTE)
        return AgentResponse(
            answer=sanitize_output(truncate_answer(text)),
            status=status,
            sources=list(state["sources"].values()),
            trace_id=trace_id,
            trace=self._export_trace(),
            tool_calls_made=state["tool_calls"],
            rounds_used=rounds,
            evidence_sufficient=state["evidence_sufficient"],
            provenance=self._provenance(mode, note, list(state["sources"].values())),
        )

    def _unavailable(self, trace_id: str, state: dict, note: str | None = None) -> AgentResponse:
        return AgentResponse(
            answer=UNAVAILABLE_ANSWER,
            status="unavailable",
            message=UNAVAILABLE_MESSAGE,
            links=[dict(link) for link in OFFICIAL_LINKS],
            trace_id=trace_id,
            trace=self._export_trace(),
            tool_calls_made=state["tool_calls"],
            evidence_sufficient=False,
            provenance=self._provenance(DataMode.UNAVAILABLE, note or LLM_FAILED_NOTE),
        )

    # --- trace ----------------------------------------------------------------------------------------------

    def _add_trace(self, event: str, **kwargs) -> None:
        self.step_counter += 1
        self.trace.append(TraceEntry(step=self.step_counter, event=event, **kwargs))
        logger.debug("Trace step %d: %s", self.step_counter, event)

    def _export_trace(self) -> list[dict]:
        return [
            {
                "step": t.step,
                "event": t.event,
                "tool_name": t.tool_name,
                "tool_args": t.tool_args,
                "result_status": t.result_status,
                "source_ids": t.source_ids,
                "duration_ms": round(t.duration_ms, 1) if t.duration_ms else None,
                "detail": t.detail,
            }
            for t in self.trace
        ]

    def _redact_args(self, args: dict) -> dict:
        redacted = {}
        for k, v in args.items():
            if isinstance(v, str) and len(v) > 100:
                redacted[k] = v[:100] + "...[truncated]"
            else:
                redacted[k] = v
        return redacted
