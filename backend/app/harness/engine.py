"""Deterministic workflow engine: transitions, clarification selection and search."""

from dataclasses import dataclass, field

from app.audit.log import AuditEvent, AuditLog
from app.clock import Clock
from app.config import Settings
from app.domain.enums import CheckStatus, DataMode, Language, Verification, WorkflowStatus as S
from app.domain.journey import REQUIRED_FIELDS
from app.domain.state import SessionState, ValidationIssue
from app.domain.transitions import ensure_transition
from app.harness.i18n import msg, provider_reason
from app.providers.errors import ProviderError
from app.ranking.recommender import Recommender
from app.stations.resolver import StationResolver
from app.validation.validator import missing_fields, validate_journey

QUESTION_ORDER = ("destination", "origin", "journey_date", "passenger_count")


@dataclass
class Reply:
    state: SessionState
    parts: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(p for p in self.parts if p)


class WorkflowEngine:
    def __init__(self, settings: Settings, clock: Clock, audit: AuditLog,
                 recommender: Recommender, resolver: StationResolver) -> None:
        self.settings = settings
        self.clock = clock
        self.audit = audit
        self.recommender = recommender
        self.resolver = resolver

    # ---- transitions ---------------------------------------------------------
    def move(self, state: SessionState, target: S, reason: str, **detail: object) -> SessionState:
        if state.status == target and target in (S.PRESENTING_RECOMMENDATIONS, S.COLLECTING_DETAILS,
                                                 S.NEEDS_CLARIFICATION, S.CANCELLED):
            return state
        ensure_transition(state.status, target)
        self.record(state, "transition", from_status=state.status.value, to_status=target.value,
                    reason=reason, **detail)
        return state.model_copy(update={"status": target, "updated_at": self.clock.now(),
                                        "version": state.version + 1})

    def record(self, state: SessionState, kind: str, from_status: str | None = None,
               to_status: str | None = None, **detail: object) -> None:
        self.audit.record(AuditEvent(at=self.clock.now(), session_id=state.session_id, type=kind,
                                     from_status=from_status, to_status=to_status, detail=dict(detail)))

    # ---- clarification / search ---------------------------------------------
    def advance(self, state: SessionState, merge_issues: list[ValidationIssue], force_search: bool = False) -> Reply:
        now = self.clock.now()
        issues = merge_issues + validate_journey(state.journey, now, self.settings)
        missing = missing_fields(state.journey)
        state = state.model_copy(update={"validation_errors": issues, "missing_fields": missing})
        if issues or missing:
            return self._clarify(state, issues, missing)
        if not force_search and not state.asked_preferences and not _has_priorities(state):
            state = self.move(state, S.COLLECTING_DETAILS, "ask_preferences")
            state = state.model_copy(update={"asked_preferences": True, "pending_question": "preferences"})
            return Reply(state, [msg(state.language, "ask_preferences")])
        return self.search(state)

    def _clarify(self, state: SessionState, issues: list[ValidationIssue], missing: list[str]) -> Reply:
        target = S.NEEDS_CLARIFICATION if issues else S.COLLECTING_DETAILS
        state = self.move(state, target, "clarify", missing=missing, issues=[i.code for i in issues])
        lang = state.language
        if issues:
            issue = issues[0]
            text = self._issue_text(issue, lang)
            pending = issue.field
        else:
            pending = next(f for f in QUESTION_ORDER if f in missing)
            text = msg(lang, f"ask_{pending}")
        return Reply(state.model_copy(update={"pending_question": pending}), [text])

    def _issue_text(self, issue: ValidationIssue, lang: Language) -> str:
        if issue.code == "ambiguous_station":
            options = ", ".join(f"{i + 1}) {c}" for i, c in enumerate(issue.candidates))
            return msg(lang, "ambiguous_station", query=issue.message.split('"')[1], options=options)
        if issue.code == "station_not_found":
            cities = ", ".join(sorted({p.label for p in self.resolver.all_places() if p.kind == "city"}))
            return msg(lang, "station_not_found", query=issue.message.split('"')[1], options=cities)
        follow_up = msg(lang, f"ask_{issue.field}") if issue.field in REQUIRED_FIELDS else ""
        return f"{msg(lang, 'field_issue', message=issue.message)} {follow_up}".strip()

    def search(self, state: SessionState) -> Reply:
        state = self.move(state, S.VALIDATING_REQUEST, "validated")
        state = self.move(state, S.SEARCHING_OPTIONS, "search")
        try:
            result = self.recommender.recommend(state.journey, self.clock.now(), state.language)
        except ProviderError as err:
            # Never present an outage as "no trains found", and never substitute other data.
            state = self.move(state, S.ERROR, "data_unavailable", provider_error=err.kind.value)
            return Reply(state.model_copy(update={"recommendations": None, "pending_question": None}),
                         [msg(state.language, "data_unavailable", reason=provider_reason(state.language, err))])
        base = {"recommendations": result, "pending_question": None, "selected_option_id": None,
                "awaiting_confirmation": False, "validation_errors": [], "missing_fields": []}
        if not result.recommendations:
            state = self.move(state.model_copy(update=base), S.NO_FEASIBLE_OPTIONS, "no_feasible",
                              considered=result.considered_count)
            return Reply(state, self._no_options_text(state))
        state = self.move(state.model_copy(update=base), S.PRESENTING_RECOMMENDATIONS, "recommendations",
                          eligible=result.eligible_count, options=[r.option.option_id for r in result.recommendations])
        return Reply(state, self._recs_text(state))

    def _recs_text(self, state: SessionState) -> list[str]:
        rs = state.recommendations
        lang = state.language
        parts = [msg(lang, _keyed("recs_ready", state), eligible=rs.eligible_count, considered=rs.considered_count,
                     source=_source(state))]
        parts += rs.notes
        # Only accessibility needs count here; other unverified items (e.g. missing fares) are not assistance.
        has_unverified = any(ns.status == Verification.UNKNOWN for r in rs.recommendations for ns in r.need_statuses)
        if has_unverified and state.journey.assistance_mandatory:
            parts.append(msg(lang, "assistance_mandatory_note"))
        elif has_unverified:
            parts.append(msg(lang, "assistance_note"))
        return parts

    def _no_options_text(self, state: SessionState) -> list[str]:
        rs = state.recommendations
        lang = state.language
        parts = [msg(lang, _keyed("no_options", state), source=_source(state))]
        reasons = sorted({r for e in rs.excluded for r in e.reasons})[:3]
        parts += reasons
        if rs.relax_suggestions:
            parts.append(msg(lang, "relax_offer", options="; ".join(s.message for s in rs.relax_suggestions)))
        return parts


def _source(state: SessionState) -> str:
    """The live data source named in the reply (e.g. "NTES (unofficial client)")."""
    rs = state.recommendations
    return rs.provenance.source if rs is not None and rs.provenance is not None else "the live data source"


def _keyed(key: str, state: SessionState) -> str:
    """Message variant that names the data source (demo vs live)."""
    return f"{key}_live" if state.data_mode == DataMode.LIVE else key


def _has_priorities(state: SessionState) -> bool:
    j = state.journey
    return any([j.budget_priority, j.arrival_deadline, j.departure_window, j.class_preference,
                j.budget_limit is not None, j.transfer_preference])


def selected_recommendation(state: SessionState):
    if not state.recommendations or not state.selected_option_id:
        return None
    return next((r for r in state.recommendations.recommendations
                 if r.option.option_id == state.selected_option_id), None)


def all_hard_constraints_ok(rec) -> bool:
    return all(c.status != CheckStatus.VIOLATED for c in rec.hard_constraints)
