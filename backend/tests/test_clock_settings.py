"""FIXED_NOW freezes the clock for deterministic e2e runs, but never in production."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.clock import FixedClock, SystemClock
from app.config import Settings
from app.container import build_clock


def test_fixed_now_freezes_clock_outside_production():
    settings = Settings(app_env="development", fixed_now="2026-10-10T10:00:00+05:30", _env_file=None)
    clock = build_clock(settings)
    assert isinstance(clock, FixedClock)
    assert clock.now() == datetime(2026, 10, 10, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


def test_naive_fixed_now_gets_app_timezone():
    settings = Settings(fixed_now="2026-10-10T10:00:00", _env_file=None)
    assert build_clock(settings).now().tzinfo == ZoneInfo("Asia/Kolkata")


def test_fixed_now_ignored_in_production():
    settings = Settings(app_env="production", fixed_now="2026-10-10T10:00:00+05:30", _env_file=None)
    assert isinstance(build_clock(settings), SystemClock)


def test_default_is_system_clock():
    assert isinstance(build_clock(Settings(_env_file=None)), SystemClock)
