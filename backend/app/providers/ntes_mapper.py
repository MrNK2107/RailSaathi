"""Map NTES responses (from the unofficial `ntes-client`) to RailSaathi models.

Shapes OBSERVED from the live service on 2026-10-17 (scripts/ntes_smoke.py prints them again):

trains_between -> {"StationFromCode", "StationToCode", "TotalTrains", "Trains": [
    {"TrainNumber": "12657", "TrainName": "MAS SBC SF MAIL", "FromStation": "MAS", "FromStationName": "...",
     "toStation": "SBC", "ToStationName": "...", "DepTimeFrom": "22:50", "ArrTimeTo": "04:35",
     "TravelTime": "05:45", "DayOfRun": "Daily" | "Mon,tue,thu", "ClassOfTravel": "1A,2A,3A,SL,GEN,PWD", ...}]}
  NTES answers for the station *groups*: a MAS->SBC query also lists trains from PER or to SMVB/YPR. Only trains
  whose boarding and alighting stations are among the stations the passenger's places resolved to are kept.
  `DayOfRun` is read as the days the train leaves the boarding station (FromStation), as the NTES app shows it.
  There are no fares: none are ever invented.
schedule -> {"TrainNumber", "TrainName", "stations": [{"StationCode", "StationName", "STA": "" | "22:50",
    "STD": "22:51" | "", "Day": 1, ...}]}   (Day is 1 on the train's first day)
station_live -> {"Station", "NextHr", "TrainsAtStation": [{"TrainNumber", "TrainName", "Destination",
    "DestinationName", "STD": "23:10 16-Oct" | "DSTN", "ETD": "02:57" | "DSTN", "DelayDep": "RT" | "03:47",
    "Cancel": 0, "DepCancelFlag": 0, "StartDate": "15-Oct-2026", ...}]}
live_status -> {"TN", "TNM", "CPOS": "Departed from ... at 02:37 17-Oct", "LDEL": "3" (minutes late at the last
    reported station), "STNS": [per stop: "SC", "STD", "ETD", "DDEP": "00:09" | "On Time", ...], ...}
Records missing essential fields are skipped, never guessed."""

import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.domain.options import DataProvenance, JourneyOption, Leg
from app.providers.railradar_mapper import MappingError, _clean_classes, parse_clock, parse_minutes

_DAYS = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
_MONTHS = {m: i + 1 for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT",
                                           "NOV", "DEC"))}


def station_label(code: str, ntes_name: Any, catalogue: dict[str, str]) -> str:
    """The catalogue's name when RailSaathi knows the station, else NTES's (upper-case) name in title case."""
    if code in catalogue:
        return catalogue[code]
    name = str(ntes_name or "").strip()
    return name.title() if name else code


def runs_on(day_of_run: Any, day: date) -> bool | None:
    """Whether a train with this NTES "days of run" runs on `day`; None when the value is not understood."""
    text = str(day_of_run or "").strip().upper()
    if not text:
        return None
    if text == "DAILY":
        return True
    days = set()
    for token in re.split(r"[,\s]+", text):
        if token[:3] not in _DAYS:
            return None
        days.add(_DAYS[token[:3]])
    return day.weekday() in days


def map_between(raw: dict, day: date, tz: ZoneInfo, provenance: DataProvenance,
                catalogue: dict[str, str]) -> JourneyOption:
    """One trains_between record, placed on `day` (the boarding date). Raises MappingError when unusable."""
    train_no = str(raw.get("TrainNumber") or "").strip()
    origin = str(raw.get("FromStation") or "").strip().upper()
    dest = str(raw.get("toStation") or raw.get("ToStation") or "").strip().upper()
    dep_clock = parse_clock(raw.get("DepTimeFrom"))
    travel = parse_minutes(raw.get("TravelTime"))
    if not train_no or not origin or not dest or dep_clock is None or not travel:
        raise MappingError("train number, stations, departure or travel time missing")
    departure = datetime.combine(day, dep_clock, tzinfo=tz)
    arrival = departure + timedelta(minutes=travel)
    name = str(raw.get("TrainName") or "").strip() or f"Train {train_no}"
    leg = Leg(train_no=train_no, train_name=name,
              from_code=origin, from_name=station_label(origin, raw.get("FromStationName"), catalogue),
              to_code=dest, to_name=station_label(dest, raw.get("ToStationName"), catalogue),
              departure=departure, arrival=arrival)
    return JourneyOption(
        option_id=f"NTES-{train_no}-{origin}-{dest}@{day.isoformat()}", legs=[leg], departure=departure,
        arrival=arrival, duration_minutes=travel, transfers=0, fares={},
        classes=_clean_classes(raw.get("ClassOfTravel")), station_codes=[origin, dest], provenance=provenance)


def _hhmm(value: Any) -> str | None:
    clock = parse_clock(value) if isinstance(value, str) and value.strip() else None
    return f"{clock:%H:%M}" if clock else None


