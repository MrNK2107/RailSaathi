from datetime import date, datetime

import pytest

from app.config import Settings
from app.domain.enums import DateAnchor, PassengerNeed, TravelClass
from app.domain.journey import JourneyDetails, Place, TimeWindow
from app.validation.parsing import parse_class, parse_date_text, parse_time_text
from app.validation.validator import missing_fields, validate_journey
from tests.conftest import FIXED_NOW, IST

SETTINGS = Settings(_env_file=None)
CBE = Place(id="coimbatore", label="Coimbatore", kind="city", station_codes=["CBE"])
CHN = Place(id="chennai", label="Chennai", kind="city", station_codes=["MAS", "MS"])
MAS = Place(id="MAS", label="Chennai Central (MAS)", kind="station", station_codes=["MAS"])


def _complete(**overrides) -> JourneyDetails:
    base = dict(origin=CBE, destination=CHN, journey_date=date(2026, 10, 11), passenger_count=2)
    return JourneyDetails(**{**base, **overrides})


def codes(issues):
    return [i.code for i in issues]


# ---- date parsing ----------------------------------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("tomorrow", date(2026, 10, 11)),
        ("நாளை", date(2026, 10, 11)),
        ("day after tomorrow", date(2026, 10, 12)),
        ("today", date(2026, 10, 10)),
        ("Sunday", date(2026, 10, 11)),
        ("next saturday", date(2026, 10, 17)),
        ("2026-10-20", date(2026, 10, 20)),
        ("20/10/2026", date(2026, 10, 20)),
        ("20 Oct", date(2026, 10, 20)),
        ("October 20", date(2026, 10, 20)),
    ],
)
def test_parse_dates(text, expected):
    result = parse_date_text(text, FIXED_NOW)
    assert result.status == "ok"
    assert result.value == expected


def test_relative_date_across_day_boundary():
    late_night = datetime(2026, 10, 10, 23, 59, tzinfo=IST)
    after_midnight = datetime(2026, 10, 11, 0, 1, tzinfo=IST)
    assert parse_date_text("tomorrow", late_night).value == date(2026, 10, 11)
    assert parse_date_text("tomorrow", after_midnight).value == date(2026, 10, 12)


def test_same_weekday_as_today_is_ambiguous():
    assert parse_date_text("saturday", FIXED_NOW).status == "ambiguous"


def test_day_month_without_year_rolls_forward_and_is_inferred():
    result = parse_date_text("5 Jan", FIXED_NOW)
    assert result.value == date(2027, 1, 5)
    assert result.inferred


@pytest.mark.parametrize("text", ["31/02/2026", "someday", "2026-13-01"])
def test_invalid_dates(text):
    assert parse_date_text(text, FIXED_NOW).status == "invalid"


@pytest.mark.parametrize(
    "text,expected",
    [("9 am", "09:00"), ("9:30pm", "21:30"), ("21:00", "21:00"), ("12 am", "00:00"),
     ("9", "09:00"), ("மாலை 6", "18:00"), ("25:00", None), ("soon", None)],
)
def test_parse_time(text, expected):
    assert parse_time_text(text) == expected


def test_parse_class():
    assert parse_class("AC chair car") is TravelClass.CC
    assert parse_class("3A") is TravelClass.THREE_A
    assert parse_class("first ac") is None


# ---- journey validation ----------------------------------------------------

def test_complete_journey_is_valid():
    assert validate_journey(_complete(), FIXED_NOW, SETTINGS) == []
    assert missing_fields(_complete()) == []


def test_missing_origin_and_destination_reported():
    j = JourneyDetails(journey_date=date(2026, 10, 11), passenger_count=1)
    assert missing_fields(j) == ["origin", "destination"]


def test_same_origin_and_destination_rejected():
    assert "same_origin_destination" in codes(validate_journey(_complete(origin=MAS), FIXED_NOW, SETTINGS))


def test_past_and_far_future_dates_rejected():
    assert codes(validate_journey(_complete(journey_date=date(2026, 10, 9)), FIXED_NOW, SETTINGS)) == ["date_in_past"]
    assert codes(validate_journey(_complete(journey_date=date(2027, 6, 1)), FIXED_NOW, SETTINGS)) == ["date_too_far"]


@pytest.mark.parametrize("count", [0, -1, 7])
def test_invalid_passenger_count(count):
    assert codes(validate_journey(_complete(passenger_count=count), FIXED_NOW, SETTINGS)) == ["invalid_passenger_count"]


def test_invalid_budget():
    assert codes(validate_journey(_complete(budget_limit=-50), FIXED_NOW, SETTINGS)) == ["invalid_budget"]


def test_mandatory_deadline_already_passed_today():
    j = _complete(journey_date=date(2026, 10, 10), arrival_deadline="09:00",
                  date_anchor=DateAnchor.ARRIVAL, deadline_strict=True)
    assert codes(validate_journey(j, FIXED_NOW, SETTINGS)) == ["deadline_passed"]


def test_contradictory_daytime_and_night_window():
    j = _complete(passenger_needs=[PassengerNeed.DAYTIME_DEPARTURE],
                  departure_window=TimeWindow(start="21:00", end="23:59"))
    assert codes(validate_journey(j, FIXED_NOW, SETTINGS)) == ["contradictory_constraints"]


def test_constraints_hash_changes_with_constraints_only():
    a = _complete()
    b = _complete(field_sources={"origin": "explicit"})
    c = _complete(passenger_count=3)
    assert a.constraints_hash() == b.constraints_hash() != c.constraints_hash()


def test_tanglish_evening_time():
    assert parse_time_text("maalai 6") == "18:00"
    assert parse_time_text("kaalai 9") == "09:00"
