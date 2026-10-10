"""Deterministic parsing of dates, times, budgets and classes.

The LLM (if any) only supplies raw text such as "tomorrow" or "9 am"; these
functions decide what that means using the injected clock.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.domain.enums import TravelClass

WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5,
    "sunday": 6, "திங்கள்": 0, "செவ்வாய்": 1, "புதன்": 2, "வியாழன்": 3, "வெள்ளி": 4,
    "சனி": 5, "ஞாயிறு": 6,
}
MONTHS = {
    m: i + 1
    for i, names in enumerate([
        ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
        ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
        ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"), ("dec", "december"),
    ])
    for m in names
}
_TODAY = ("today", "tonight", "இன்று", "இன்னிக்கு", "inniki", "innaiku")
_TOMORROW = ("tomorrow", "tmrw", "tmr", "நாளை", "naalai", "nalaiku", "naalaikku")
_DAY_AFTER = ("day after tomorrow", "நாளை மறுநாள்", "நாளைமறுநாள்")


@dataclass(frozen=True)
class DateParse:
    status: str  # "ok" | "ambiguous" | "invalid"
    value: date | None = None
    inferred: bool = False
    message: str = ""


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_date_text(text: str, now: datetime) -> DateParse:
    t = text.strip().lower()
    today = now.date()
    if any(k in t for k in _DAY_AFTER):
        return DateParse("ok", today + timedelta(days=2))
    if any(k in t for k in _TOMORROW):
        return DateParse("ok", today + timedelta(days=1))
    if any(k in t for k in _TODAY):
        return DateParse("ok", today)
    for name, idx in WEEKDAYS.items():
        if name in t:
            return _weekday(idx, today, explicit_next="next" in t)
    return _absolute(t, today)


def _weekday(idx: int, today: date, explicit_next: bool) -> DateParse:
    delta = (idx - today.weekday()) % 7
    if delta == 0 and not explicit_next:
        return DateParse("ambiguous", message="Do you mean today or the same day next week?")
    return DateParse("ok", today + timedelta(days=delta or 7))


def _absolute(t: str, today: date) -> DateParse:
    if m := re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t):
        return _checked(_safe_date(int(m[1]), int(m[2]), int(m[3])))
    if m := re.search(r"\b(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?\b", t):
        return _dmy(int(m[1]), int(m[2]), m[3], today)
    if m := re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)(?:\s+(\d{4}))?", t):
        if m[2] in MONTHS:
            return _dmy(int(m[1]), MONTHS[m[2]], m[3], today)
    if m := re.search(r"\b([a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?", t):
        if m[1] in MONTHS:
            return _dmy(int(m[2]), MONTHS[m[1]], m[3], today)
    return DateParse("invalid", message="I could not understand that date.")


def _dmy(d: int, mth: int, year: str | None, today: date) -> DateParse:
    if year:
        y = int(year) + (2000 if len(year) == 2 else 0)
        return _checked(_safe_date(y, mth, d))
    candidate = _safe_date(today.year, mth, d)
    if candidate and candidate < today:
        candidate = _safe_date(today.year + 1, mth, d)
    result = _checked(candidate)
    return DateParse(result.status, result.value, inferred=True, message=result.message)


def _checked(value: date | None) -> DateParse:
    if value is None:
        return DateParse("invalid", message="That date does not exist.")
    return DateParse("ok", value)


def parse_time_text(text: str) -> str | None:
    """Return "HH:MM" for inputs like "9 am", "9:30pm", "21:00", "9", "காலை 9"."""
    t = text.strip().lower().replace(".", ":")
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\s*m|p\s*m)?", t)
    if not m:
        return None
    hour, minute = int(m[1]), int(m[2] or 0)
    meridiem = (m[3] or "").replace(" ", "")
    if meridiem == "" and any(w in t for w in ("மாலை", "இரவு", "evening", "night", "maalai", "malai", "iravu")):
        meridiem = "pm"
    if meridiem == "pm" and hour < 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


def is_valid_hhmm(value: str) -> bool:
    m = re.fullmatch(r"(\d{2}):(\d{2})", value or "")
    return bool(m) and int(m[1]) < 24 and int(m[2]) < 60


CLASS_ALIASES: dict[str, TravelClass] = {
    "sleeper": TravelClass.SL, "sl": TravelClass.SL,
    "3a": TravelClass.THREE_A, "3ac": TravelClass.THREE_A, "third ac": TravelClass.THREE_A,
    "3 tier ac": TravelClass.THREE_A, "ac 3 tier": TravelClass.THREE_A, "3 tier": TravelClass.THREE_A,
    "2a": TravelClass.TWO_A, "2ac": TravelClass.TWO_A, "second ac": TravelClass.TWO_A,
    "2 tier ac": TravelClass.TWO_A, "ac 2 tier": TravelClass.TWO_A,
    "ac chair car": TravelClass.CC, "chair car": TravelClass.CC, "cc": TravelClass.CC,
    "executive chair car": TravelClass.EC, "executive": TravelClass.EC, "ec": TravelClass.EC,
    "second sitting": TravelClass.TWO_S, "2s": TravelClass.TWO_S, "general sitting": TravelClass.TWO_S,
}
UNSUPPORTED_CLASSES = ("first ac", "1a", "1ac", "first class", "ac first class")


def parse_class(text: str) -> TravelClass | None:
    t = text.strip().lower()
    if t.upper() in TravelClass.__members__.values():
        return TravelClass(t.upper())
    return CLASS_ALIASES.get(t)
