"""Recommendation service: search -> hard-constraint filter -> score -> categorise -> explain."""

from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta

from app.domain.enums import BudgetPriority, DataMode, DateAnchor, Language, RecommendationCategory as Cat
from app.domain.journey import JourneyDetails
from app.domain.options import DataProvenance, ExcludedOption, JourneyOption, Recommendation, RecommendationSet, RelaxSuggestion
from app.providers.base import JourneyProvider
from app.ranking.evaluate import Evaluation, evaluate_option
from app.ranking.explain import explain
from app.ranking.scoring import Scored, fare_key, score_options

OptionTransform = Callable[[list[JourneyOption]], list[JourneyOption]]

RELAXABLE = {
    "arrival_deadline": "Allow arrival after your deadline",
    "budget_limit": "Raise or remove your maximum budget",
    "travel_class": "Accept other travel classes",
    "direct_only": "Allow journeys with one change of train",
    "mandatory_assistance": "Consider journeys where assistance is not listed",
}
MAX_CARDS = 3
BOOKING_LIMITATION = "Seat availability is not checked and no ticket is booked."


class Recommender:
    def __init__(self, provider: JourneyProvider, min_transfer_minutes: int) -> None:
        self._provider = provider
        self._min_transfer = min_transfer_minutes

    def search(self, journey: JourneyDetails) -> list[JourneyOption]:
        if not (journey.origin and journey.destination and journey.journey_date):
            raise ValueError("Search requires origin, destination and journey date")
        dates = [journey.journey_date]
        if journey.date_anchor == DateAnchor.ARRIVAL:
            dates = [journey.journey_date - timedelta(days=1), journey.journey_date]
        options = self._provider.search(journey.origin.station_codes, journey.destination.station_codes, dates)
        if journey.date_anchor == DateAnchor.ARRIVAL:
            options = [o for o in options if o.arrival.date() == journey.journey_date]
        return options

    def recommend(
        self, journey: JourneyDetails, now: datetime, lang: Language,
        transform: OptionTransform | None = None,
    ) -> RecommendationSet:
        options = self.search(journey)
        if transform:
            options = transform(options)
        evaluations = [evaluate_option(o, journey, now, self._provider, self._min_transfer) for o in options]
        eligible = [e for e in evaluations if e.eligible]
        excluded = [e for e in evaluations if not e.eligible]
        scored = score_options(eligible, journey)
        recs = self._build_cards(scored, journey, lang)
        return RecommendationSet(
            constraints_hash=journey.constraints_hash(),
            computed_at=now,
            considered_count=len(evaluations),
            eligible_count=len(eligible),
            recommendations=recs,
            excluded=[_excluded(e) for e in excluded],
            relax_suggestions=_relax(excluded) if not eligible else [],
            notes=_notes(eligible, excluded) + _fare_notes(evaluations, journey),
            limitations=_limitations(eligible, self._provider.provenance()),
            provenance=_set_provenance(options, self._provider.provenance()),
        )

    def _build_cards(self, scored: list[Scored], journey: JourneyDetails, lang: Language) -> list[Recommendation]:
        if not scored:
            return []
        pool = [s for s in scored if s.evaluation.fully_compliant] or scored
        picks = {
            Cat.BEST_OVERALL: pool[0],
            Cat.FASTEST: min(pool, key=lambda s: (s.evaluation.option.duration_minutes, fare_key(s.evaluation))),
        }
        priced = [s for s in pool if s.evaluation.total_fare is not None]
        if priced:  # never label an option "Lowest cost" without a known fare
            picks[Cat.LOWEST_COST] = min(priced, key=lambda s: (s.evaluation.total_fare, s.evaluation.option.duration_minutes))
        picks = {cat: picks[cat] for cat in (Cat.BEST_OVERALL, Cat.LOWEST_COST, Cat.FASTEST) if cat in picks}
        labels: dict[str, list[Cat]] = {}
        for cat, s in picks.items():
            labels.setdefault(s.evaluation.option.option_id, []).append(cat)
        # When categories collapse onto one option (e.g. no fares), show the next-best eligible
        # options so the passenger still sees up to MAX_CARDS real choices. They get no category label.
        for s in pool:
            if len(labels) >= MAX_CARDS:
                break
            labels.setdefault(s.evaluation.option.option_id, [])
        rank = {s.evaluation.option.option_id: i + 1 for i, s in enumerate(scored)}
        known = [s.evaluation.total_fare for s in scored if s.evaluation.total_fare is not None]
        cheapest = min(known) if known else None
        fastest = min(s.evaluation.option.duration_minutes for s in scored)
        cards: list[Recommendation] = []
        for option_id, cats in labels.items():
            s = next(x for x in scored if x.evaluation.option.option_id == option_id)
            cards.append(_card(s, cats, rank[option_id], journey, lang, cheapest, fastest))
        return cards


