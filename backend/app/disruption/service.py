"""Disruption-aware reassessment. Never replaces a plan on its own: it returns
re-ranked alternatives and requires the passenger to confirm a replacement."""

from datetime import datetime, timedelta

from app.domain.enums import Language
from app.domain.journey import JourneyDetails
from app.domain.options import JourneyOption, Recommendation, RecommendationSet
from app.domain.state import Reassessment
from app.providers.base import DisruptionEvent, DisruptionSource
from app.ranking.recommender import Recommender


class DisruptionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _uses(option: JourneyOption, train_no: str) -> bool:
    return any(leg.train_no == train_no for leg in option.legs)


def apply_event(options: list[JourneyOption], event: DisruptionEvent) -> list[JourneyOption]:
    if event.type == "cancellation":
        return [o for o in options if not _uses(o, event.train_no)]
    return [_delay(o, event) if _uses(o, event.train_no) else o for o in options]


def _delay(option: JourneyOption, event: DisruptionEvent) -> JourneyOption:
    shift = timedelta(minutes=event.delay_minutes)
    legs = [
        leg.model_copy(update={"departure": leg.departure + shift, "arrival": leg.arrival + shift})
        if leg.train_no == event.train_no else leg
        for leg in option.legs
    ]
    buffers = [int((b.departure - a.arrival).total_seconds() // 60) for a, b in zip(legs, legs[1:])]
    return option.model_copy(update={
        "legs": legs,
        "departure": legs[0].departure,
        "arrival": legs[-1].arrival,
        "duration_minutes": int((legs[-1].arrival - legs[0].departure).total_seconds() // 60),
        "min_transfer_minutes": min(buffers) if buffers else None,
        "simulated_change": event.label,
    })


class DisruptionService:
    def __init__(self, source: DisruptionSource, recommender: Recommender) -> None:
        self._source = source
        self._recommender = recommender

    def list_events(self) -> list[DisruptionEvent]:
        return self._source.list_events()

    def pick_event(self, event_id: str | None, current: RecommendationSet, selected_id: str | None) -> DisruptionEvent:
        if event_id:
            event = self._source.get_event(event_id)
            if event is None:
                raise DisruptionError("unknown_event", f"Unknown disruption event '{event_id}'.")
            return event
        options = {r.option.option_id: r.option for r in current.recommendations}
        ordered = [options[selected_id]] if selected_id in options else []
        ordered += [o for oid, o in options.items() if oid != selected_id]
        live_lookup = getattr(self._source, "events_for_trains", None)
        if live_lookup is not None:
            trains = [(leg.train_no, leg.departure.date()) for o in ordered for leg in o.legs]
            events = live_lookup(trains)
            if not events:
                raise DisruptionError("no_relevant_event",
                                      "No delays or cancellations are currently reported for your trains (live status).")
        else:
            events = self._source.list_events()
        for option in ordered:
            for event in events:
                if _uses(option, event.train_no):
                    return event
        raise DisruptionError("no_relevant_event", "No simulated disruption affects the current options.")

    def reassess(
        self, journey: JourneyDetails, current: RecommendationSet, selected_id: str | None,
        event_id: str | None, now: datetime, lang: Language,
    ) -> tuple[RecommendationSet, Reassessment]:
        event = self.pick_event(event_id, current, selected_id)
        new_set = self._recommender.recommend(journey, now, lang, transform=lambda opts: apply_event(opts, event))
        affected = [r.option.option_id for r in current.recommendations if _uses(r.option, event.train_no)]
        previous = next((r for r in current.recommendations if r.option.option_id == selected_id), None)
        still_valid = self._still_valid(previous, new_set, event)
        changes = [_describe(r, event) for r in current.recommendations if _uses(r.option, event.train_no)]
        summary = _summary(event, previous, still_valid)
        return new_set, Reassessment(
            event_id=event.id, event_label=event.label, simulated=event.simulated, summary=summary,
            affected_option_ids=affected,
            selected_option_affected=bool(previous and previous.option.option_id in affected),
            original_still_valid=still_valid, changes=changes, previous_selection=previous,
            requires_confirmation=True,
        )

    @staticmethod
    def _still_valid(previous: Recommendation | None, new_set: RecommendationSet, event: DisruptionEvent) -> bool | None:
        if previous is None:
            return None
        if not _uses(previous.option, event.train_no):
            return True
        if event.type == "cancellation":
            return False
        return previous.option.option_id not in {e.option_id for e in new_set.excluded}


def _describe(rec: Recommendation, event: DisruptionEvent) -> str:
    o = rec.option
    if event.type == "cancellation":
        return f"{event.train_no} is cancelled (simulated), so option {o.option_id} is no longer available."
    new_arrival = o.arrival + timedelta(minutes=event.delay_minutes) if o.legs[-1].train_no == event.train_no else None
    if new_arrival:
        return (f"{event.train_no} delayed {event.delay_minutes} min (simulated): arrival moves from "
                f"{o.arrival:%H:%M %d %b} to {new_arrival:%H:%M %d %b}.")
    return (f"{event.train_no} delayed {event.delay_minutes} min (simulated): the connection on option "
            f"{o.option_id} shrinks by {event.delay_minutes} min.")


def _summary(event: DisruptionEvent, previous: Recommendation | None, still_valid: bool | None) -> str:
    prefix = "SIMULATED EVENT: " if event.simulated else ""
    if previous is None:
        return f"{prefix}{event.label}. Recommendations have been recalculated."
    if still_valid:
        return f"{prefix}{event.label}. Your selected journey still meets your requirements."
    return (f"{prefix}{event.label}. Your selected journey no longer meets your requirements. "
            "Please review the alternatives and confirm a replacement. Nothing has been changed automatically.")
