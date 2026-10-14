"""
RailSathi AI — Deterministic Agent Controller

Orchestrates the LLM ↔ Tool execution loop with:
- Call budget enforcement
- Tool allowlisting and argument validation
- Evidence tracking and source provenance
- Structured trace logging
- Explicit failure and insufficient-evidence handling
"""

import logging
import time
import uuid
from typing import Any
from dataclasses import dataclass, field

from app.llm.base import ChatLLM, ChatMessage, Deadline, LLMError, ToolResult, tool_specs
from app.tools.registry import (
    ALL_TOOL_SCHEMAS,
    execute_any_tool as execute_tool,
    get_all_tool_names as get_tool_names,
    validate_any_tool_args as validate_tool_args,
)

DEFAULT_DEADLINE_SECONDS = 20.0

logger = logging.getLogger("railsaathi.controller")


@dataclass
class TraceEntry:
    """A single entry in the execution trace."""
    step: int
    event: str  # "llm_call", "tool_call", "tool_result", "error", "budget_exceeded"
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
    status: str  # "answered", "clarification_required", "insufficient_evidence",
                  # "service_unavailable", "execution_limit_reached", "error"
    sources: list[dict] = field(default_factory=list)
    trace_id: str = ""
    trace: list[dict] = field(default_factory=list)
    tool_calls_made: int = 0
    rounds_used: int = 0
    evidence_sufficient: bool = True


