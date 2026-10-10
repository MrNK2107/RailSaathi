from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.clock import FixedClock
from app.providers.demo import DemoDisruptionSource, DemoJourneyProvider
from app.stations.resolver import StationResolver

IST = ZoneInfo("Asia/Kolkata")
# Saturday 10 Oct 2026, 10:00 IST -> "tomorrow" is Sunday 11 Oct 2026.
FIXED_NOW = datetime(2026, 10, 10, 10, 0, tzinfo=IST)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(FIXED_NOW)


@pytest.fixture(scope="session")
def provider() -> DemoJourneyProvider:
    return DemoJourneyProvider()


@pytest.fixture(scope="session")
def disruptions() -> DemoDisruptionSource:
    return DemoDisruptionSource()


@pytest.fixture(scope="session")
def resolver(provider) -> StationResolver:
    return StationResolver(provider)
