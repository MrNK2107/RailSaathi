"""Hard-constraint evaluation and passenger-need verification for one option."""

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from app.domain.enums import (
    ACCESSIBILITY_NEEDS,
    CheckStatus,
    DateAnchor,
    PassengerNeed,
    TransferPreference,
    TravelClass,
    Verification,
)
from app.domain.journey import JourneyDetails
from app.domain.options import ConstraintCheck, JourneyOption, NeedStatus
from app.providers.base import JourneyProvider

LONG_BUFFER_MINUTES = 60
NEED_LABELS = {
    PassengerNeed.ASSISTANCE_REQUESTED: "Assistance",
    PassengerNeed.WHEELCHAIR: "Wheelchair support",
    PassengerNeed.REDUCED_WALKING: "Reduced-walking route",
}


@dataclass
class Evaluation:
    option: JourneyOption
    selected_class: TravelClass | None
    fare_per_passenger: float | None
    total_fare: float | None
    checks: list[ConstraintCheck]
    need_statuses: list[NeedStatus] = field(default_factory=list)
    deadline_dt: datetime | None = None

    @property
    def eligible(self) -> bool:
        return all(c.status != CheckStatus.VIOLATED for c in self.checks)

    @property
    def fully_compliant(self) -> bool:
        return self.eligible and all(c.status != CheckStatus.UNVERIFIED for c in self.checks)

    @property
    def violations(self) -> list[ConstraintCheck]:
        return [c for c in self.checks if c.status == CheckStatus.VIOLATED]


def available_classes(option: JourneyOption) -> list[TravelClass]:
    return list(option.classes) or list(option.fares)


def choose_class(option: JourneyOption, journey: JourneyDetails) -> TravelClass | None:
    """Preferred class if offered, else the cheapest priced class, else unknown (None)."""
    if journey.class_preference and journey.class_preference in available_classes(option):
        return journey.class_preference
    if option.fares:
        return min(option.fares, key=lambda c: option.fares[c])
    return None


def deadline_for(option: JourneyOption, journey: JourneyDetails) -> datetime | None:
    if not journey.arrival_deadline:
        return None
    hh, mm = (int(p) for p in journey.arrival_deadline.split(":"))
    tz = option.arrival.tzinfo
    if journey.date_anchor == DateAnchor.ARRIVAL and journey.journey_date:
        return datetime.combine(journey.journey_date, time(hh, mm), tzinfo=tz)
    candidate = datetime.combine(option.departure.date(), time(hh, mm), tzinfo=tz)
    return candidate if candidate > option.departure else candidate + timedelta(days=1)


def need_statuses(option: JourneyOption, journey: JourneyDetails, provider: JourneyProvider) -> list[NeedStatus]:
    result: list[NeedStatus] = []
    for need in journey.passenger_needs:
        if need not in ACCESSIBILITY_NEEDS:
            continue
        per_station = {code: _facility(provider, code, need) for code in option.station_codes}
        result.append(_combine(need, per_station, provider))
    return result


def _facility(provider: JourneyProvider, code: str, need: PassengerNeed) -> Verification:
    station = provider.station(code)
    if station is None:
        return Verification.UNKNOWN
    return station.facilities.get(need, Verification.UNKNOWN)


def _station_name(provider: JourneyProvider, code: str) -> str:
    station = provider.station(code)
    return station.name if station else code


def _combine(need: PassengerNeed, per_station: dict[str, Verification], provider: JourneyProvider) -> NeedStatus:
    label = NEED_LABELS[need]

    def names(status: Verification) -> str:
        return ", ".join(_station_name(provider, c) for c, s in per_station.items() if s == status)

    if Verification.NOT_SUPPORTED in per_station.values():
        return NeedStatus(need=need, status=Verification.NOT_SUPPORTED,
                          detail=f"{label} is listed as not available at {names(Verification.NOT_SUPPORTED)} (per the data source).")
    if Verification.UNKNOWN in per_station.values():
        return NeedStatus(need=need, status=Verification.UNKNOWN,
                          detail=f"{label} has been requested, but availability at "
                                 f"{names(Verification.UNKNOWN)} has not been verified.")
    return NeedStatus(need=need, status=Verification.VERIFIED_SUPPORTED,
                      detail=f"{label} is listed as available at all stations on this journey "
                             "(per the data source; not a booking or guarantee).")


