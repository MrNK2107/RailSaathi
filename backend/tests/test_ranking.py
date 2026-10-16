from datetime import date

import pytest

from app.domain.enums import (
    BudgetPriority,
    CheckStatus,
    DateAnchor,
    Language,
    PassengerNeed,
    RecommendationCategory as Cat,
    TransferPreference,
    TravelClass,
    Verification,
)
from app.domain.journey import JourneyDetails, Place, TimeWindow
from app.ranking.recommender import Recommender
from tests.conftest import FIXED_NOW

CBE = Place(id="coimbatore", label="Coimbatore", kind="city", station_codes=["CBE"])
CHN = Place(id="chennai", label="Chennai", kind="city", station_codes=["MAS", "MS"])
BLR = Place(id="bengaluru", label="Bengaluru", kind="city", station_codes=["SBC", "BNC"])
SALEM = Place(id="salem", label="Salem", kind="city", station_codes=["SA"])


@pytest.fixture
def rec(provider):
    return Recommender(provider, min_transfer_minutes=30)


def deadline_journey(**kw) -> JourneyDetails:
    base = dict(origin=CBE, destination=CHN, journey_date=date(2026, 10, 11), passenger_count=2,
                arrival_deadline="09:00", deadline_strict=True, date_anchor=DateAnchor.ARRIVAL)
    return JourneyDetails(**{**base, **kw})


def by_label(result, label):
    return next(r for r in result.recommendations if label in r.labels)


def train_nos(rec_):
    return [leg.train_no for leg in rec_.option.legs]


def test_cheapest_eligible_respects_deadline_and_explains_exclusion(rec):
    result = rec.recommend(deadline_journey(budget_priority=BudgetPriority.MINIMIZE_COST), FIXED_NOW, Language.EN)
    cheapest = by_label(result, Cat.LOWEST_COST)
    assert train_nos(cheapest) == ["D103"]
    assert cheapest.total_fare == 590
    excluded_ids = {e.option_id for e in result.excluded}
    assert "CBE-MS-D105@2026-10-10" in excluded_ids
    assert any("D105" in n and "after the 09:00 deadline" in n for n in result.notes)
    for r in result.recommendations:
        assert all(c.status != CheckStatus.VIOLATED for c in r.hard_constraints)


def test_fastest_and_best_overall(rec):
    result = rec.recommend(deadline_journey(budget_priority=BudgetPriority.MINIMIZE_COST), FIXED_NOW, Language.EN)
    assert train_nos(by_label(result, Cat.FASTEST)) == ["D101"]
    assert train_nos(by_label(result, Cat.BEST_OVERALL)) == ["D103"]


def test_duplicate_categories_are_merged_into_one_card(rec):
    result = rec.recommend(deadline_journey(), FIXED_NOW, Language.EN)
    ids = [r.option.option_id for r in result.recommendations]
    assert len(ids) == len(set(ids))
    assert sum(len(r.labels) for r in result.recommendations) == 3


def test_minimize_time_priority_changes_best(rec):
    j = JourneyDetails(origin=CBE, destination=CHN, journey_date=date(2026, 10, 11), passenger_count=1,
                       budget_priority=BudgetPriority.MINIMIZE_TIME)
    result = rec.recommend(j, FIXED_NOW, Language.EN)
    assert train_nos(by_label(result, Cat.BEST_OVERALL)) == ["D107"]
    assert train_nos(by_label(result, Cat.FASTEST)) == ["D107"]


def test_soft_departure_window_preference_affects_ranking(rec):
    j = JourneyDetails(origin=CBE, destination=CHN, journey_date=date(2026, 10, 11), passenger_count=1,
                       departure_window=TimeWindow(start="13:00", end="16:00"))
    result = rec.recommend(j, FIXED_NOW, Language.EN)
    best = by_label(result, Cat.BEST_OVERALL)
    assert train_nos(best) == ["D109"]
    assert any("preferred window" in m for m in best.preference_matches)


def test_no_feasible_option_offers_relaxation(rec):
    j = deadline_journey(arrival_deadline="04:00")
    result = rec.recommend(j, FIXED_NOW, Language.EN)
    assert result.recommendations == []
    assert result.eligible_count == 0
    assert result.relax_suggestions[0].constraint == "arrival_deadline"


