from datetime import date

from app.domain.enums import DataMode, TravelClass


def test_demo_search_builds_dated_options(provider):
    options = provider.search(["CBE"], ["MAS", "MS"], [date(2026, 10, 10)])
    ids = {o.option_id for o in options}
    assert "CBE-MAS-D101@2026-10-10" in ids
    d101 = next(o for o in options if o.option_id == "CBE-MAS-D101@2026-10-10")
    assert d101.arrival.isoformat() == "2026-10-11T05:20:00+05:30"
    assert d101.duration_minutes == 490
    assert d101.fares[TravelClass.SL] == 315
    assert d101.provenance.mode is DataMode.DEMO


def test_transfer_option_has_buffer(provider):
    options = provider.search(["CBE"], ["MAS"], [date(2026, 10, 10)])
    transfer = next(o for o in options if o.transfers == 1)
    assert transfer.min_transfer_minutes == 50
    assert transfer.station_codes == ["CBE", "ED", "MAS"]


def test_search_returns_nothing_for_unknown_route(provider):
    assert provider.search(["KPD"], ["CBE"], [date(2026, 10, 10)]) == []


def test_resolve_city_alias(resolver):
    res = resolver.resolve("Kovai")
    assert res.status == "resolved"
    assert res.place.id == "coimbatore"


def test_resolve_station_alias_and_code(resolver):
    assert resolver.resolve("Chennai Egmore").place.id == "MS"
    assert resolver.resolve("mas").place.id == "MAS"


def test_resolve_tamil_name(resolver):
    assert resolver.resolve("மதுரை").place.id == "madurai"


def test_misspelling_is_ambiguous_not_substituted(resolver):
    res = resolver.resolve("Coimbatur")
    assert res.status == "ambiguous"
    assert res.place is None
    assert any(c.id == "coimbatore" for c in res.candidates)


def test_partial_name_matching_several_places_is_ambiguous(resolver):
    res = resolver.resolve("Bengaluru C")
    assert res.status == "ambiguous"
    assert {c.id for c in res.candidates} >= {"SBC", "BNC"}


def test_unknown_place_not_found(resolver):
    assert resolver.resolve("Ooty").status == "not_found"


def test_find_in_text_prefers_longest_alias(resolver):
    found = resolver.find_in_text("from Chennai Central to Kovai")
    assert [m.place.id for m in found] == ["MAS", "coimbatore"]


def test_find_in_text_tamil_suffix(resolver):
    found = resolver.find_in_text("கோவையிலிருந்து சென்னைக்கு")
    assert [m.place.id for m in found] == ["coimbatore", "chennai"]


def test_disruption_events_are_simulated(disruptions):
    events = disruptions.list_events()
    assert events and all(e.simulated and e.provenance.mode is DataMode.DEMO for e in events)