class AgentController:
    """
    Deterministic controller that manages the LLM ↔ tool lifecycle.

    Independent of the HTTP routes; talks to any `ChatLLM` (Gemini, the rule-based KeywordChatLLM, or a
    scripted MockChatLLM in tests). All LLM calls of the turn share one `Deadline`
    (Settings.llm_overall_deadline_seconds): no LLM call or retry outlives it. Tool execution is not covered by
    the deadline; tools rely on their own timeouts.
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
    ):
        self.llm = llm
        self.db_path = str(db_path)
        self.max_rounds = max_rounds
        self.max_tool_calls = max_tool_calls
        self.allowed_tools = set(allowed_tools or get_tool_names())
        self.tools = tool_specs(ALL_TOOL_SCHEMAS, self.allowed_tools)
        self.deadline_seconds = deadline_seconds
        self.goal_planner = goal_planner  # journey tool backend (the container's GoalPlanner)
        self.trace: list[TraceEntry] = []
        self.step_counter = 0

    def process_message(
        self,
        message: str,
        history: list[ChatMessage] | None = None,
    ) -> AgentResponse:
        """
        Process a passenger message through the full agent lifecycle.

        Args:
            message: The passenger's question.
            history: Optional conversation history (bounded).

        Returns:
            A structured AgentResponse.
        """
        trace_id = f"trace-{uuid.uuid4().hex[:12]}"
        deadline = Deadline(self.deadline_seconds)
        self.trace = []
        self.step_counter = 0

        # Validate input
        if not message or not message.strip():
            return AgentResponse(
                answer="Please provide a question about Indian Railways ticketing.",
                status="error",
                trace_id=trace_id,
            )

        if len(message) > 2000:
            return AgentResponse(
                answer="Your message is too long. Please keep questions under 2000 characters.",
                status="error",
                trace_id=trace_id,
            )

        # Build conversation contents
        contents: list[ChatMessage] = list(history) if history else []
        contents.append(ChatMessage(role="user", text=message))

        total_tool_calls = 0
        all_sources = {}
        evidence_sufficient = True

        try:
            for round_num in range(self.max_rounds):
                # Call LLM
                t0 = time.time()
                try:
                    response = self.llm.generate(contents, self.tools, deadline)
                except Exception as e:
                    kind = e.kind.value if isinstance(e, LLMError) else type(e).__name__
                    self._add_trace("error", detail=f"LLM call failed: {kind}")
                    logger.error("[%s] LLM error: %s", trace_id, kind)
                    return AgentResponse(
                        answer="I'm sorry, the AI service is currently unavailable. Please try again later.",
                        status="service_unavailable",
                        trace_id=trace_id,
                        trace=self._export_trace(),
                    )

                llm_duration = (time.time() - t0) * 1000
                self._add_trace("llm_call", duration_ms=llm_duration,
                                detail=f"Round {round_num + 1}")

                # Check if response contains function calls
                if not response.is_tool_call:
                    # Text response — we're done
                    text = response.text
                    if not text:
                        text = "I wasn't able to generate a response. Please try rephrasing your question."

                    return AgentResponse(
                        answer=text,
                        status="answered",
                        sources=list(all_sources.values()),
                        trace_id=trace_id,
                        trace=self._export_trace(),
                        tool_calls_made=total_tool_calls,
                        rounds_used=round_num + 1,
                        evidence_sufficient=evidence_sufficient,
                    )

                # Process function calls
                function_calls = [{"name": c.name, "args": dict(c.args), "id": c.id} for c in response.tool_calls]
                function_responses = []

                for fc in function_calls:
                    # Budget check
                    if total_tool_calls >= self.max_tool_calls:
                        self._add_trace("budget_exceeded",
                                        detail=f"Tool call budget ({self.max_tool_calls}) exhausted")
                        function_responses.append({
                            "name": fc["name"], "id": fc["id"],
                            "response": {
                                "error": "Tool call budget exhausted. Please provide a response based on evidence gathered so far."
                            },
                        })
                        continue

                    # Tool allowlist check
                    if fc["name"] not in self.allowed_tools:
                        self._add_trace("error", tool_name=fc["name"],
                                        detail=f"Tool not allowed: {fc['name']}")
                        function_responses.append({
                            "name": fc["name"], "id": fc["id"],
                            "response": {"error": f"Tool '{fc['name']}' is not registered."},
                        })
                        continue

                    # Validate arguments
                    is_valid, validation_error = validate_tool_args(fc["name"], fc["args"])
                    if not is_valid:
                        self._add_trace("error", tool_name=fc["name"],
                                        tool_args=self._redact_args(fc["args"]),
                                        detail=f"Invalid args: {validation_error}")
                        function_responses.append({
                            "name": fc["name"], "id": fc["id"],
                            "response": {"error": validation_error},
                        })
                        continue

                    # Execute tool
                    t0 = time.time()
                    result = execute_tool(fc["name"], fc["args"], self.db_path, self.goal_planner)
                    tool_duration = (time.time() - t0) * 1000
                    total_tool_calls += 1

                    # Collect sources
                    source_ids = []
                    raw_sources = list(result.get("sources", []))
                    if "journey_plan" in result and isinstance(result["journey_plan"], dict):
                        raw_sources.extend(result["journey_plan"].get("sources", []))

                    for source in raw_sources:
                        sid = source.get("source_id", "")
                        if sid:
                            all_sources[sid] = {
                                "source_id": sid,
                                "title": source.get("title", ""),
                                "url": source.get("source_url", ""),
                                "publisher": source.get("publisher", ""),
                                "last_verified_at": source.get("last_verified_at", ""),
                            }
                            source_ids.append(sid)

                    # Track evidence sufficiency
                    if not result.get("evidence_sufficient", True):
                        evidence_sufficient = False

                    self._add_trace(
                        "tool_call",
                        tool_name=fc["name"],
                        tool_args=self._redact_args(fc["args"]),
                        result_status=result.get("status", "unknown"),
                        source_ids=source_ids,
                        duration_ms=tool_duration,
                    )

                    function_responses.append({
                        "name": fc["name"], "id": fc["id"],
                        "response": result,
                    })

                # Add model's response and tool results to history
                contents.append(response.as_message())
                contents.append(ChatMessage(role="tool", tool_results=tuple(
                    ToolResult(name=fr["name"], response=fr["response"], call_id=fr.get("id"))
                    for fr in function_responses)))

            # If we exhausted rounds
            self._add_trace("budget_exceeded",
                            detail=f"Round budget ({self.max_rounds}) exhausted")

            # One final LLM call to get summary
            try:
                text = self.llm.generate(contents, self.tools, deadline).text
            except Exception:
                text = "I've gathered some information but reached my processing limit. Here's what I found so far."

            return AgentResponse(
                answer=text or "I reached my processing limit. Please try a more specific question.",
                status="execution_limit_reached",
                sources=list(all_sources.values()),
                trace_id=trace_id,
                trace=self._export_trace(),
                tool_calls_made=total_tool_calls,
                rounds_used=self.max_rounds,
                evidence_sufficient=evidence_sufficient,
            )

        except Exception as e:
            self._add_trace("error", detail=f"Unexpected error: {type(e).__name__}")
            logger.error("[%s] Controller error: %s", trace_id, type(e).__name__, exc_info=True)
            return AgentResponse(
                answer="An unexpected error occurred. Please try again.",
                status="error",
                trace_id=trace_id,
                trace=self._export_trace(),
            )

    def _add_trace(self, event: str, **kwargs) -> None:
        """Add a trace entry."""
        self.step_counter += 1
        entry = TraceEntry(step=self.step_counter, event=event, **kwargs)
        self.trace.append(entry)
        logger.debug(f"Trace step {self.step_counter}: {event} {kwargs}")

    def _export_trace(self) -> list[dict]:
        """Export trace entries as dicts for serialization."""
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
        """Redact sensitive arguments for logging."""
        redacted = {}
        for k, v in args.items():
            if isinstance(v, str) and len(v) > 100:
                redacted[k] = v[:100] + "...[truncated]"
            else:
                redacted[k] = v
        return redacted
