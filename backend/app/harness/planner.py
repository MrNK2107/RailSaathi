"""Planner service: the conversation/workflow harness used by the API layer."""

import re
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta

from app.disruption.service import DisruptionError, DisruptionService
from app.domain.enums import FieldSource, Language, WorkflowStatus as S
from app.domain.journey import REQUIRED_FIELDS, JourneyDetails
from app.domain.state import ConfirmationRecord, SessionState
from app.domain.transitions import InvalidTransitionError
from app.harness.engine import Reply, WorkflowEngine, selected_recommendation
from app.harness.errors import PlannerError, safe_validation_errors
from app.harness.handoff import build_handoff
from app.harness.i18n import field_label, msg
from app.harness.merge import JourneyMerger, MergeResult, changed_fields
from app.intent.extractor import ExtractionResult, IntentExtractor
from app.intent.llm import Deadline, ExtractionContext
from app.intent.patterns import RE_RESTART
from app.intent.schema import IntentUpdate
from app.providers.errors import ProviderError
from app.providers.live_source import reason_for
from app.sessions.store import SessionExpiredError, SessionNotFoundError, SessionStore
from app.validation.validator import validate_journey

_ORDINALS = {"1": 0, "first": 0, "one": 0, "2": 1, "second": 1, "two": 1, "3": 2, "third": 2,
             "three": 2, "4": 3, "fourth": 3, "5": 4, "fifth": 4}


@dataclass
class PlannerResult:
    state: SessionState
    assistant_message: str
    extraction_source: str | None = None
    fallback_reason: str | None = None


