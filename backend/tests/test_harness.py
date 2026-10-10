from datetime import timedelta

import pytest

from app.clock import FixedClock
from app.config import Settings
from app.container import build_container
from app.domain.enums import Language, PassengerNeed, WorkflowStatus as S
from app.harness.errors import PlannerError
from tests.conftest import FIXED_NOW


@pytest.fixture
def planner():
    settings = Settings(_env_file=None)
    return build_container(settings, clock=FixedClock(FIXED_NOW), use_configured_llm=False).planner


def start(planner, lang=Language.EN):
    return planner.create_session(lang).state.session_id


def say(planner, sid, text, lang=None):
    return planner.handle_message(sid, text, lang)


def test_scenario_a_asks_only_for_missing_details_then_recommends(planner):
    sid = start(planner)
    r = say(planner, sid, "I need to reach Chennai before 9 AM tomorrow.")
    assert r.state.status is S.COLLECTING_DETAILS
    assert r.state.pending_question == "origin"
    assert r.assistant_message == "Where will you be travelling from?"
    assert r.state.journey.destination.id == "chennai"
    assert r.state.journey.arrival_deadline == "09:00"
    r = say(planner, sid, "Coimbatore")
    assert r.state.journey.origin.id == "coimbatore"
    assert r.state.pending_question == "passenger_count"
    r = say(planner, sid, "2")
    assert r.state.status is S.PRESENTING_RECOMMENDATIONS
    assert r.state.recommendations.recommendations
    assert r.extraction_source == "rules"


def test_preference_question_asked_once_when_no_priorities(planner):
    sid = start(planner)
    r = say(planner, sid, "from Coimbatore to Chennai tomorrow, 1 passenger")
    assert r.state.pending_question == "preferences"
    r = say(planner, sid, "no preference")
    assert r.state.status is S.PRESENTING_RECOMMENDATIONS


def test_scenario_b_cheapest_with_mandatory_deadline(planner):
    sid = start(planner)
    r = say(planner, sid, "Find the cheapest option from Coimbatore to Chennai, but I must reach before 9 AM "
                          "tomorrow. 2 passengers")
    rs = r.state.recommendations
    cheapest = next(x for x in rs.recommendations if "lowest_cost" in x.labels)
    assert cheapest.option.legs[0].train_no == "D103"
    assert "Cheaper option excluded" in r.assistant_message and "D105" in r.assistant_message


def test_scenario_c_assistance_need_preserved_and_unverified_reported(planner):
    sid = start(planner)
    say(planner, sid, "I am travelling with my mother, and she needs assistance.")
    r = say(planner, sid, "to Chennai from Madurai tomorrow before 9 am")
    j = r.state.journey
    assert PassengerNeed.ASSISTANCE_REQUESTED in j.passenger_needs
    assert j.passenger_count == 2
    assert r.state.status is S.PRESENTING_RECOMMENDATIONS
    assert "not verified" in r.assistant_message
    assert all("booked" not in u for rec in r.state.recommendations.recommendations for u in rec.unverified)


def _ready(planner):
    sid = start(planner)
    r = say(planner, sid, "from Coimbatore to Chennai, reach before 9 am tomorrow, cheapest, 2 passengers")
    assert r.state.status is S.PRESENTING_RECOMMENDATIONS
    return sid, r


def test_scenario_d_destination_correction_preserves_other_fields(planner):
    sid, before = _ready(planner)
    r = say(planner, sid, "Change my destination to Bengaluru.")
    j = r.state.journey
    assert j.destination.id == "bengaluru"
    assert j.origin.id == "coimbatore" and j.passenger_count == 2 and j.arrival_deadline == "09:00"
    assert r.state.recommendations.constraints_hash != before.state.recommendations.constraints_hash
    assert all(x.option.legs[-1].to_code in ("SBC", "BNC") for x in r.state.recommendations.recommendations)
    assert "Updated: destination" in r.assistant_message


