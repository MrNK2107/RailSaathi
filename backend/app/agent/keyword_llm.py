"""Rule-based `ChatLLM` used by the ticketing agent when no real LLM is configured (or LLM_PROVIDER=bedrock,
which has no chat adapter). It picks a deterministic tool from keywords in the question and phrases the tool's
grounded result; it never invents facts beyond what the tools return. Also used in tests and local development.
"""

import re
from collections.abc import Sequence

from app.llm.base import ChatMessage, Deadline, LLMTurn, ToolCall, ToolSpec


def _call(name: str, args: dict) -> LLMTurn:
    return LLMTurn(tool_calls=(ToolCall(name=name, args=args),))


class KeywordChatLLM:
    """Deterministic keyword router: user question -> one tool call; tool result -> formatted answer."""

    name = "rules"

    def generate(self, messages: Sequence[ChatMessage], tools: Sequence[ToolSpec], deadline: Deadline) -> LLMTurn:
        last = messages[-1] if messages else None
        if last is not None and last.role == "tool" and last.tool_results:
            first = last.tool_results[0]
            return self._synthesize_answer(first.data if first.data is not None else first.response, first.name)
        user_text = next((m.text for m in reversed(messages) if m.role == "user" and m.text), "")
        return self._plan_tool_call(user_text)

    def _plan_tool_call(self, text: str) -> LLMTurn:
        t = text.lower()

        # Goal-Based Train Journey Planning queries
        if any(w in t for w in [
            "meeting", "interview", "appointment", "reach", "tidel park", "travelling from", "traveling from",
            "journey", "best train", "find a train", "find train", "train from", "train to", "exam", "reach by",
            "reach before", "buffer"
        ]):
            return _call(
                name="plan_goal_based_journey",
                args={"passenger_prompt": text},
            )

        # Ticket class comparison
        classes_found = re.findall(r"\b(1a|2a|3a|3e|sl|cc|2s|ec|ea)\b", t)
        if len(classes_found) >= 2:
            return _call(
                name="explain_ticket_class",
                args={
                    "class_code": classes_found[0].upper(),
                    "comparison_class": classes_found[1].upper(),
                },
            )
        elif len(classes_found) == 1:
            return _call(
                name="explain_ticket_class",
                args={"class_code": classes_found[0].upper()},
            )

        # Reservation statuses
        status_match = re.search(r"\b(cnf|rac|wl|gnwl|rlwl|pqwl|waitlist|confirmed)\b", t)
        if status_match:
            code = status_match.group(1).upper()
            return _call(
                name="explain_reservation_status",
                args={"status_code": code, "question": text},
            )

        # Booking process
        if any(w in t for w in ["how to book", "booking step", "counter", "irctc online", "book a train"]):
            channel = "counter" if "counter" in t else "irctc_online"
            return _call(
                name="get_booking_steps",
                args={"booking_channel": channel, "question": text},
            )

        # Cancellation / Refund / Tatkal refund
        if any(w in t for w in ["cancel", "refund", "tdr", "deduction", "clerkage"]):
            return _call(
                name="get_cancellation_refund_guidance",
                args={"question": text},
            )

        # Default fallback to knowledge search
        return _call(
            name="search_ticketing_guidance",
            args={"query": text},
        )

    def _synthesize_answer(self, tool_result: dict, tool_name: str) -> LLMTurn:
        """Synthesize a structured guidance answer using evidence from tool result."""
        # Case 0: plan_goal_based_journey
        if tool_name == "plan_goal_based_journey":
            return LLMTurn(text=_journey_answer(tool_result))

        # Case 2: explain_reservation_status
        if tool_name == "explain_reservation_status":
            results = tool_result.get("results", [])
            code = tool_result.get("status_code", "")
            if results:
                answer = f"### Reservation Status: {code}\n\n{results[0]['answer_text']}\n\n"
                if results[0].get("conditions"):
                    answer += "**Important Rules & Boarding Rights:**\n"
                    for c in results[0]["conditions"]:
                        answer += f"- {c}\n"
                answer += "\n*(Verified from official Indian Railways Reservation Rules)*"
                return LLMTurn(text=answer)

        # Case 3: general search / booking / refund
        results = tool_result.get("results", [])
        if results:
            first = results[0]
            answer = f"### Official Ticketing Guidance\n\n{first['answer_text']}\n\n"
            if first.get("conditions"):
                answer += "**Applicable Conditions & Rules:**\n"
                for c in first["conditions"]:
                    answer += f"- {c}\n"
            if first.get("exceptions"):
                answer += "\n**Exceptions / Specific Notes:**\n"
                for ex in first["exceptions"]:
                    answer += f"- {ex}\n"
            answer += "\n*(Information retrieved from verified Indian Railways / IRCTC repository)*"
            return LLMTurn(text=answer)

        return LLMTurn(text=(
            "I checked the official RailSathi knowledge base, but could not find specific rules matching your exact query. "
            "Please check current notices directly on the official IRCTC portal (https://www.irctc.co.in) or at a station reservation counter."
        ))


