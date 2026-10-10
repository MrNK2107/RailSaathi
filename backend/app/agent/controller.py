"""
RailSathi AI — Deterministic Agent Controller

Orchestrates the LLM ↔ Tool execution loop with:
- Call budget enforcement
- Tool allowlisting and argument validation
- Evidence tracking and source provenance
- Structured trace logging
- Explicit failure and insufficient-evidence handling
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from google.genai import types

from app.tools.registry import (
    execute_any_tool as execute_tool,
    get_all_tool_names as get_tool_names,
    validate_any_tool_args as validate_tool_args,
)

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

    Independent of Flask routes — can be tested with a mock LLM client.
    """

    def __init__(
        self,
        llm_client,
        db_path: str,
        max_rounds: int = 4,
        max_tool_calls: int = 6,
        allowed_tools: list[str] | None = None,
    ):
        self.llm_client = llm_client
        self.db_path = str(db_path)
        self.max_rounds = max_rounds
        self.max_tool_calls = max_tool_calls
        self.allowed_tools = set(allowed_tools or get_tool_names())
        self.trace: list[TraceEntry] = []
        self.step_counter = 0

    def process_message(
        self,
        message: str,
        history: list[types.Content] | None = None,
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
        contents = list(history) if history else []
        contents.append(self.llm_client.build_user_content(message))

        total_tool_calls = 0
        all_sources = {}
        evidence_sufficient = True

        try:
            for round_num in range(self.max_rounds):
                # Call LLM
                t0 = time.time()
                try:
                    response = self.llm_client.generate(contents)
                except Exception as e:
                    self._add_trace("error", detail=f"LLM call failed: {type(e).__name__}: {str(e)}")
                    logger.error(f"[{trace_id}] LLM error: {e}")
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
                if not self.llm_client.is_function_call(response):
                    # Text response — we're done
                    text = self.llm_client.get_text(response)
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
                function_calls = self.llm_client.get_function_calls(response)
                function_responses = []

                for fc in function_calls:
                    # Budget check
                    if total_tool_calls >= self.max_tool_calls:
                        self._add_trace("budget_exceeded",
                                        detail=f"Tool call budget ({self.max_tool_calls}) exhausted")
                        function_responses.append({
                            "name": fc["name"],
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
                            "name": fc["name"],
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
                            "name": fc["name"],
                            "response": {"error": validation_error},
                        })
                        continue

                    # Execute tool
                    t0 = time.time()
                    result = execute_tool(fc["name"], fc["args"], self.db_path)
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
                        "name": fc["name"],
                        "response": result,
                    })

                # Add model's response and tool results to history
                model_content = self.llm_client.build_model_content(response)
                contents.append(model_content)

                tool_response_content = self.llm_client.build_function_response_content(
                    function_responses
                )
                contents.append(tool_response_content)

            # If we exhausted rounds
            self._add_trace("budget_exceeded",
                            detail=f"Round budget ({self.max_rounds}) exhausted")

            # One final LLM call to get summary
            try:
                final_response = self.llm_client.generate(contents)
                text = self.llm_client.get_text(final_response)
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
            logger.error(f"[{trace_id}] Controller error: {e}", exc_info=True)
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