def evaluate_option(
    option: JourneyOption, journey: JourneyDetails, now: datetime,
    provider: JourneyProvider, min_transfer_minutes: int,
) -> Evaluation:
    cls = choose_class(option, journey)
    fare = option.fares.get(cls) if cls else None
    total = fare * (journey.passenger_count or 1) if fare is not None else None
    deadline = deadline_for(option, journey)
    statuses = need_statuses(option, journey, provider)
    checks = [
        _check_departure(option, now),
        _check_connection(option, journey, min_transfer_minutes),
        _check_deadline(option, journey, deadline),
        _check_budget(total, journey),
        _check_class(option, journey),
        _check_direct(option, journey),
        _check_assistance(statuses, journey),
    ]
    return Evaluation(option, cls, fare, total, [c for c in checks if c], statuses, deadline)


def _check_departure(option: JourneyOption, now: datetime) -> ConstraintCheck:
    if option.departure <= now:
        return ConstraintCheck(name="departure_in_future", status=CheckStatus.VIOLATED,
                               detail="This train has already departed.")
    return ConstraintCheck(name="departure_in_future", status=CheckStatus.MET,
                           detail="Departs after the current time.")


def _check_connection(option: JourneyOption, journey: JourneyDetails, minimum: int) -> ConstraintCheck | None:
    if option.transfers == 0:
        return None
    needed = max(minimum, LONG_BUFFER_MINUTES) if PassengerNeed.LONGER_TRANSFER_BUFFER in journey.passenger_needs else minimum
    buffer = option.min_transfer_minutes or 0
    ok = buffer >= needed
    return ConstraintCheck(
        name="connection_feasible", status=CheckStatus.MET if ok else CheckStatus.VIOLATED,
        detail=f"Connection time {buffer} min (minimum {needed} min required).")


def _check_deadline(option: JourneyOption, journey: JourneyDetails, deadline: datetime | None) -> ConstraintCheck | None:
    if deadline is None or not journey.deadline_strict:
        return None
    ok = option.arrival <= deadline
    when = option.arrival.strftime("%H:%M on %d %b")
    return ConstraintCheck(
        name="arrival_deadline", status=CheckStatus.MET if ok else CheckStatus.VIOLATED,
        detail=f"Arrives {when}, {'before' if ok else 'after'} the {journey.arrival_deadline} deadline.")


def _check_budget(total: float | None, journey: JourneyDetails) -> ConstraintCheck | None:
    if journey.budget_limit is None or not journey.budget_strict:
        return None
    if total is None:
        return ConstraintCheck(name="budget_limit", status=CheckStatus.UNVERIFIED,
                               detail="Fare not available from the data source, so the budget cannot be checked.")
    ok = total <= journey.budget_limit
    return ConstraintCheck(
        name="budget_limit", status=CheckStatus.MET if ok else CheckStatus.VIOLATED,
        detail=f"Total listed fare ₹{total:,.0f} vs maximum ₹{journey.budget_limit:,.0f}.")


def _check_class(option: JourneyOption, journey: JourneyDetails) -> ConstraintCheck | None:
    if not journey.class_preference or not journey.class_strict:
        return None
    offered = available_classes(option)
    if not offered:
        return ConstraintCheck(name="travel_class", status=CheckStatus.UNVERIFIED,
                               detail=f"The data source does not list classes, so {journey.class_preference} is unverified.")
    ok = journey.class_preference in offered
    return ConstraintCheck(
        name="travel_class", status=CheckStatus.MET if ok else CheckStatus.VIOLATED,
        detail=f"{journey.class_preference} {'is' if ok else 'is not'} offered on this journey.")


def _check_direct(option: JourneyOption, journey: JourneyDetails) -> ConstraintCheck | None:
    if journey.transfer_preference != TransferPreference.DIRECT_ONLY or not journey.transfer_strict:
        return None
    ok = option.transfers == 0
    return ConstraintCheck(
        name="direct_only", status=CheckStatus.MET if ok else CheckStatus.VIOLATED,
        detail="Direct journey." if ok else f"Requires {option.transfers} change(s).")


def _check_assistance(statuses: list[NeedStatus], journey: JourneyDetails) -> ConstraintCheck | None:
    if not journey.assistance_mandatory or not statuses:
        return None
    found = {s.status for s in statuses}
    if Verification.NOT_SUPPORTED in found:
        status = CheckStatus.VIOLATED
    elif Verification.UNKNOWN in found:
        status = CheckStatus.UNVERIFIED
    else:
        status = CheckStatus.MET
    return ConstraintCheck(name="mandatory_assistance", status=status,
                           detail=" ".join(s.detail for s in statuses))