NL = "\n"


def _hhmm(iso: str | None) -> str:
    return iso[11:16] if isinstance(iso, str) and len(iso) >= 16 else "?"


def _train_line(ev: dict) -> str:
    cand = ev.get("candidate", {})
    return (f"**{cand.get('train_number')} {cand.get('train_name')}**: departs {cand.get('origin_code')} "
            f"{_hhmm(cand.get('departure'))}, arrives {cand.get('destination_code')} {_hhmm(cand.get('arrival'))}")


def _journey_answer(tool_result: dict) -> str:
    """Phrase a goal plan from the planner's result only (provider trains, provenance, buffers)."""
    if tool_result.get("status") != "success":
        return f"I could not plan this journey: {tool_result.get('error', 'the planner failed')}"
    plan = tool_result.get("journey_plan", {})
    provenance = plan.get("provenance") or {}
    mode = provenance.get("mode", "unknown")
    # The demo mode is local/dev only and is not labelled in the UI; every other mode is named.
    label = "" if mode == "demo" else f" ({mode})"
    source = f"*Data: {provenance.get('source', 'unknown source')}{label}. {provenance.get('note', '')}*"
    if plan.get("status") in ("clarification_required", "provider_unavailable"):
        return plan.get("summary", "") + NL + NL + source
    req = plan.get("trip_requirements") or {}
    best = plan.get("best_match")
    parts = ["### Journey plan", plan.get("summary", "")]
    if best:
        lm = best.get("last_mile_duration_minutes")
        lines = ["#### Best match", f"- {_train_line(best)}",
                 f"- Last mile: {f'about {lm} min by cab' if lm is not None else 'not estimated'}",
                 f"- Estimated buffer before your {req.get('meeting_time')} meeting: "
                 f"{best.get('actual_arrival_buffer_minutes')} min"]
        fare = best.get("recommended_fare")
        if best.get("recommended_class"):
            lines.append(f"- Class: {best['recommended_class']}" + (f" (listed fare ₹{fare:.0f})" if fare else ""))
        parts.append(NL.join(lines))
    alts = plan.get("feasible_alternatives", [])
    if alts:
        parts.append(NL.join(["#### Alternatives", *(f"- {_train_line(a)}" for a in alts[:2])]))
    if plan.get("tradeoff_explanation"):
        parts.append(f"**Note:** {plan['tradeoff_explanation']}")
    infeasible = plan.get("infeasible_options", [])
    if infeasible and not best:
        parts.append(NL.join(["#### Trains that miss the deadline", *(
            f"- {_train_line(i)}: {' '.join(i.get('hard_constraint_violations', []))}" for i in infeasible[:3])]))
    handoff = (best or {}).get("booking_handoff")
    if handoff:
        parts.append(f"Book on the official portal: [{handoff.get('official_provider')}]({handoff.get('booking_url')})")
    parts.append(source)
    return (NL + NL).join(p for p in parts if p)
