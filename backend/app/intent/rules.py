"""Deterministic rule-based intent extractor (always-available fallback)."""

import re

from app.domain.enums import BudgetPriority, DateAnchor, PassengerNeed, TransferPreference
from app.intent import patterns as P
from app.intent.schema import IntentUpdate
from app.stations.resolver import StationResolver
from app.validation.parsing import CLASS_ALIASES, UNSUPPORTED_CLASSES

_ORIGIN_BEFORE = re.compile(r"(from|leaving|departing|starting|boarding at|origin(?: is| to)?|source(?: is| to)?)\s*$")
_DEST_BEFORE = re.compile(r"(to|reach|reaching|arrive (?:at|in)|towards|for|till|destination(?: is| to)?|get to|be in)\s*$")
_ORIGIN_AFTER = re.compile(r"^\s*(இலிருந்து|லிருந்து|யிலிருந்து|ல\s*இருந்து|இருந்து|la\s*irundhu|le\s*irundhu|irundhu|se)\b|^(இலிருந்து|லிருந்து|யிலிருந்து|இருந்து)")
_DEST_AFTER = re.compile(r"^\s*(க்கு|கு|ukku|ku|kku)\b|^(க்கு|கு|வுக்கு|யுக்கு)")
_RAW_FROM = re.compile(r"\bfrom\s+([A-Z][a-zA-Z]{2,})")
_RAW_TO = re.compile(r"\b(?:to|reach)\s+([A-Z][a-zA-Z]{2,})")
_BARE_NUMBER = re.compile(r"^\s*" + P._NUM + r"\s*(?:passengers?|people|persons?|of us)?\s*[.!]?\s*$")
_SELECT_WORDS = {"first": "1", "second": "2", "third": "3", "cheapest": "lowest_cost", "lowest": "lowest_cost",
                 "fastest": "fastest", "quickest": "fastest", "best": "best_overall"}


def _num(token: str) -> int | None:
    token = token.strip().lower()
    return int(token) if token.isdigit() else P.NUMBER_WORDS.get(token)


