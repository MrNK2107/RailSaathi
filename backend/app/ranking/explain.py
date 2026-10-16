"""Explanations built only from computed attributes (never from the LLM)."""

from app.domain.enums import (
    BudgetPriority,
    CheckStatus,
    Language,
    RecommendationCategory,
    Verification,
)
from app.domain.journey import JourneyDetails
from app.ranking.evaluate import Evaluation
from app.ranking.scoring import departure_score, effective_window

T = {
    "en": {
        "best_overall": "it is the strongest overall match for your priorities",
        "lowest_cost": "it has the lowest listed fare among eligible options (₹{fare} for {pax})",
        "fastest": "it is the quickest eligible journey ({dur})",
        "recommended": "Recommended because {reasons}.",
        "deadline_met": "It arrives at {arr}, before your {deadline} deadline.",
        "deadline_soft_missed": "It arrives at {arr}, after your preferred {deadline} arrival.",
        "window_miss": "Departs at {dep}, outside your preferred departure window.",
        "transfer": "{n} change(s) at {at} with a {buf} min connection.",
        "pricier": "Costs ₹{diff} more than the cheapest eligible option.",
        "slower": "Takes {diff} longer than the fastest eligible option.",
        "class_missing": "Your preferred class {cls} is not offered; showing {sel}.",
        "over_budget": "Total ₹{fare} is above your budget of ₹{limit}.",
        "and": " and ",
        "fare_unknown": "Fare not available from the data source — check the official fare before booking.",
        "also_eligible": "Also eligible: meets your mandatory requirements; ranked below the options above.",
    },
    "ta": {
        "best_overall": "இது உங்கள் முன்னுரிமைகளுக்கு மிகச் சிறந்த பொருத்தம்",
        "lowest_cost": "தகுதியான விருப்பங்களில் இதுவே குறைந்த கட்டணம் (₹{fare}, {pax} பேருக்கு)",
        "fastest": "இதுவே மிக விரைவான பயணம் ({dur})",
        "recommended": "பரிந்துரைக்கப்படுகிறது: {reasons}.",
        "deadline_met": "{arr} மணிக்கு வந்தடையும் — உங்கள் {deadline} காலக்கெடுவிற்கு முன்.",
        "deadline_soft_missed": "{arr} மணிக்கு வந்தடையும் — நீங்கள் விரும்பிய {deadline} நேரத்திற்குப் பின்.",
        "window_miss": "{dep} மணிக்குப் புறப்படும் — நீங்கள் விரும்பிய நேரத்திற்கு வெளியே.",
        "transfer": "{at} நிலையத்தில் {n} மாற்றம் ({buf} நிமிட இணைப்பு).",
        "pricier": "குறைந்த கட்டண விருப்பத்தை விட ₹{diff} அதிகம்.",
        "slower": "மிக விரைவான விருப்பத்தை விட {diff} அதிக நேரம்.",
        "class_missing": "நீங்கள் விரும்பிய {cls} வகுப்பு இல்லை; {sel} காட்டப்படுகிறது.",
        "over_budget": "மொத்தம் ₹{fare} — உங்கள் ₹{limit} பட்ஜெட்டை விட அதிகம்.",
        "and": " மற்றும் ",
        "also_eligible": "மேலும் தகுதியானது: உங்கள் கட்டாயத் தேவைகளைப் பூர்த்தி செய்கிறது; மேலே உள்ளவற்றை விடக் குறைந்த தரவரிசை.",
        "fare_unknown": "தரவு மூலத்தில் கட்டணம் இல்லை — முன்பதிவுக்கு முன் அதிகாரப்பூர்வ கட்டணத்தைச் சரிபார்க்கவும்.",
    },
}


def fmt_duration(minutes: int) -> str:
    return f"{minutes // 60} h {minutes % 60:02d} min"


def _t(lang: Language, key: str, **kw) -> str:
    return T[lang.value][key].format(**kw)