class PlannerService:
    def __init__(self, engine: WorkflowEngine, store: SessionStore, extractor: IntentExtractor,
                 merger: JourneyMerger, disruption: DisruptionService, data_mode) -> None:
        self.engine = engine
        self.store = store
        self.extractor = extractor
        self.merger = merger
        self.disruption = disruption
        self.data_mode = data_mode

    # ---- session lifecycle ---------------------------------------------------
    def create_session(self, language: Language) -> PlannerResult:
        now = self.engine.clock.now()
        state = SessionState(session_id=str(uuid.uuid4()), language=language, data_mode=self.data_mode,
                             created_at=now, updated_at=now, missing_fields=list(_required()))
        self.store.create(state)
        self.engine.record(state, "session_created", to_status=state.status.value, language=language.value)
        return PlannerResult(state, msg(language, "help"))

    def get(self, session_id: str) -> SessionState:
        try:
            return self.store.get(session_id)
        except SessionNotFoundError as exc:
            raise PlannerError("session_not_found", "Session not found.") from exc
        except SessionExpiredError as exc:
            raise PlannerError("session_expired", "Session expired. Please start a new session.") from exc

    @contextmanager
    def _session(self, session_id: str):
        self.get(session_id)
        with self.store.lock(session_id):
            state = self.get(session_id)
            holder: dict = {"state": state}
            try:
                yield holder
            except InvalidTransitionError as exc:
                raise PlannerError("invalid_transition", str(exc)) from exc
            self.store.save(holder["state"].model_copy(update={"updated_at": self.engine.clock.now()}))

    # ---- conversation --------------------------------------------------------
    def handle_message(self, session_id: str, message: str, language: Language | None) -> PlannerResult:
        with self._session(session_id) as h:
            # One LLM budget for the whole turn, started once the session lock is held; the lock TTL is
            # validated (config.py) to outlive it.
            deadline = Deadline(self.engine.settings.llm_overall_deadline_seconds)
            state: SessionState = h["state"]
            if language and language != state.language:
                state = state.model_copy(update={"language": language})
            if state.status == S.CANCELLED and not _is_restart(message):
                h["state"] = state
                return PlannerResult(state, msg(state.language, "session_cancelled"))
            extraction = self._extract(state, message, deadline)
            try:
                reply = self._dispatch(state, extraction.update)
            except PlannerError as exc:
                if exc.code in ("invalid_transition", "session_not_found", "session_expired"):
                    raise
                reply = Reply(state, [exc.message])
            h["state"] = reply.state
            self.engine.record(reply.state, "message_processed", intent=extraction.update.intent,
                               extraction_source=extraction.source, fallback=extraction.fallback_reason)
            final = reply.state.model_copy(update={"extraction_source": extraction.source})
            h["state"] = final
            return PlannerResult(final, reply.text, extraction.source, extraction.fallback_reason)

    def _extract(self, state: SessionState, message: str, deadline: Deadline | None = None):
        update = self._candidate_choice(state, message)
        if update is not None:
            return ExtractionResult(update, "rules", None)
        ctx = ExtractionContext(language=state.language.value, today_iso=self.engine.clock.now().date().isoformat(),
                                pending_field=state.pending_question, captured_fields=_captured(state.journey),
                                deadline=deadline)
        return self.extractor.extract(message, ctx)

    @staticmethod
    def _candidate_choice(state: SessionState, message: str) -> IntentUpdate | None:
        field = state.pending_question
        ids = state.pending_candidates.get(field or "", [])
        token = re.sub(r"[^\w]", "", message.strip().lower().replace("the ", "").replace(" one", ""))
        if ids and token in _ORDINALS and _ORDINALS[token] < len(ids):
            return IntentUpdate(**{f"{field}_text": ids[_ORDINALS[token]]})
        return None

    def _dispatch(self, state: SessionState, u: IntentUpdate) -> Reply:
        lang = state.language
        if u.intent == "cancel":
            return self._cancel(state)
        if u.intent == "restart":
            return self._restart(state)
        if u.intent == "confirm" and not u.has_details():
            if state.status != S.AWAITING_CONFIRMATION:
                return Reply(state, [msg(lang, "need_selection")])
            return self._confirm(state, None)
        if u.intent == "select_option" and u.selected_option and state.recommendations:
            option_id = _option_from_choice(state, u.selected_option)
            if option_id is None:
                raise PlannerError("invalid_option", "That option number is not in the current recommendations.")
            return self._select(state, option_id)
        if u.intent in ("greeting", "help") and not u.has_details():
            return Reply(state, [msg(lang, "help")])
        return self._update_details(state, u)

    def _update_details(self, state: SessionState, u: IntentUpdate) -> Reply:
        merged = self.merger.merge(state.journey, u, self.engine.clock.now())
        corrected = _corrected_fields(state.journey, merged.changed)
        state = self._apply_merge(state, merged)
        prefix = [msg(state.language, "unsupported", items=", ".join(u.unsupported_requests))] if u.unsupported_requests else []
        if corrected:
            labels = ", ".join(field_label(state.language, f) for f in corrected)
            prefix.append(msg(state.language, "updated", fields=labels))
        nothing_new = not merged.changed and not merged.issues
        if nothing_new and state.status in (S.PRESENTING_RECOMMENDATIONS, S.AWAITING_CONFIRMATION):
            if u.intent != "request_recommendations":
                return Reply(state, prefix + [msg(state.language, "nothing_changed")])
        force = u.intent in ("request_recommendations", "relax_constraint") or state.pending_question == "preferences"
        if state.pending_question == "preferences":
            state = state.model_copy(update={"asked_preferences": True})
        reply = self.engine.advance(state, merged.issues, force_search=force)
        return Reply(reply.state, prefix + reply.parts)

    def _apply_merge(self, state: SessionState, merged: MergeResult) -> SessionState:
        updates: dict = {"journey": merged.journey, "pending_candidates": merged.candidates}
        if merged.changed and state.recommendations is not None:
            updates.update(recommendations=None, selected_option_id=None, awaiting_confirmation=False,
                           reassessment=None)
            self.engine.record(state, "recommendations_invalidated", changed=merged.changed)
            if state.confirmation and not state.confirmation.superseded:
                updates["confirmation"] = state.confirmation.model_copy(update={"superseded": True})
        if merged.changed:
            self.engine.record(state, "journey_updated", fields=merged.changed)
        return state.model_copy(update=updates)

    # ---- direct actions (also used by the REST endpoints) ---------------------
    def patch_journey(self, session_id: str, values: dict, resolve_places: dict[str, str]) -> PlannerResult:
        with self._session(session_id) as h:
            state: SessionState = h["state"]
            if state.status == S.CANCELLED:
                raise PlannerError("session_cancelled", "Session is cancelled.")
            u = IntentUpdate(**{f"{k}_text": v for k, v in resolve_places.items()})
            merged = self.merger.merge(state.journey, u, self.engine.clock.now())
            try:
                journey = JourneyDetails.model_validate({**merged.journey.model_dump(), **values})
            except ValueError as exc:
                raise PlannerError("validation_failed", "Invalid journey values.", {"errors": safe_validation_errors(exc)}) from exc
            sources = {**journey.field_sources, **{k: FieldSource.EDITED for k in [*values, *resolve_places]}}
            journey = journey.model_copy(update={"field_sources": sources})
            merged = MergeResult(journey, merged.issues, merged.candidates, changed_fields(state.journey, journey))
            state = self._apply_merge(state, merged).model_copy(update={"asked_preferences": True})
            # A manual edit is an explicit request to (re)plan: recalculate as soon as details are valid.
            reply = self.engine.advance(state, merged.issues, force_search=True)
            h["state"] = reply.state
            return PlannerResult(reply.state, reply.text)

    def recommend(self, session_id: str) -> PlannerResult:
        with self._session(session_id) as h:
            state: SessionState = h["state"]
            if state.status == S.CANCELLED:
                raise PlannerError("session_cancelled", "Session is cancelled.")
            issues = validate_journey(state.journey, self.engine.clock.now(), self.engine.settings)
            if issues or state.missing_fields or any(getattr(state.journey, f) is None for f in _required()):
                raise PlannerError("not_ready", "Required journey details are missing or invalid.",
                                   {"missing_fields": [f for f in _required() if getattr(state.journey, f) is None],
                                    "validation_errors": [i.model_dump() for i in issues]})
            reply = self.engine.search(state.model_copy(update={"asked_preferences": True}))
            h["state"] = reply.state
            return PlannerResult(reply.state, reply.text)

    def select(self, session_id: str, option_id: str) -> PlannerResult:
        with self._session(session_id) as h:
            reply = self._select(h["state"], option_id)
            h["state"] = reply.state
            return PlannerResult(reply.state, reply.text)

    def _select(self, state: SessionState, option_id: str | None) -> Reply:
        if state.status not in (S.PRESENTING_RECOMMENDATIONS, S.AWAITING_CONFIRMATION) or not state.recommendations:
            raise PlannerError("no_recommendations", "There are no current recommendations to choose from.")
        rec = next((r for r in state.recommendations.recommendations if r.option.option_id == option_id), None)
        if rec is None:
            raise PlannerError("invalid_option", "That option is not in the current recommendations.")
        state = state.model_copy(update={"selected_option_id": option_id, "awaiting_confirmation": True})
        state = self.engine.move(state, S.AWAITING_CONFIRMATION, "option_selected", option_id=option_id)
        legs = " + ".join(f"{leg.train_no} {leg.train_name}" for leg in rec.option.legs)
        fare = f"₹{rec.total_fare:,.0f}" if rec.total_fare is not None else "fare not available"
        summary = f"{legs}, {rec.option.departure:%H:%M %d %b} → {rec.option.arrival:%H:%M %d %b}, {fare}"
        return Reply(state, [msg(state.language, "selected", summary=summary)])

    def confirm(self, session_id: str, option_id: str | None) -> PlannerResult:
        with self._session(session_id) as h:
            reply = self._confirm(h["state"], option_id)
            h["state"] = reply.state
            return PlannerResult(reply.state, reply.text)

    def _confirm(self, state: SessionState, option_id: str | None) -> Reply:
        if state.status == S.CONFIRMED and state.confirmation and not state.confirmation.superseded \
                and option_id in (None, state.confirmation.selected_option_id):
            return Reply(state, [msg(state.language, "confirmed", ref=state.confirmation.confirmation_id)])
        if state.status != S.AWAITING_CONFIRMATION:
            raise PlannerError("not_ready", "Select a recommended option before confirming.")
        if option_id and option_id != state.selected_option_id:
            raise PlannerError("invalid_option", "Confirmation does not match the selected option.")
        rec = selected_recommendation(state)
        self._ensure_fresh(state, rec)
        now = self.engine.clock.now()
        previous = state.confirmation.confirmation_id if state.confirmation else None
        conf_id = f"RSP-{uuid.uuid4().hex[:10].upper()}"
        handoff = build_handoff(state.session_id, conf_id, now, state.journey, rec, previous)
        record = ConfirmationRecord(confirmation_id=conf_id, confirmed_at=now, selected_option_id=rec.option.option_id,
                                    constraints_hash=state.journey.constraints_hash(), handoff=handoff)
        state = state.model_copy(update={"confirmation": record, "awaiting_confirmation": False, "reassessment": None})
        state = self.engine.move(state, S.CONFIRMED, "passenger_confirmed", confirmation_id=conf_id,
                                 option_id=rec.option.option_id, replaces=previous)
        return Reply(state, [msg(state.language, "confirmed", ref=conf_id)])

    def _ensure_fresh(self, state: SessionState, rec) -> None:
        rs = state.recommendations
        now = self.engine.clock.now()
        if rec is None or rs is None:
            raise PlannerError("invalid_option", "The selected option is no longer available.")
        if rs.constraints_hash != state.journey.constraints_hash():
            raise PlannerError("stale_recommendations", "Journey details changed; please review new recommendations.")
        if now - rs.computed_at > timedelta(minutes=self.engine.settings.recommendation_ttl_minutes):
            raise PlannerError("stale_recommendations", "Recommendations are out of date; please refresh them.")
        if rec.option.departure <= now or not all(c.status != "violated" for c in rec.hard_constraints):
            raise PlannerError("stale_recommendations", "The selected option no longer meets your requirements.")
        issues = validate_journey(state.journey, now, self.engine.settings)
        if issues:
            raise PlannerError("validation_failed", "Journey details are invalid.",
                               {"validation_errors": [i.model_dump() for i in issues]})

    def reassess(self, session_id: str, event_id: str | None) -> PlannerResult:
        with self._session(session_id) as h:
            state: SessionState = h["state"]
            allowed = (S.PRESENTING_RECOMMENDATIONS, S.AWAITING_CONFIRMATION, S.CONFIRMED)
            if state.status not in allowed or not state.recommendations:
                raise PlannerError("no_recommendations", "There is no current plan to reassess.")
            selected = state.selected_option_id or (state.confirmation.selected_option_id if state.confirmation else None)
            try:
                new_set, info = self.disruption.reassess(state.journey, state.recommendations, selected,
                                                         event_id, self.engine.clock.now(), state.language)
            except DisruptionError as exc:
                raise PlannerError(exc.code, str(exc)) from exc
            except ProviderError as exc:
                # Fixed reason by kind: the provider's own message can carry upstream (RailRadar) text.
                raise PlannerError("data_unavailable", f"Live train data is unavailable: {reason_for(exc)}",
                                   {"reason_kind": exc.kind.value}) from exc
            state = state.model_copy(update={"recommendations": new_set, "reassessment": info,
                                             "selected_option_id": None, "awaiting_confirmation": False})
            state = self.engine.move(state, S.PRESENTING_RECOMMENDATIONS, "reassessed", event_id=info.event_id,
                                     still_valid=info.original_still_valid)
            h["state"] = state
            text = info.summary if new_set.recommendations else f"{info.summary} {msg(state.language, 'no_options')}"
            return PlannerResult(state, text)

    def cancel(self, session_id: str) -> PlannerResult:
        with self._session(session_id) as h:
            reply = self._cancel(h["state"])
            h["state"] = reply.state
            return PlannerResult(reply.state, reply.text)

    def _cancel(self, state: SessionState) -> Reply:
        state = self.engine.move(state, S.CANCELLED, "passenger_cancelled")
        state = state.model_copy(update={"recommendations": None, "selected_option_id": None,
                                         "awaiting_confirmation": False, "pending_question": None,
                                         "reassessment": None})
        return Reply(state, [msg(state.language, "cancelled")])

    def _restart(self, state: SessionState) -> Reply:
        state = self._cancel(state).state
        state = self.engine.move(state, S.COLLECTING_DETAILS, "restart")
        fresh = state.model_copy(update={
            "journey": JourneyDetails(), "missing_fields": list(_required()), "validation_errors": [],
            "asked_preferences": False, "pending_candidates": {}, "confirmation": None,
            "pending_question": "destination",
        })
        return Reply(fresh, [msg(state.language, "restarted")])


def _required() -> tuple[str, ...]:
    return REQUIRED_FIELDS


_SILENT_FIELDS = {"date_anchor", "deadline_strict", "budget_strict", "class_strict", "transfer_strict"}


def _corrected_fields(before: JourneyDetails, changed: list[str]) -> list[str]:
    """Fields that replaced an existing value (corrections), not first-time captures."""
    return [f for f in changed if f not in _SILENT_FIELDS and getattr(before, f) not in (None, [], False)]


def _captured(journey: JourneyDetails) -> list[str]:
    data = journey.model_dump(exclude={"field_sources"})
    return [k for k, v in data.items() if v not in (None, [], False)]


def _is_restart(message: str) -> bool:
    return bool(RE_RESTART.search(message.lower()))


def _option_from_choice(state: SessionState, choice: str) -> str | None:
    recs = state.recommendations.recommendations
    if choice.isdigit():
        idx = int(choice) - 1
        return recs[idx].option.option_id if 0 <= idx < len(recs) else None
    return next((r.option.option_id for r in recs if choice in [lbl.value for lbl in r.labels]), None)
