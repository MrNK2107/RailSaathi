"""Injectable clock so date-dependent logic can be tested with a fixed time."""

from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def __init__(self, tz: str = "Asia/Kolkata") -> None:
        self._tz = ZoneInfo(tz)

    def now(self) -> datetime:
        return datetime.now(self._tz)


class FixedClock:
    def __init__(self, fixed: datetime) -> None:
        if fixed.tzinfo is None:
            raise ValueError("FixedClock requires a timezone-aware datetime")
        self._fixed = fixed

    def now(self) -> datetime:
        return self._fixed
