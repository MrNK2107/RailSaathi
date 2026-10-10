import pytest

from app.disruption.service import DisruptionError, DisruptionService, apply_event
from app.domain.enums import BudgetPriority, Language, RecommendationCategory as Cat
from app.ranking.recommender import Recommender
from tests.conftest import FIXED_NOW
from tests.test_ranking import deadline_journey

D103 = "CBE-MAS-D103@2026-10-10"
D101 = "CBE-MAS-D101@2026-10-10"


@pytest.fixture
def setup(provider, disruptions):
    rec = Recommender(provider, min_transfer_minutes=30)
    service = DisruptionService(disruptions, rec)
    journey = deadline_journey(budget_priority=BudgetPriority.MINIMIZE_COST)
    current = rec.recommend(journey, FIXED_NOW, Language.EN)
    return service, journey, current


def test_delay_makes_selected_journey_miss_deadline(setup):
    service, journey, current = setup
    assert any(r.option.option_id == D103 and Cat.LOWEST_COST in r.labels for r in current.recommendations)
    new_set, info = service.reassess(journey, current, D103, "SIM-DELAY-D103", FIXED_NOW, Language.EN)
    assert info.selected_option_affected
    assert info.original_still_valid is False
    assert info.requires_confirmation
    assert info.simulated and info.summary.startswith("SIMULATED EVENT")
    assert "09:15" in info.changes[0]
    assert D103 in {e.option_id for e in new_set.excluded}
    assert D103 not in {r.option.option_id for r in new_set.recommendations}
    assert new_set.recommendations  # alternatives offered


def test_minor_delay_keeps_plan_valid(setup):
    service, journey, current = setup
    _, info = service.reassess(journey, current, D101, "SIM-DELAY-D101", FIXED_NOW, Language.EN)
    assert info.selected_option_affected
    assert info.original_still_valid is True


def test_unaffected_selection(setup):
    service, journey, current = setup
    _, info = service.reassess(journey, current, D101, "SIM-DELAY-D103", FIXED_NOW, Language.EN)
    assert not info.selected_option_affected
    assert info.original_still_valid is True


def test_cancellation_removes_option(provider, setup):
    service, journey, current = setup
    options = provider.search(["CBE"], ["MAS"], [FIXED_NOW.date()])
    remaining = apply_event(options, service._source.get_event("SIM-CANCEL-D107"))
    assert all(leg.train_no != "D107" for o in remaining for leg in o.legs)


def test_delay_breaks_connection(provider, disruptions):
    options = provider.search(["CBE"], ["MAS"], [FIXED_NOW.date()])
    delayed = apply_event(options, disruptions.get_event("SIM-DELAY-D121"))
    transfer = next(o for o in delayed if o.transfers == 1)
    assert transfer.min_transfer_minutes == -20
    assert transfer.simulated_change.startswith("Simulated")


def test_auto_picks_event_affecting_selection(setup):
    service, _, current = setup
    assert service.pick_event(None, current, D103).train_no == "D103"


def test_no_suitable_replacement(provider, disruptions):
    from app.domain.enums import TransferPreference, TravelClass
    rec = Recommender(provider, min_transfer_minutes=30)
    service = DisruptionService(disruptions, rec)
    # Only D103 offers 2A within a strict ₹2,300 budget for two passengers.
    journey = deadline_journey(class_preference=TravelClass.TWO_A, class_strict=True,
                               transfer_preference=TransferPreference.DIRECT_ONLY, transfer_strict=True,
                               budget_limit=2300, budget_strict=True)
    current = rec.recommend(journey, FIXED_NOW, Language.EN)
    assert [r.option.option_id for r in current.recommendations] == [D103]
    new_set, info = service.reassess(journey, current, D103, None, FIXED_NOW, Language.EN)
    assert info.original_still_valid is False
    assert new_set.eligible_count == 0
    assert new_set.recommendations == []
    assert new_set.relax_suggestions


def test_unknown_event_rejected(setup):
    service, journey, current = setup
    with pytest.raises(DisruptionError) as err:
        service.reassess(journey, current, D103, "NOPE", FIXED_NOW, Language.EN)
    assert err.value.code == "unknown_event"