def explain(
    ev: Evaluation, labels: list[RecommendationCategory], journey: JourneyDetails,
    lang: Language, cheapest: float | None, fastest: int,
) -> tuple[str, list[str], list[str], list[str]]:
    """Return (explanation, preference_matches, tradeoffs, unverified)."""
    pax = journey.passenger_count or 1
    reasons = [
        _t(lang, label.value, fare=f"{ev.total_fare or 0:,.0f}", pax=pax, dur=fmt_duration(ev.option.duration_minutes))
        for label in labels
    ]
    parts = ([_t(lang, "recommended", reasons=T[lang.value]["and"].join(reasons))] if reasons
             else [T[lang.value]["also_eligible"]])
    deadline_line = _deadline_line(ev, journey, lang)
    if deadline_line:
        parts.append(deadline_line)
    tradeoffs = _tradeoffs(ev, journey, lang, cheapest, fastest)
    unverified = [s.detail for s in ev.need_statuses if s.status == Verification.UNKNOWN]
    if ev.total_fare is None:
        unverified.append(T[lang.value]["fare_unknown"])
    return " ".join(parts), _matches(ev, journey), tradeoffs, unverified


def _deadline_line(ev: Evaluation, journey: JourneyDetails, lang: Language) -> str | None:
    if not ev.deadline_dt:
        return None
    arr = ev.option.arrival.strftime("%H:%M, %d %b")
    key = "deadline_met" if ev.option.arrival <= ev.deadline_dt else "deadline_soft_missed"
    return _t(lang, key, arr=arr, deadline=journey.arrival_deadline)


def _matches(ev: Evaluation, journey: JourneyDetails) -> list[str]:
    matches = [c.detail for c in ev.checks if c.status == CheckStatus.MET and c.name != "departure_in_future"]
    if journey.class_preference and ev.selected_class == journey.class_preference:
        matches.append(f"Preferred class {journey.class_preference} available.")
    if journey.budget_priority == BudgetPriority.MINIMIZE_COST and ev.total_fare is not None:
        matches.append("Lower fare prioritised as requested.")
    if ev.option.transfers == 0:
        matches.append("Direct journey (no changes).")
    window = effective_window(journey)
    if window and departure_score(ev.option.departure, window) == 1.0:
        matches.append(f"Departs within your preferred window ({window.start}-{window.end}).")
    if journey.budget_limit is not None and ev.total_fare is not None and ev.total_fare <= journey.budget_limit:
        matches.append(f"Within your budget of ₹{journey.budget_limit:,.0f}.")
    return matches


def _tradeoffs(ev: Evaluation, journey: JourneyDetails, lang: Language, cheapest: float | None, fastest: int) -> list[str]:
    out: list[str] = []
    window = effective_window(journey)
    if window and departure_score(ev.option.departure, window) < 1.0:
        out.append(_t(lang, "window_miss", dep=ev.option.departure.strftime("%H:%M")))
    if ev.option.transfers:
        at = ", ".join(leg.to_name for leg in ev.option.legs[:-1])
        out.append(_t(lang, "transfer", n=ev.option.transfers, at=at, buf=ev.option.min_transfer_minutes))
    if ev.total_fare is not None and cheapest is not None and ev.total_fare > cheapest:
        out.append(_t(lang, "pricier", diff=f"{ev.total_fare - cheapest:,.0f}"))
    if ev.option.duration_minutes > fastest:
        out.append(_t(lang, "slower", diff=fmt_duration(ev.option.duration_minutes - fastest)))
    if journey.class_preference and ev.selected_class and ev.selected_class != journey.class_preference:
        out.append(_t(lang, "class_missing", cls=journey.class_preference, sel=ev.selected_class))
    if (journey.budget_limit is not None and not journey.budget_strict and ev.total_fare is not None
            and ev.total_fare > journey.budget_limit):
        out.append(_t(lang, "over_budget", fare=f"{ev.total_fare:,.0f}", limit=f"{journey.budget_limit:,.0f}"))
    return out