def test_date_and_passenger_corrections(planner):
    sid, _ = _ready(planner)
    r = say(planner, sid, "Change the date to Sunday.")
    assert r.state.journey.journey_date.isoformat() == "2026-10-11"
    r = say(planner, sid, "Actually, there are three passengers.")
    assert r.state.journey.passenger_count == 3
    assert r.state.journey.destination.id == "chennai"


def test_select_and_confirm_produces_handoff(planner):
    sid, _ = _ready(planner)
    r = say(planner, sid, "option 1")
    assert r.state.status is S.AWAITING_CONFIRMATION
    r = say(planner, sid, "confirm")
    assert r.state.status is S.CONFIRMED
    handoff = r.state.confirmation.handoff
    assert handoff["module"] == "smart_passenger_planner"
    assert handoff["journey"]["passenger_count"] == 2
    assert "No ticket has been booked" in handoff["disclaimers"][0]
    assert handoff["data_provenance"]["mode"] == "demo"
    assert "No ticket has been booked" in r.assistant_message


def test_confirm_is_idempotent(planner):
    sid, _ = _ready(planner)
    say(planner, sid, "option 1")
    first = planner.confirm(sid, None)
    second = planner.confirm(sid, None)
    assert first.state.confirmation.confirmation_id == second.state.confirmation.confirmation_id


def test_confirm_before_recommendations_rejected(planner):
    sid = start(planner)
    r = say(planner, sid, "confirm")
    assert r.state.status is S.COLLECTING_DETAILS
    assert "choose one of the recommended options" in r.assistant_message
    with pytest.raises(PlannerError) as err:
        planner.confirm(sid, None)
    assert err.value.code == "not_ready"


def test_stale_recommendations_cannot_be_confirmed(planner):
    sid, _ = _ready(planner)
    say(planner, sid, "option 1")
    planner.engine.clock = FixedClock(FIXED_NOW + timedelta(minutes=45))
    with pytest.raises(PlannerError) as err:
        planner.confirm(sid, None)
    assert err.value.code == "stale_recommendations"


def test_scenario_e_reassessment_requires_new_confirmation(planner):
    sid, r = _ready(planner)
    d103 = next(x for x in r.state.recommendations.recommendations if x.option.legs[0].train_no == "D103")
    planner.select(sid, d103.option.option_id)
    planner.confirm(sid, None)
    r = planner.reassess(sid, "SIM-DELAY-D103")
    assert r.state.status is S.PRESENTING_RECOMMENDATIONS
    assert r.state.reassessment.original_still_valid is False
    assert r.state.reassessment.simulated
    assert r.state.confirmation.selected_option_id == d103.option.option_id  # not replaced automatically
    assert r.assistant_message.startswith("SIMULATED EVENT")
    alt = r.state.recommendations.recommendations[0].option.option_id
    planner.select(sid, alt)
    confirmed = planner.confirm(sid, None).state
    assert confirmed.confirmation.handoff["replaces_confirmation_id"]


def test_scenario_g_no_feasible_and_relax(planner):
    sid = start(planner)
    r = say(planner, sid, "from Coimbatore to Chennai tomorrow, must reach before 4 am, 1 passenger")
    assert r.state.status is S.NO_FEASIBLE_OPTIONS
    assert "No option in the current demo dataset" in r.assistant_message
    assert "Allow arrival after your deadline" in r.assistant_message
    r = say(planner, sid, "remove the deadline")
    assert r.state.journey.arrival_deadline is None
    assert r.state.status is S.PRESENTING_RECOMMENDATIONS


def test_ambiguous_station_clarified_by_number(planner):
    sid = start(planner)
    r = say(planner, sid, "to Coimbatur")
    assert r.state.status is S.NEEDS_CLARIFICATION
    assert "1) Coimbatore" in r.assistant_message
    r = say(planner, sid, "1")
    assert r.state.journey.destination.id == "coimbatore"


def test_unknown_station_lists_available(planner):
    sid = start(planner)
    r = say(planner, sid, "from Ooty to Chennai")
    assert "Ooty" in r.assistant_message and "Madurai" in r.assistant_message