class RuleBasedExtractor:
    name = "rules"

    def __init__(self, resolver: StationResolver) -> None:
        self._resolver = resolver

    def extract(self, text: str, pending_field: str | None = None) -> IntentUpdate:
        t = text.lower()
        data: dict = {"intent": self._intent(t), "is_correction": bool(P.RE_CORRECTION.search(t))}
        data.update(self._places(text, t))
        data.update(self._dates_times(t))
        data.update(self._passengers(t))
        data.update(self._needs(t))
        data.update(self._money_class_transfer(t))
        data.update(self._relax_and_unsupported(t))
        if m := P.RE_SELECT.search(t):
            data["selected_option"] = _SELECT_WORDS.get(m[1], m[1])
            data["intent"] = "select_option"
        update = IntentUpdate(**data)
        update = self._apply_pending(update, text, t, pending_field)
        if update.intent in ("greeting", "other", "help") and update.has_details():
            update = update.model_copy(update={"intent": "provide_details"})
        return update

    def _intent(self, t: str) -> str:
        for pattern, intent in (
            (P.RE_RESTART, "restart"), (P.RE_CANCEL, "cancel"), (P.RE_CONFIRM, "confirm"),
            (P.RE_SHOW, "request_recommendations"), (P.RE_GREETING, "greeting"), (P.RE_HELP, "help"),
        ):
            if pattern.search(t):
                return intent
        return "provide_details"

    def _places(self, text: str, t: str) -> dict:
        out: dict = {"unassigned_places": []}
        for m in self._resolver.find_in_text(text):
            before, after = t[max(0, m.start - 30):m.start], t[m.end:m.end + 14]
            if _ORIGIN_BEFORE.search(before) or _ORIGIN_AFTER.search(after):
                out.setdefault("origin_text", text[m.start:m.end])
            elif _DEST_BEFORE.search(before) or _DEST_AFTER.search(after):
                out.setdefault("destination_text", text[m.start:m.end])
            else:
                out["unassigned_places"].append(text[m.start:m.end])
        if re.search(r"\b(origin|source|starting point)\b", t) and "destination_text" in out and "origin_text" not in out:
            out["origin_text"] = out.pop("destination_text")
        known = {p.lower() for p in [out.get("origin_text"), out.get("destination_text"), *out["unassigned_places"]] if p}
        for key, rx in (("origin_text", _RAW_FROM), ("destination_text", _RAW_TO)):
            m = rx.search(text)
            if key not in out and m and m[1].lower() not in P.STOP_WORDS and m[1].lower() not in known:
                out[key] = m[1]
        return out

    def _dates_times(self, t: str) -> dict:
        out: dict = {}
        if m := P.RE_DATE.search(t):
            out["date_text"] = m[0]
        if m := P.RE_DEADLINE.search(t):
            out["arrival_deadline_text"] = m[1]
        elif m := P.RE_DEADLINE_TA.search(t):
            out["arrival_deadline_text"] = f"{m[1] or ''} {m[2]}".strip()
        if "arrival_deadline_text" in out:
            out["deadline_strict"] = not P.RE_SOFT.search(t)
        if "arrival_deadline_text" in out or P.RE_ARRIVAL_ANCHOR.search(t):
            out["date_anchor"] = DateAnchor.ARRIVAL
        elif "date_text" in out:
            out["date_anchor"] = DateAnchor.DEPARTURE
        if m := P.RE_DEPART_AFTER.search(t):
            out["departure_after_text"] = m[1]
        if m := P.RE_DEPART_BEFORE.search(t):
            out["departure_before_text"] = m[1]
        if m := P.RE_PERIOD.search(t):
            period = m[1] or m[2]
            out["departure_period"] = "night" if period == "overnight" else period
        return out

    def _passengers(self, t: str) -> dict:
        if m := (P.RE_COUNT.search(t) or P.RE_FAMILY.search(t)):
            return {"passenger_count": _num(m[1])}
        if P.RE_ALONE.search(t):
            return {"passenger_count": 1}
        if not re.search(r"\bwith\b|உடன்|கூட|oda|kooda", t):
            return {}
        companions = sum(len(re.findall(rf"(?<![\w-]){re.escape(r)}(?![\w-])", t)) for r in P.RELATIONS)
        companions += sum(n for word, n in P.PAIR_RELATIONS.items() if word in t)
        kids = P.RE_KIDS_COUNT.search(t)
        if kids:
            companions += _num(kids[1]) or 0
        elif P.NEED_PATTERNS[PassengerNeed.TRAVELLING_WITH_CHILDREN].search(t):
            return {}  # number of children unknown -> ask rather than guess
        return {"passenger_count": 1 + companions} if companions else {}

    def _needs(self, t: str) -> dict:
        needs = [need for need, rx in P.NEED_PATTERNS.items() if rx.search(t)]
        if PassengerNeed.WHEELCHAIR in needs and PassengerNeed.ASSISTANCE_REQUESTED not in needs:
            needs.append(PassengerNeed.ASSISTANCE_REQUESTED)
        out: dict = {"needs_add": needs}
        if P.RE_ASSIST_MANDATORY.search(t):
            out["assistance_mandatory"] = True
        return out

    def _money_class_transfer(self, t: str) -> dict:
        out: dict = {}
        if P.RE_COST.search(t):
            out["budget_priority"] = BudgetPriority.MINIMIZE_COST
        elif P.RE_TIME.search(t):
            out["budget_priority"] = BudgetPriority.MINIMIZE_TIME
        if m := P.RE_BUDGET.search(t):
            out["budget_limit"] = float(m[2].replace(",", ""))
            out["budget_strict"] = bool(P.RE_BUDGET_STRICT.search(t))
        for alias in sorted(CLASS_ALIASES, key=len, reverse=True):
            if re.search(rf"(?<![\w]){re.escape(alias)}(?![\w])", t):
                out["class_text"] = alias
                out["class_strict"] = bool(P.RE_STRICT_WORD.search(t))
                break
        if P.RE_ALLOW_TRANSFER.search(t):
            out["transfer_preference"] = TransferPreference.ALLOW
        elif P.RE_DIRECT.search(t):
            out["transfer_preference"] = TransferPreference.DIRECT_ONLY
            out["transfer_strict"] = not P.RE_DIRECT_SOFT.search(t)
        return out

    def _relax_and_unsupported(self, t: str) -> dict:
        out: dict = {"clear_fields": [], "unsupported_requests": []}
        for m in P.RE_RELAX.finditer(t):
            target = m[2]
            field = ("budget_limit" if "budget" in target or "price" in target else
                     "arrival_deadline" if target in ("deadline", "arrival time", "time limit") else
                     "class_preference" if target == "class" else
                     "departure_window" if target in ("window", "departure time") else "transfer_preference")
            out["clear_fields"].append(field)
        out["unsupported_requests"] = [label for key, label in P.UNSUPPORTED.items() if key in t]
        out["unsupported_requests"] += ["First AC (1A) class" for c in UNSUPPORTED_CLASSES if re.search(rf"\b{c}\b", t)][:1]
        return out

    def _apply_pending(self, u: IntentUpdate, text: str, t: str, pending: str | None) -> IntentUpdate:
        changes: dict = {}
        if u.clear_fields and u.intent == "provide_details":
            changes["intent"] = "relax_constraint"
            if "budget_limit" in u.clear_fields and u.budget_priority == BudgetPriority.MINIMIZE_COST:
                changes["budget_priority"] = None
                changes["budget_limit"] = None
        if pending in ("origin", "destination") and u.unassigned_places:
            changes[f"{pending}_text"] = u.unassigned_places[0]
            changes["unassigned_places"] = u.unassigned_places[1:]
        elif pending in ("origin", "destination") and not (u.origin_text or u.destination_text) \
                and re.fullmatch(r"\s*[\w .()-]{2,40}\s*", text) and not u.has_details():
            changes[f"{pending}_text"] = text.strip(" .")
        if pending == "passenger_count" and u.passenger_count is None and (m := _BARE_NUMBER.match(t)):
            changes["passenger_count"] = _num(m[1])
        if pending == "journey_date" and not u.date_text and len(text) <= 30 and u.intent == "provide_details":
            changes["date_text"] = text.strip()
        return u.model_copy(update=changes) if changes else u
