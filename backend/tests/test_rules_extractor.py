import pytest

from app.domain.enums import BudgetPriority, DateAnchor, PassengerNeed as N, TransferPreference
from app.intent.rules import RuleBasedExtractor


@pytest.fixture(scope="module")
def ex(resolver):
    return RuleBasedExtractor(resolver)


def test_scenario_a_reach_chennai_before_9(ex):
    u = ex.extract("I need to reach Chennai before 9 AM tomorrow.")
    assert u.destination_text == "Chennai"
    assert u.origin_text is None
    assert u.date_text == "tomorrow"
    assert u.arrival_deadline_text.strip() == "9 am"
    assert u.deadline_strict is True
    assert u.date_anchor is DateAnchor.ARRIVAL


def test_full_example_with_mother_and_assistance(ex):
    u = ex.extract("I need to reach Chennai before 9 AM tomorrow. I want the cheapest option, "
                   "and I am travelling with my mother, who needs assistance.")
    assert u.passenger_count == 2
    assert u.budget_priority is BudgetPriority.MINIMIZE_COST
    assert N.ASSISTANCE_REQUESTED in u.needs_add
    assert u.assistance_mandatory is None


def test_from_and_to(ex):
    u = ex.extract("from Coimbatore to Bengaluru on 20 Oct, 3 passengers")
    assert (u.origin_text, u.destination_text) == ("Coimbatore", "Bengaluru")
    assert u.date_text == "20 oct"
    assert u.passenger_count == 3


def test_tamil_script(ex):
    u = ex.extract("நாளை கோவையிலிருந்து சென்னைக்கு காலை 9 மணிக்குள் போக வேண்டும், அம்மா உடன்")
    assert u.origin_text == "கோவை"
    assert u.destination_text == "சென்னை"
    assert u.date_text == "நாளை"
    assert u.arrival_deadline_text == "காலை 9"
    assert u.passenger_count == 2


def test_tanglish(ex):
    u = ex.extract("naalai Kovai la irundhu Chennai ku poganum")
    assert u.origin_text == "Kovai" and u.destination_text == "Chennai"


def test_bare_answer_fills_pending_field(ex):
    assert ex.extract("Coimbatore.", pending_field="origin").origin_text == "Coimbatore"
    assert ex.extract("3", pending_field="passenger_count").passenger_count == 3
    assert ex.extract("two of us", pending_field="passenger_count").passenger_count == 2
    assert ex.extract("next friday", pending_field="journey_date").date_text == "next friday"


def test_unknown_place_kept_as_raw_text(ex):
    assert ex.extract("from Ooty to Chennai").origin_text == "Ooty"


def test_corrections(ex):
    u = ex.extract("Change the date to Sunday.")
    assert u.is_correction and u.date_text == "sunday" and u.destination_text is None
    assert ex.extract("Actually, there are three passengers.").passenger_count == 3
    u = ex.extract("I prefer AC Chair Car.")
    assert u.class_text == "ac chair car" and u.class_strict is False
    u = ex.extract("Change my destination to Bengaluru.")
    assert u.destination_text == "Bengaluru" and u.is_correction


def test_forget_budget_limit(ex):
    u = ex.extract("Forget the budget limit.")
    assert u.intent == "relax_constraint"
    assert "budget_limit" in u.clear_fields
    assert u.budget_priority is None


def test_strict_budget_and_direct(ex):
    u = ex.extract("maximum 1500 rupees, direct trains only")
    assert u.budget_limit == 1500 and u.budget_strict is True
    assert u.transfer_preference is TransferPreference.DIRECT_ONLY and u.transfer_strict


def test_intents(ex):
    assert ex.extract("cancel").intent == "cancel"
    assert ex.extract("start over").intent == "restart"
    assert ex.extract("Yes, confirm").intent == "confirm"
    assert ex.extract("show me the options").intent == "request_recommendations"
    u = ex.extract("I'll take option 2")
    assert u.intent == "select_option" and u.selected_option == "2"
    assert ex.extract("choose the cheapest").selected_option == "lowest_cost"


def test_children_without_count_does_not_guess(ex):
    u = ex.extract("travelling with kids to Madurai")
    assert u.passenger_count is None
    assert N.TRAVELLING_WITH_CHILDREN in u.needs_add


def test_wheelchair_implies_assistance_and_mandatory(ex):
    u = ex.extract("my father uses a wheelchair, assistance is mandatory")
    assert {N.WHEELCHAIR, N.ASSISTANCE_REQUESTED} <= set(u.needs_add)
    assert u.assistance_mandatory is True


def test_unsupported_preferences(ex):
    u = ex.extract("I want a window seat in first AC")
    assert "seat selection" in u.unsupported_requests
    assert "First AC (1A) class" in u.unsupported_requests


def test_departure_preferences(ex):
    u = ex.extract("leave after 6 pm and prefer daytime? no, evening train")
    assert u.departure_after_text.strip() == "6 pm"
    assert u.departure_period == "evening"


def test_soft_deadline(ex):
    assert ex.extract("ideally reach by 8 am").deadline_strict is False


def test_tanglish_deadline(ex):
    u = ex.extract("Naalaiku Kovai la irundhu Chennai ku amma kooda poganum, kaalai 9 manikku munnadi")
    assert u.arrival_deadline_text == "kaalai 9"
    assert u.date_anchor is DateAnchor.ARRIVAL
    assert ex.extract("maalai 6 mani kulla reach").arrival_deadline_text == "maalai 6"
