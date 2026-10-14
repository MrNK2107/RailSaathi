"""journey/provider_adapter.py maps JourneyProvider results into the goal planner's leg model."""

from datetime import date, datetime, timedelta

from app.domain.enums import DataMode
from app.domain.options import DataProvenance, JourneyOption, Leg
from app.journey.provider_adapter import ProviderJourneyAdapter, option_to_candidate
from app.providers.railradar import UnconfiguredLiveProvider
from tests.conftest import IST

D = date(2026, 10, 10)


def test_maps_demo_option_legs_fares_and_provenance(provider):
    options = provider.search(["CBE"], ["MAS"], [D])
    option = next(o for o in options if o.option_id.startswith("CBE-MAS-D103"))
    cand = option_to_candidate(option)
    assert cand.option_id == option.option_id
    assert cand.train_number == "D103" and cand.origin_code == "CBE" and cand.destination_code == "MAS"
    assert cand.departure == option.departure and cand.departure.tzinfo is not None
    assert cand.arrival.date() == D + timedelta(days=1)
    assert cand.duration_minutes == option.duration_minutes and cand.transfers == 0
    assert cand.fares == {"SL": 295.0, "3A": 790.0, "2A": 1150.0}
    assert set(cand.classes) == {"SL", "3A", "2A"}  # classes fall back to the fare keys
    assert cand.provenance.mode == DataMode.DEMO


def test_multi_leg_option_keeps_every_leg(provider):
    option = next(o for o in provider.search(["CBE"], ["MAS"], [D]) if o.transfers == 1)
    cand = option_to_candidate(option)
    assert [leg.train_number for leg in cand.legs] == ["D121", "D123"]
    assert cand.train_number == "D121 + D123"
    assert cand.origin_code == "CBE" and cand.destination_code == "MAS"


def test_adapter_search_returns_candidates_with_set_provenance(provider):
    result = ProviderJourneyAdapter(provider, "Asia/Kolkata").search(["CBE"], ["MAS", "MS"], [D])
    assert result.error is None and result.candidates
    assert {c.departure.date() for c in result.candidates} == {D}
    assert result.provenance.mode == DataMode.DEMO and "demo" in result.provenance.source.lower()


def test_adapter_drops_options_not_departing_on_a_requested_date():
    """Day-of-week/date filter: a provider answer for another departure date is never used."""
    prov = DataProvenance(mode=DataMode.LIVE, source="test", as_of=datetime(2026, 10, 1, tzinfo=IST), note="n")

    def opt(day: date) -> JourneyOption:
        dep = datetime(day.year, day.month, day.day, 6, 0, tzinfo=IST)
        leg = Leg(train_no="12345", train_name="T", from_code="CBE", from_name="C", to_code="MAS", to_name="M",
                  departure=dep, arrival=dep + timedelta(hours=6))
        return JourneyOption(option_id=f"x@{day}", legs=[leg], departure=dep, arrival=leg.arrival,
                             duration_minutes=360, transfers=0, station_codes=["CBE", "MAS"], provenance=prov)

    class Loose:
        def search(self, o, d, dates):
            return [opt(D), opt(D + timedelta(days=3))]

        def provenance(self):
            return prov

    result = ProviderJourneyAdapter(Loose(), "Asia/Kolkata").search(["CBE"], ["MAS"], [D])
    assert [c.option_id for c in result.candidates] == [f"x@{D}"]


def test_provider_error_becomes_unavailable_provenance_not_an_exception():
    adapter = ProviderJourneyAdapter(UnconfiguredLiveProvider("RailRadar API key is not configured"), "Asia/Kolkata")
    result = adapter.search(["CBE"], ["MAS"], [D])
    assert result.candidates == [] and result.error == "not_configured"
    assert result.provenance.mode == DataMode.UNAVAILABLE
    assert result.provenance.note  # a reason the UI can show