def test_strict_budget_filters_options(rec):
    result = rec.recommend(deadline_journey(budget_limit=620, budget_strict=True), FIXED_NOW, Language.EN)
    assert result.eligible_count == 2
    assert {tuple(train_nos(r)) for r in result.recommendations} <= {("D103",), ("D121", "D123")}


def test_strict_class_and_direct_only(rec):
    j = deadline_journey(class_preference=TravelClass.TWO_A, class_strict=True,
                         transfer_preference=TransferPreference.DIRECT_ONLY, transfer_strict=True)
    result = rec.recommend(j, FIXED_NOW, Language.EN)
    assert result.eligible_count == 2  # only direct trains offering 2A
    assert {tuple(train_nos(r)) for r in result.recommendations} <= {("D101",), ("D103",)}
    assert all(r.selected_class is TravelClass.TWO_A for r in result.recommendations)


def test_unverified_assistance_is_flagged_not_hidden(rec):
    mdu = Place(id="madurai", label="Madurai", kind="city", station_codes=["MDU"])
    j = deadline_journey(origin=mdu, passenger_needs=[PassengerNeed.ASSISTANCE_REQUESTED])
    result = rec.recommend(j, FIXED_NOW, Language.EN)
    assert result.recommendations, "unknown assistance must not hide journeys"
    first = result.recommendations[0]
    assert first.need_statuses[0].status is Verification.UNKNOWN
    assert "Chennai Egmore has not been verified" in first.unverified[0]


def test_verified_assistance_reported(rec):
    j = deadline_journey(passenger_needs=[PassengerNeed.ASSISTANCE_REQUESTED])
    result = rec.recommend(j, FIXED_NOW, Language.EN)
    direct = next(r for r in result.recommendations if train_nos(r) == ["D101"])
    assert direct.need_statuses[0].status is Verification.VERIFIED_SUPPORTED


def test_mandatory_assistance_marks_unknown_as_not_fully_compliant(rec):
    j = deadline_journey(passenger_needs=[PassengerNeed.ASSISTANCE_REQUESTED], assistance_mandatory=True)
    result = rec.recommend(j, FIXED_NOW, Language.EN)
    # Category picks prefer fully compliant journeys (D101/D103 have verified assistance).
    assert all(r.fully_compliant for r in result.recommendations)


def test_mandatory_assistance_not_supported_is_excluded(rec):
    j = JourneyDetails(origin=SALEM, destination=CHN, journey_date=date(2026, 10, 11), passenger_count=1,
                       passenger_needs=[PassengerNeed.ASSISTANCE_REQUESTED], assistance_mandatory=True)
    result = rec.recommend(j, FIXED_NOW, Language.EN)
    assert result.eligible_count == 0
    assert result.relax_suggestions[0].constraint == "mandatory_assistance"


def test_departed_trains_are_excluded(rec):
    j = JourneyDetails(origin=CBE, destination=CHN, journey_date=date(2026, 10, 10), passenger_count=1)
    result = rec.recommend(j, FIXED_NOW, Language.EN)
    assert "CBE-MAS-D107@2026-10-10" in {e.option_id for e in result.excluded}


def test_tamil_explanations(rec):
    result = rec.recommend(deadline_journey(), FIXED_NOW, Language.TA)
    assert "பரிந்துரைக்கப்படுகிறது" in result.recommendations[0].explanation


def test_demo_results_keep_their_mode_but_no_demo_wording(rec):
    result = rec.recommend(deadline_journey(), FIXED_NOW, Language.EN)
    assert result.provenance.mode.value == "demo"
    assert not any("demo" in lim.lower() for lim in result.limitations)  # demo data is not labelled in the UI


def test_constraint_change_changes_hash(rec):
    a = rec.recommend(deadline_journey(), FIXED_NOW, Language.EN)
    b = rec.recommend(deadline_journey(destination=BLR), FIXED_NOW, Language.EN)
    assert a.constraints_hash != b.constraints_hash
    assert all(r.option.legs[-1].to_code in {"SBC", "BNC"} for r in b.recommendations)