def _card(s: Scored, cats: list[Cat], rank: int, journey: JourneyDetails,
          lang: Language, cheapest: float | None, fastest: int) -> Recommendation:
    ev = s.evaluation
    text, matches, tradeoffs, unverified = explain(ev, cats, journey, lang, cheapest, fastest)
    return Recommendation(
        option=ev.option, labels=cats, rank=rank, score=s.score, score_breakdown=s.breakdown,
        selected_class=ev.selected_class, fare_per_passenger=ev.fare_per_passenger,
        total_fare=ev.total_fare, fully_compliant=ev.fully_compliant, hard_constraints=ev.checks,
        need_statuses=ev.need_statuses, preference_matches=matches, tradeoffs=tradeoffs,
        unverified=unverified, explanation=text,
    )


def _summary(ev: Evaluation) -> str:
    o = ev.option
    trains = " + ".join(f"{leg.train_no} {leg.train_name}" for leg in o.legs)
    fare = f"₹{ev.total_fare:,.0f} ({ev.selected_class})" if ev.total_fare is not None else "fare not available"
    return f"{trains}: {o.departure:%H:%M %d %b} → {o.arrival:%H:%M %d %b}, {fare}"


def _excluded(ev: Evaluation) -> ExcludedOption:
    return ExcludedOption(option_id=ev.option.option_id, summary=_summary(ev),
                          reasons=[c.detail for c in ev.violations])


def _relax(excluded: list[Evaluation]) -> list[RelaxSuggestion]:
    counts = Counter(c.name for e in excluded for c in e.violations if c.name in RELAXABLE)
    return [RelaxSuggestion(constraint=name, excluded_count=n, message=RELAXABLE[name])
            for name, n in counts.most_common()]


def _set_provenance(options: list[JourneyOption], fallback: DataProvenance) -> DataProvenance:
    """Report the oldest retrieval time among the options actually used (cached data included)."""
    if not options:
        return fallback
    oldest = min(options, key=lambda o: o.provenance.as_of)
    return oldest.provenance


def _fare_notes(evaluations: list[Evaluation], journey: JourneyDetails) -> list[str]:
    if not evaluations or any(e.total_fare is not None for e in evaluations):
        return []
    if journey.budget_priority == BudgetPriority.MINIMIZE_COST or journey.budget_limit is not None:
        return ["Fares are not available from the data source, so options cannot be compared or "
                "checked by price. No option is labelled \"Lowest cost\"."]
    return []


def _notes(eligible: list[Evaluation], excluded: list[Evaluation]) -> list[str]:
    known = [e.total_fare for e in eligible if e.total_fare is not None]
    if not known:
        return []
    cheapest_ok = min(known)
    cheaper = sorted((e for e in excluded if e.total_fare is not None and e.total_fare < cheapest_ok
                      and all(c.name != "departure_in_future" for c in e.violations)),
                     key=lambda e: e.total_fare)
    return [f"Cheaper option excluded — {_summary(e)}: {' '.join(c.detail for c in e.violations)}"
            for e in cheaper[:2]]


def _limitations(eligible: list[Evaluation], provenance: DataProvenance) -> list[str]:
    # Demo data is local/dev only (production refuses it) and is not labelled in the UI, so it adds no source note.
    notes = [BOOKING_LIMITATION] if provenance.mode == DataMode.DEMO else [provenance.note, BOOKING_LIMITATION]
    if eligible and not any(e.fully_compliant for e in eligible):
        notes.append("None of the eligible journeys could be fully verified against your mandatory "
                     "requirements; see \"Not verified\" on each option.")
    return notes
