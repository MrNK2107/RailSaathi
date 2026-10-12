"""
RailSathi AI — Development Mock LLM Client

Enables local development, testing, and UI evaluation when GEMINI_API_KEY
is not yet set in the environment. Follows the exact GeminiClient protocol.
"""

import re
from typing import Any
try:
    from google.genai import types
except ImportError:
    class DummyPart:
        def __init__(self, text=None, function_call=None):
            self.text = text
            self.function_call = function_call
        @classmethod
        def from_text(cls, text=""):
            return cls(text=text)

    class DummyContent:
        def __init__(self, role="", parts=None):
            self.role = role
            self.parts = parts or []

    class DummyTypes:
        Part = DummyPart
        Content = DummyContent

    types = DummyTypes()


class DevMockResponse:
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


class DevMockGeminiClient:
    """
    Intelligent mock client for development mode.
    Dispatches tool calls based on user question keywords so the
    entire agent tool execution and evidence flow can be demonstrated.
    """

    def __init__(self, model_name: str = "mock-gemini-2.0-flash"):
        self.model_name = model_name

    def generate(self, contents: list[types.Content]) -> DevMockResponse:
        # Check if the last content is a function response from a tool execution
        last_content = contents[-1] if contents else None
        if last_content and last_content.parts:
            # Check if any part is a function response
            for part in last_content.parts:
                fn_resp = getattr(part, "function_response", None)
                if fn_resp:
                    resp_dict = fn_resp.response if hasattr(fn_resp, "response") else {}
                    # Synthesize final answer from tool evidence
                    return self._synthesize_answer(resp_dict, fn_resp.name)

        # Otherwise this is a user query: decide which tool to call
        user_text = ""
        for c in reversed(contents):
            if c.role == "user" and c.parts:
                for p in c.parts:
                    if getattr(p, "text", None):
                        user_text = p.text
                        break
            if user_text:
                break

        return self._plan_tool_call(user_text)

    def _plan_tool_call(self, text: str) -> DevMockResponse:
        t = text.lower()

        # Goal-Based Train Journey Planning queries
        if any(w in t for w in [
            "meeting", "interview", "appointment", "reach", "tidel park", "travelling from", "traveling from",
            "journey", "best train", "find a train", "find train", "train from", "train to", "exam", "reach by",
            "reach before", "buffer"
        ]):
            return DevMockResponse(function_calls=[{
                "name": "plan_goal_based_journey",
                "args": {"passenger_prompt": text},
            }])

        # Ticket class comparison
        classes_found = re.findall(r"\b(1a|2a|3a|3e|sl|cc|2s|ec|ea)\b", t)
        if len(classes_found) >= 2:
            return DevMockResponse(function_calls=[{
                "name": "explain_ticket_class",
                "args": {
                    "class_code": classes_found[0].upper(),
                    "comparison_class": classes_found[1].upper(),
                },
            }])
        elif len(classes_found) == 1:
            return DevMockResponse(function_calls=[{
                "name": "explain_ticket_class",
                "args": {"class_code": classes_found[0].upper()},
            }])

        # Reservation statuses
        status_match = re.search(r"\b(cnf|rac|wl|gnwl|rlwl|pqwl|waitlist|confirmed)\b", t)
        if status_match:
            code = status_match.group(1).upper()
            return DevMockResponse(function_calls=[{
                "name": "explain_reservation_status",
                "args": {"status_code": code, "question": text},
            }])

        # Booking process
        if any(w in t for w in ["how to book", "booking step", "counter", "irctc online", "book a train"]):
            channel = "counter" if "counter" in t else "irctc_online"
            return DevMockResponse(function_calls=[{
                "name": "get_booking_steps",
                "args": {"booking_channel": channel, "question": text},
            }])

        # Cancellation / Refund / Tatkal refund
        if any(w in t for w in ["cancel", "refund", "tdr", "deduction", "clerkage"]):
            return DevMockResponse(function_calls=[{
                "name": "get_cancellation_refund_guidance",
                "args": {"question": text},
            }])

        # Default fallback to knowledge search
        return DevMockResponse(function_calls=[{
            "name": "search_ticketing_guidance",
            "args": {"query": text},
        }])

    def _synthesize_answer(self, tool_result: dict, tool_name: str) -> DevMockResponse:
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
                return DevMockResponse(text=answer)
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
                return DevMockResponse(text=answer)
            p_text = res_p[0]["answer_text"] if res_p else f"Class details for {primary.get('class_code')}."

            if comp:
                res_c = comp.get("results", [])
                c_text = res_c[0]["answer_text"] if res_c else f"Class details for {comp.get('class_code')}."
                answer = (
                    f"### Comparison: {primary.get('class_code')} vs {comp.get('class_code')}\n\n"
                    f"**{primary.get('class_code')} Overview:**\n{p_text}\n\n"
                    f"**{comp.get('class_code')} Overview:**\n{c_text}\n\n"
                    f"**Key Conditions & Amenities:**\n"
                )
                for cond in (res_p[0].get("conditions", []) if res_p else []):
                    answer += f"- {cond}\n"
                answer += "\n*(Verified from official IRCTC classes documentation)*"
                return DevMockResponse(text=answer)
            else:
                answer = f"### {primary.get('class_code')} Ticket Class Guidance\n\n{p_text}\n\n"
                if res_p and res_p[0].get("conditions"):
                    answer += "**Key Travel Conditions:**\n"
                    for cond in res_p[0]["conditions"]:
                        answer += f"- {cond}\n"
                answer += "\n*(Verified from official IRCTC classes documentation)*"
                return DevMockResponse(text=answer)

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
                return DevMockResponse(text=answer)

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
            return DevMockResponse(text=answer)

        return DevMockResponse(text=(
            "I checked the official RailSathi knowledge base, but could not find specific rules matching your exact query. "
            "Please check current notices directly on the official IRCTC portal (https://www.irctc.co.in) or at a station reservation counter."
        ))

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
