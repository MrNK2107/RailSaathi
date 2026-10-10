"""Transparent weighted-utility scoring over eligible options.

score = sum(weight_k * component_k), every component normalised to [0, 1].
Weights are heuristics chosen for the prototype, not tuned or evaluated.
"""

from dataclasses import dataclass
from datetime import datetime

from app.domain.enums import ACCESSIBILITY_NEEDS, BudgetPriority, PassengerNeed, TransferPreference, Verification
from app.domain.journey import JourneyDetails, TimeWindow
from app.ranking.evaluate import Evaluation

BASE_WEIGHTS = {"cost": 0.30, "time": 0.30, "departure": 0.15, "transfers": 0.10, "preference": 0.15}
PRIORITY_WEIGHT = 0.80
DAYTIME_WINDOW = TimeWindow(start="06:00", end="18:00", label="daytime")
DECAY_HOURS = 6.0


@dataclass(frozen=True)
class Scored:
    evaluation: Evaluation
    score: float
    breakdown: dict[str, float]


def effective_window(journey: JourneyDetails) -> TimeWindow | None:
    if journey.departure_window:
        return journey.departure_window
    if PassengerNeed.DAYTIME_DEPARTURE in journey.passenger_needs:
        return DAYTIME_WINDOW
    return None


def weights_for(journey: JourneyDetails) -> dict[str, float]:
    w = dict(BASE_WEIGHTS)
    if journey.budget_priority == BudgetPriority.MINIMIZE_COST:
        w["cost"] = PRIORITY_WEIGHT
    elif journey.budget_priority == BudgetPriority.MINIMIZE_TIME:
        w["time"] = PRIORITY_WEIGHT
    if effective_window(journey) is None:
        w["departure"] = 0.0
    prefers_direct = journey.transfer_preference == TransferPreference.DIRECT_ONLY or any(
        n in journey.passenger_needs
        for n in (PassengerNeed.TRAVELLING_WITH_CHILDREN, PassengerNeed.TRAVELLING_WITH_ELDERLY)
    )
    if prefers_direct:
        w["transfers"] = 0.25
    total = sum(w.values())
    return {k: round(v / total, 4) for k, v in w.items()}


def _minmax(value: float, low: float, high: float) -> float:
    return 1.0 if high == low else (high - value) / (high - low)


def departure_score(departure: datetime, window: TimeWindow | None) -> float:
    if window is None:
        return 1.0
    minutes = departure.hour * 60 + departure.minute
    start = int(window.start[:2]) * 60 + int(window.start[3:])
    end = int(window.end[:2]) * 60 + int(window.end[3:])
    inside = start <= minutes <= end if start < end else (minutes >= start or minutes <= end)
    if inside:
        return 1.0
    gap = min(abs(minutes - start), abs(minutes - end), 1440 - abs(minutes - start), 1440 - abs(minutes - end))
    return max(0.0, 1.0 - gap / 60 / DECAY_HOURS)


def preference_score(ev: Evaluation, journey: JourneyDetails) -> float:
    parts: list[float] = []
    if journey.class_preference:
        parts.append(1.0 if ev.selected_class == journey.class_preference else 0.0)
    if ev.deadline_dt and not journey.deadline_strict:
        parts.append(1.0 if ev.option.arrival <= ev.deadline_dt else 0.0)
    if journey.budget_limit is not None and not journey.budget_strict and ev.total_fare is not None:
        parts.append(1.0 if ev.total_fare <= journey.budget_limit else 0.0)
    for ns in ev.need_statuses:
        if ns.need in ACCESSIBILITY_NEEDS:
            parts.append({Verification.VERIFIED_SUPPORTED: 1.0, Verification.UNKNOWN: 0.5}.get(ns.status, 0.0))
    return sum(parts) / len(parts) if parts else 1.0


def score_options(evaluations: list[Evaluation], journey: JourneyDetails) -> list[Scored]:
    if not evaluations:
        return []
    weights = weights_for(journey)
    window = effective_window(journey)
    fares = [e.total_fare for e in evaluations if e.total_fare is not None]
    durations = [e.option.duration_minutes for e in evaluations]
    scored: list[Scored] = []
    for ev in evaluations:
        comp = {
            "cost": _cost_score(ev.total_fare, fares),
            "time": _minmax(ev.option.duration_minutes, min(durations), max(durations)),
            "departure": departure_score(ev.option.departure, window),
            "transfers": 1.0 / (1 + ev.option.transfers),
            "preference": preference_score(ev, journey),
        }
        breakdown = {k: round(weights[k] * v, 4) for k, v in comp.items()}
        scored.append(Scored(ev, round(sum(breakdown.values()), 4), breakdown))
    return sorted(scored, key=lambda s: (-s.score, fare_key(s.evaluation), s.evaluation.option.option_id))


UNKNOWN_FARE_SCORE = 0.5  # neutral: an unknown fare is neither rewarded nor penalised


def _cost_score(total: float | None, known: list[float]) -> float:
    if total is None or not known:
        return UNKNOWN_FARE_SCORE
    return _minmax(total, min(known), max(known))


def fare_key(ev: Evaluation) -> float:
    """Sort key that places unknown fares after every known fare."""
    return ev.total_fare if ev.total_fare is not None else float("inf")