def map_schedule(raw: dict, catalogue: dict[str, str]) -> tuple[str | None, list[dict]]:
    """(train name, stops as ScheduleStop fields). Stops without a station code are skipped."""
    stops = []
    for stop in raw.get("stations") or []:
        if not isinstance(stop, dict):
            continue
        code = str(stop.get("StationCode") or "").strip().upper()
        if not code:
            continue
        day = stop.get("Day")
        stops.append({"station_code": code, "station_name": station_label(code, stop.get("StationName"), catalogue),
                      "arrival": _hhmm(stop.get("STA")), "departure": _hhmm(stop.get("STD")),
                      "day_offset": max(int(day) - 1, 0) if isinstance(day, int) or str(day).isdigit() else 0})
    name = str(raw.get("TrainName") or "").strip() or None
    return name, stops


def parse_board_time(value: Any, now: datetime) -> datetime | None:
    """"23:10 16-Oct" -> an aware datetime in now's zone, the year chosen nearest to `now`. "DSTN"/"SRC" -> None."""
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s+(\d{1,2})-([A-Za-z]{3})\s*", str(value or ""))
    if not m or m[4].upper() not in _MONTHS or int(m[1]) > 23 or int(m[2]) > 59:
        return None
    best = None
    for year in (now.year - 1, now.year, now.year + 1):
        try:
            when = datetime(year, _MONTHS[m[4].upper()], int(m[3]), int(m[1]), int(m[2]), tzinfo=now.tzinfo)
        except ValueError:
            continue
        if best is None or abs(when - now) < abs(best - now):
            best = when
    return best


def parse_delay(value: Any) -> int | None:
    """NTES delays: "RT" / "On Time" -> 0, "03:47" -> 227, "12" -> 12; anything else -> None (unknown)."""
    if isinstance(value, (int, float)) and value >= 0:
        return int(value)
    text = str(value or "").strip().upper()
    if text in ("RT", "ON TIME", "NO DELAY"):
        return 0
    if re.fullmatch(r"\d{1,2}:\d{2}", text):
        hours, minutes = text.split(":")
        return int(hours) * 60 + int(minutes)
    if text.isdigit():
        return int(text)
    return None


def _flag(value: Any) -> bool:
    return str(value).strip() in ("1", "True", "true", "Y")


def map_board_entry(raw: dict, now: datetime) -> dict | None:
    """A departure on a station board, or None for trains that end here or have no usable departure time."""
    train_no = str(raw.get("TrainNumber") or "").strip()
    departure = parse_board_time(raw.get("STD"), now)
    if not train_no or departure is None:
        return None
    cancelled = _flag(raw.get("Cancel")) or _flag(raw.get("DepCancelFlag"))
    return {"train_no": train_no, "train_name": str(raw.get("TrainName") or "").strip() or f"Train {train_no}",
            "scheduled_departure": departure,
            "destination": str(raw.get("Destination") or "").strip().upper() or None,
            "destination_name": raw.get("DestinationName"),
            "delay_minutes": None if cancelled else parse_delay(raw.get("DelayDep")), "cancelled": cancelled}


# A mention of "cancel" counts as a FULL cancellation only in one of these unambiguous forms.
_FULL_CANCEL = (re.compile(r"\b(?:IS|HAS BEEN|STANDS|STAND)\s+(?:FULLY\s+)?CANCELL?ED\b"),
                re.compile(r"\bTRAIN(?:\s+NO\.?)?(?:\s+\d{4,5})?\s+(?:FULLY\s+)?CANCELL?ED\b"),
                re.compile(r"^(?:REQUEST FAILED:\s*)?(?:FULLY\s+)?CANCELL?ED\b"),
                re.compile(r"\bFULLY\s+CANCELL?ED\b"))
# Any of these makes a cancellation mention ambiguous: partly cancelled, short-terminated, diverted, a negation,
# "cancellation details ...", or a cancellation limited to a stretch of the route.
_NOT_FULL = re.compile(r"PARTIAL|SHORT|TERMINAT|DIVERT|DETAILS|BETWEEN|\bNOT\b|\bNO\b(?!\.)|\bUPTO\b|\bUP TO\b|"
                       r"\bTILL\b|\bFROM\b|\bAT\b")


def classify_cancellation(text: object) -> bool | None:
    """True only for an unambiguous full cancellation; None when a cancellation is mentioned in any other way (the
    status is unclear, never claimed); False when no cancellation is mentioned."""
    t = " ".join(str(text or "").upper().split())
    if "CANCEL" not in t:
        return False
    if _NOT_FULL.search(t):
        return None
    return True if any(p.search(t) for p in _FULL_CANCEL) else None


def map_live(raw: dict) -> tuple[int | None, bool | None, bool]:
    """(delay minutes, cancelled, unclear) from a live_status payload. LDEL is the delay at the last reported
    station. `cancelled` is True only for an unambiguous full cancellation; `unclear` is True when the position text
    mentions a cancellation in an ambiguous way (partial, short-terminated, ...), and then `cancelled` is None."""
    position = " ".join(" ".join(str(raw.get(k) or "") for k in ("CPOS", "LUPDFULL")).split())
    verdict = classify_cancellation(position)
    if verdict is True:
        return None, True, False
    delay = parse_delay(raw.get("LDEL"))
    if verdict is None:
        return delay, None, True
    if delay is None and not position:
        return None, None, False  # no running information at all
    return delay, (False if position else None), False

