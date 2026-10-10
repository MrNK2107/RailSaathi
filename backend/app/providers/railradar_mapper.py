"""Map RailRadar JSON records to planner models.

Shape OBSERVED from the live API on 2026-10-10 (each item of data.trains):
    {"train": {"number", "name", "type", "runDays", "runningDaysBitmap"},
     "from": {"code", "name", "city", "departure": "HH:MM", "day", "sequence"},
     "to":   {"code", "name", "city", "arrival": "HH:MM", "day", "sequence"},
     "duration": <minutes>, "distance", "totalHaltsBetween"}
from.day/to.day are days of the train's own run. The `date` query parameter is the
passenger's boarding date at the origin (verified with non-daily train 22208).
No class or fare fields are documented for this endpoint, so none are invented.
Documented field names are tried first; a few alternative spellings remain as a
fallback until a real response is observed with scripts/check_railradar.py.
Records missing essential fields are skipped, never guessed.
"""

import re
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.domain.enums import TravelClass
from app.domain.options import DataProvenance, JourneyOption, Leg

NUMBER_KEYS = ("trainNumber", "train_number", "trainNo", "train_no", "number")
NAME_KEYS = ("trainName", "train_name", "name")
DEPART_KEYS = ("departureTime", "departure_time", "fromDepartureTime", "fromStd", "std", "departure", "dep")
ARRIVE_KEYS = ("arrivalTime", "arrival_time", "toArrivalTime", "toSta", "sta", "arrival", "arr")
DURATION_KEYS = ("durationMinutes", "duration_minutes", "travelTimeMinutes", "travelTime", "duration")
# Only explicit 0-based offsets relative to the passenger's departure are trusted.
OFFSET_KEYS = ("arrivalDayOffset", "dayOffset", "daysToArrive")
FROM_CODE_KEYS = ("fromStationCode", "from_station_code", "sourceStationCode", "fromCode")
TO_CODE_KEYS = ("toStationCode", "to_station_code", "destinationStationCode", "toCode")
FROM_NAME_KEYS = ("fromStationName", "from_station_name", "sourceStationName")
TO_NAME_KEYS = ("toStationName", "to_station_name", "destinationStationName")
CLASS_KEYS = ("classes", "availableClasses", "travelClasses", "classTypes")
FARE_KEYS = ("fares", "fare", "fareByClass")
NESTED_FROM = ("from", "source", "fromStation", "origin")
NESTED_TO = ("to", "destination", "toStation")

# Documented: data.delayMinutes, data.status, data.lastUpdatedAt, data.exceptions[].
DELAY_KEYS = ("delayMinutes", "delay_minutes", "currentDelay", "delay", "lateBy", "late_by")
CANCELLED_KEYS = ("isCancelled", "cancelled", "is_cancelled")
STATUS_KEYS = ("status", "runningStatus", "trainStatus")


class MappingError(ValueError):
    pass


def first(record: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, "", []):
            return value
    return None


def nested(record: dict, containers: tuple[str, ...], keys: tuple[str, ...]) -> Any:
    for container in containers:
        inner = record.get(container)
        if isinstance(inner, dict):
            value = first(inner, keys)
            if value is not None:
                return value
    return None


