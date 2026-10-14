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
            return self._synthesize_answer(first.response, first.name)
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
            plan = tool_result.get("journey_plan", {})
            req = plan.get("trip_requirements", {})
            best = plan.get("best_match")
            alts = plan.get("feasible_alternatives", [])
            infeasible = plan.get("infeasible_options", [])
            tradeoff = plan.get("tradeoff_explanation")

            if best:
                ts = best.get("train_service", {})
                answer = (
                    f"### 🎯 Recommended Journey Plan for Your Goal\n\n"
                    f"**Goal:** Reach **{req.get('destination_venue')}** by **{req.get('meeting_time')}** on **{req.get('meeting_date')}** "
                    f"from **{req.get('origin')}** with at least a **{req.get('required_arrival_buffer_minutes', 45)}-minute buffer**.\n\n"
                    f"#### 🏆 Best Feasible Match: {ts.get('train_name')} ({ts.get('train_number')})\n"
                    f"- **Departure:** {ts.get('departure_time')} from **{ts.get('origin_station_name')} ({ts.get('origin_station_code')})**\n"
                    f"- **Arrival at Station:** {ts.get('arrival_time')} at **{ts.get('destination_station_name')} ({ts.get('destination_station_code')})**\n"
                    f"- **Journey Duration:** {ts.get('duration_minutes', 0) // 60}h {ts.get('duration_minutes', 0) % 60}m\n"
                    f"- **Last-Mile Transfer:** ~{best.get('last_mile_duration_minutes')} mins ({best.get('last_mile_distance_km')} km by cab) to {best.get('last_mile_destination_venue')}\n"
                    f"- **Arrival Buffer at Venue:** **{best.get('actual_arrival_buffer_minutes')} minutes** before your meeting (Goal satisfied ✅)\n"
                    f"- **Recommended Class & Fare:** {best.get('recommended_class')} — ₹{best.get('recommended_fare', 'N/A')}\n\n"
                )

                if alts:
                    answer += "#### 🚆 Feasible Alternatives:\n"
                    for a in alts[:2]:
                        ats = a.get("train_service", {})
                        answer += (
                            f"- **{ats.get('train_name')} ({ats.get('train_number')}):** Departs {ats.get('departure_time')}, "
                            f"arrives {ats.get('arrival_time')} ({a.get('actual_arrival_buffer_minutes')}m buffer) | {a.get('recommended_class')} (₹{a.get('recommended_fare', 'N/A')})\n"
                        )
                    answer += "\n"

                if tradeoff:
                    answer += f"**⚠️ Evaluation Note:**\n{tradeoff}\n\n"

                if infeasible:
                    answer += "**❌ Options that do not meet your arrival deadline:**\n"
                    for inf in infeasible[:2]:
                        its = inf.get("train_service", {})
                        reasons = " ".join(inf.get("hard_constraint_violations", []))
                        answer += f"- **{its.get('train_name')} ({its.get('train_number')}):** {reasons}\n"
                    answer += "\n"

                if best.get("booking_handoff"):
                    bh = best["booking_handoff"]
                    answer += (
                        f"#### 🎫 Official Booking Handoff:\n"
                        f"Ready to book? Complete your reservation on the official portal:\n"
                        f"👉 [{bh.get('official_provider')}]({bh.get('booking_url')})\n\n"
                        f"*(Data source: Indian Railways NTES Timetable repository)*"
                    )
                return LLMTurn(text=answer)
            else:
                summary = plan.get("summary", "No direct train options found meeting the arrival deadline.")
                answer = f"### ⚠️ No Feasible Same-Day Trains Found\n\n{summary}\n\n"
                if tradeoff:
                    answer += f"**Recommendations & Alternatives:**\n{tradeoff}\n\n"
                if infeasible:
                    answer += "**Trains evaluated that missed deadline:**\n"
                    for inf in infeasible[:3]:
                        its = inf.get("train_service", {})
                        reasons = " ".join(inf.get("hard_constraint_violations", []))
                        answer += f"- **{its.get('train_name')} ({its.get('train_number')}):** {reasons}\n"
                return LLMTurn(text=answer)

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
