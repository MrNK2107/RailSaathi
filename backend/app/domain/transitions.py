"""Legal workflow transitions. Anything not listed here is rejected."""

from app.domain.enums import WorkflowStatus as S

_EDITING = {S.COLLECTING_DETAILS, S.NEEDS_CLARIFICATION, S.VALIDATING_REQUEST}

LEGAL_TRANSITIONS: dict[S, frozenset[S]] = {
    S.COLLECTING_DETAILS: frozenset(_EDITING | {S.CANCELLED, S.ERROR}),
    S.NEEDS_CLARIFICATION: frozenset(_EDITING | {S.CANCELLED, S.ERROR}),
    S.VALIDATING_REQUEST: frozenset(_EDITING | {S.SEARCHING_OPTIONS, S.ERROR}),
    S.SEARCHING_OPTIONS: frozenset({S.PRESENTING_RECOMMENDATIONS, S.NO_FEASIBLE_OPTIONS, S.ERROR}),
    S.PRESENTING_RECOMMENDATIONS: frozenset(
        _EDITING | {S.PRESENTING_RECOMMENDATIONS, S.AWAITING_CONFIRMATION, S.CANCELLED, S.ERROR}
    ),
    S.AWAITING_CONFIRMATION: frozenset(
        _EDITING | {S.PRESENTING_RECOMMENDATIONS, S.CONFIRMED, S.CANCELLED, S.ERROR}
    ),
    # A confirmed plan can be reassessed (back to recommendations) or re-planned.
    S.CONFIRMED: frozenset(_EDITING | {S.PRESENTING_RECOMMENDATIONS, S.CANCELLED}),
    S.NO_FEASIBLE_OPTIONS: frozenset(_EDITING | {S.CANCELLED, S.ERROR}),
    S.CANCELLED: frozenset({S.COLLECTING_DETAILS}),
    # From error (e.g. live data unavailable) the passenger can retry or keep editing.
    S.ERROR: frozenset(_EDITING | {S.CANCELLED}),
}


class InvalidTransitionError(Exception):
    def __init__(self, current: S, target: S) -> None:
        super().__init__(f"Cannot move from '{current}' to '{target}'")
        self.current = current
        self.target = target


def ensure_transition(current: S, target: S) -> None:
    if target not in LEGAL_TRANSITIONS[current]:
        raise InvalidTransitionError(current, target)