def test_cancel_and_restart(planner):
    sid, _ = _ready(planner)
    r = say(planner, sid, "cancel")
    assert r.state.status is S.CANCELLED and r.state.recommendations is None
    r = say(planner, sid, "to Madurai")
    assert r.state.status is S.CANCELLED
    r = say(planner, sid, "start over")
    assert r.state.status is S.COLLECTING_DETAILS
    assert r.state.journey.destination is None


def test_language_preserved_and_switchable(planner):
    sid = start(planner, Language.TA)
    r = say(planner, sid, "சென்னைக்கு நாளை")
    assert r.state.language is Language.TA
    assert r.assistant_message == "நீங்கள் எங்கிருந்து பயணம் செய்கிறீர்கள்?"
    r = say(planner, sid, "Coimbatore", Language.EN)
    assert r.state.language is Language.EN
    assert r.state.journey.destination.id == "chennai"  # state kept across language switch


def test_invalid_transition_rejected(planner):
    sid = start(planner)
    with pytest.raises(PlannerError) as err:
        planner.select(sid, "anything")
    assert err.value.code == "no_recommendations"
    state = planner.get(sid)
    from app.domain.transitions import InvalidTransitionError, ensure_transition
    with pytest.raises(InvalidTransitionError):
        ensure_transition(state.status, S.CONFIRMED)


def test_patch_journey_invalidates_and_recalculates(planner):
    sid, before = _ready(planner)
    r = planner.patch_journey(sid, {"passenger_count": 4}, {})
    assert r.state.journey.passenger_count == 4
    assert r.state.journey.field_sources["passenger_count"] == "edited"
    assert r.state.recommendations.constraints_hash != before.state.recommendations.constraints_hash


def test_audit_records_transitions_without_message_text(planner):
    sid, _ = _ready(planner)
    events = planner.engine.audit.list(sid)
    assert any(e.type == "transition" and e.to_status == "presenting_recommendations" for e in events)
    assert all("Coimbatore" not in str(e.detail) for e in events)


def test_unsupported_request_noted(planner):
    sid = start(planner)
    r = say(planner, sid, "I want a window seat to Chennai")
    assert "seat selection" in r.assistant_message
    assert r.state.journey.destination.id == "chennai"


def test_relaxing_via_patch_recalculates_without_extra_question(planner):
    sid = start(planner)
    r = say(planner, sid, "from Coimbatore to Chennai tomorrow, must reach before 4 am, 1 passenger")
    assert r.state.status is S.NO_FEASIBLE_OPTIONS
    r = planner.patch_journey(sid, {"arrival_deadline": None}, {})
    assert r.state.status is S.PRESENTING_RECOMMENDATIONS


def test_session_expires_after_ttl():
    clock = FixedClock(FIXED_NOW)
    planner = build_container(Settings(_env_file=None, session_ttl_minutes=5), clock=clock,
                              use_configured_llm=False).planner
    sid = start(planner)
    planner.engine.clock = FixedClock(FIXED_NOW + timedelta(minutes=10))
    planner.store._clock = planner.engine.clock
    with pytest.raises(PlannerError) as err:
        planner.get(sid)
    assert err.value.code == "session_expired"


def test_strict_budget_class_and_direct_from_chat(planner):
    sid = start(planner)
    r = say(planner, sid, "from Coimbatore to Chennai tomorrow, 1 passenger, maximum 1200 rupees, "
                          "direct trains only, AC 3 tier")
    j = r.state.journey
    assert j.budget_limit == 1200 and j.budget_strict and j.transfer_strict and j.class_preference == "3A"
    assert all(rec.option.transfers == 0 and rec.total_fare <= 1200 for rec in r.state.recommendations.recommendations)


def test_mandatory_assistance_with_unverified_options_is_explained(planner):
    sid = start(planner)
    r = say(planner, sid, "from Madurai to Chennai tomorrow before 9 am, 2 passengers, my mother needs "
                          "assistance, assistance is mandatory")
    assert r.state.journey.assistance_mandatory
    assert "not fully compliant" in r.assistant_message