def parse_clock(value: Any) -> time | None:
    """Accept "HH:MM", "HH:MM:SS", ISO datetimes, or minutes after midnight."""
    if isinstance(value, (int, float)) and 0 <= value < 24 * 60 * 3:
        minutes = int(value) % (24 * 60)
        return time(minutes // 60, minutes % 60)
    if isinstance(value, str):
        m = re.search(r"(\d{1,2}):(\d{2})", value)
        if m and int(m[1]) < 24 and int(m[2]) < 60:
            return time(int(m[1]), int(m[2]))
    return None


def parse_minutes(value: Any) -> int | None:
    """Accept 485, "485", "08:05", "8h 5m", "8 hrs 05 mins"."""
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    if not isinstance(value, str):
        return None
    if value.strip().isdigit():
        return int(value)
    if m := re.fullmatch(r"\s*(\d{1,2}):(\d{2})(?::\d{2})?\s*", value):
        return int(m[1]) * 60 + int(m[2])
    hours = re.search(r"(\d+)\s*h", value)
    mins = re.search(r"(\d+)\s*m", value)
    total = (int(hours[1]) * 60 if hours else 0) + (int(mins[1]) if mins else 0)
    return total or None


def _clean_classes(value: Any) -> list[TravelClass]:
    items = value if isinstance(value, list) else re.split(r"[,\s]+", value) if isinstance(value, str) else []
    out: list[TravelClass] = []
    for item in items:
        code = (item.get("code") or item.get("class") if isinstance(item, dict) else item) or ""
        try:
            cls = TravelClass(str(code).strip().upper())
        except ValueError:
            continue  # e.g. 1A, 3E, FC are not supported by the planner
        if cls not in out:
            out.append(cls)
    return out


def _fares(value: Any) -> dict[TravelClass, float]:
    pairs: list[tuple[Any, Any]] = []
    if isinstance(value, dict):
        pairs = list(value.items())
    elif isinstance(value, list):
        pairs = [(i.get("class") or i.get("code"), i.get("fare") or i.get("amount")) for i in value if isinstance(i, dict)]
    fares: dict[TravelClass, float] = {}
    for cls, amount in pairs:
        try:
            fares[TravelClass(str(cls).upper())] = float(amount)
        except (ValueError, TypeError):
            continue
    return fares


def parse_when(value: Any, day: date, tz: ZoneInfo) -> datetime | None:
    """A full ISO timestamp is used as-is; a bare clock time is placed on the search date."""
    if isinstance(value, str) and re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", value):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.astimezone(tz) if parsed.tzinfo else parsed.replace(tzinfo=tz)
    clock = parse_clock(value)
    return datetime.combine(day, clock, tzinfo=tz) if clock else None


def map_train(raw: dict, from_code: str, to_code: str, day: date, tz: ZoneInfo,
              provenance: DataProvenance, station_name: dict[str, str]) -> JourneyOption:
    train = raw.get("train") if isinstance(raw.get("train"), dict) else {}
    origin_obj = raw.get("from") if isinstance(raw.get("from"), dict) else {}
    dest_obj = raw.get("to") if isinstance(raw.get("to"), dict) else {}
    train_no = train.get("number") or first(raw, NUMBER_KEYS)
    dep_raw = origin_obj.get("departure") or nested(raw, NESTED_FROM, ("departureTime", "std", "time"))         or first(raw, DEPART_KEYS)
    departure = parse_when(dep_raw, day, tz)
    if not train_no or departure is None:
        raise MappingError("train number or departure time missing")
    arrival = _arrival(raw, departure, tz, dest_obj)
    origin = str(origin_obj.get("code") or origin_obj.get("stationCode") or first(raw, FROM_CODE_KEYS)
                 or from_code).upper()
    dest = str(dest_obj.get("code") or dest_obj.get("stationCode") or first(raw, TO_CODE_KEYS) or to_code).upper()
    name = train.get("name") or first(raw, NAME_KEYS) or f"Train {train_no}"
    leg = Leg(
        train_no=str(train_no), train_name=str(name),
        from_code=origin, from_name=str(origin_obj.get("name") or origin_obj.get("stationName")
                                        or first(raw, FROM_NAME_KEYS) or station_name.get(origin, origin)),
        to_code=dest, to_name=str(dest_obj.get("name") or dest_obj.get("stationName")
                                  or first(raw, TO_NAME_KEYS) or station_name.get(dest, dest)),
        departure=departure, arrival=arrival,
    )
    return JourneyOption(
        option_id=f"RR-{train_no}-{origin}-{dest}@{day.isoformat()}",
        legs=[leg], departure=departure, arrival=arrival,
        duration_minutes=int((arrival - departure).total_seconds() // 60), transfers=0,
        fares=_fares(first(raw, FARE_KEYS)), classes=_clean_classes(first(raw, CLASS_KEYS)),
        station_codes=[origin, dest], provenance=provenance,
    )


def _arrival(raw: dict, departure: datetime, tz: ZoneInfo, dest_obj: dict) -> datetime:
    """Prefer the documented duration (minutes); else to.arrival (ISO or clock + explicit
    0-based offset); a bare clock not after departure is taken as the next day."""
    duration = parse_minutes(first(raw, DURATION_KEYS))
    if duration:
        return departure + timedelta(minutes=duration)
    arr_raw = dest_obj.get("arrival") or nested(raw, NESTED_TO, ("arrivalTime", "sta", "time")) or first(raw, ARRIVE_KEYS)
    if isinstance(arr_raw, str) and re.match(r"\d{4}-\d{2}-\d{2}T", arr_raw):
        arrival = parse_when(arr_raw, departure.date(), tz)
        if arrival is None or arrival <= departure:
            raise MappingError("arrival timestamp missing or not after departure")
        return arrival
    arr_clock = parse_clock(arr_raw)
    if arr_clock is None:
        raise MappingError("neither duration nor arrival time present")
    arrival = datetime.combine(departure.date(), arr_clock, tzinfo=tz)
    offset = first(raw, OFFSET_KEYS)
    origin_day = (raw.get("from") or {}).get("day") if isinstance(raw.get("from"), dict) else None
    if isinstance(dest_obj.get("day"), int) and isinstance(origin_day, int):
        offset = dest_obj["day"] - origin_day  # observed: from.day/to.day are days of the train's run
    if isinstance(offset, int) and 0 <= offset <= 3:
        arrival += timedelta(days=offset)
    return arrival if arrival > departure else arrival + timedelta(days=1)


def map_live_status(raw: dict) -> tuple[int | None, bool]:
    """Return (delay_minutes, cancelled) from a live-status payload; None delay if not stated."""
    cancelled = bool(first(raw, CANCELLED_KEYS))
    status = str(first(raw, STATUS_KEYS) or "").upper()
    exceptions = raw.get("exceptions") if isinstance(raw.get("exceptions"), list) else []
    cancelled = cancelled or "CANCEL" in status or any("CANCEL" in str(e).upper() for e in exceptions)
    delay_value = first(raw, DELAY_KEYS)
    if delay_value is None:
        for container in ("currentStatus", "current", "liveData", "position"):
            inner = raw.get(container)
            if isinstance(inner, dict):
                delay_value = first(inner, DELAY_KEYS)
                if delay_value is not None:
                    break
    delay = parse_minutes(delay_value) if not isinstance(delay_value, (int, float)) else int(delay_value)
    return (max(delay, 0) if delay is not None else None), cancelled
