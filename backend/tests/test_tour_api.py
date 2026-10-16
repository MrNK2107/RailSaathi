"""Virtual tour data: GET /api/stations/{id}/tour, GET /api/client-config and the `panoramas` authoring command
(Street View metadata endpoint mocked with httpx.MockTransport; nothing contacts Google)."""

import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.clock import FixedClock
from app.config import STATIONS_DIR, Settings
from app.container import build_container
from app.llm.mock import MockVisionLocalizer
from app.main import create_app
from tests.conftest import FIXED_NOW
from tests.station_fixture import METADATA, station_root, write_station

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import stations as cli  # noqa: E402

MPP = 0.17794


def make(root=STATIONS_DIR, vision=None, **kw) -> TestClient:
    settings = Settings(_env_file=None, stations_uri=str(root), **kw)
    container = build_container(settings, clock=FixedClock(FIXED_NOW), use_configured_llm=False, vision=vision)
    return TestClient(create_app(settings, container))


# ---- tour ------------------------------------------------------------------------------------------------------

def test_chennai_tour_has_levels_areas_graph_in_metres_and_provenance():
    body = make(vision=MockVisionLocalizer([])).get("/api/stations/chennai_central/tour").json()
    assert body["station_id"] == "chennai_central" and body["layout_basis"] == "schematic"
    assert body["routing_enabled"] is True and body["ar_enabled"] is True and body["ar_guidance_available"] is True
    assert body["map"] == {"url": "/api/stations/chennai_central/map", "width_px": 1821, "height_px": 864}
    assert body["scale"]["metres_per_pixel"] == MPP and body["scale"]["verification"] == "pending"
    assert body["scale"]["width_m"] == round(1821 * MPP, 2)
    assert body["geo_reference"]["anchor"] == {"lat": 13.0825, "lon": 80.275, "x": 0.49039, "y": 0.49537}
    assert body["levels"] == [{"level": 0, "name": "Ground level (concourse and platforms)", "elevation_m": 0.0}]
    assert len(body["nodes"]) == 44 and len(body["edges"]) == 52
    node = next(n for n in body["nodes"] if n["id"] == "concourse_centre")
    assert node["position_m"] == [round(0.49039 * 1821 * MPP, 2), round(0.49537 * 864 * MPP, 2)]
    assert node["cues"] and all(c["verified_on"] is None and c["source"] for c in node["cues"])
    edge = next(e for e in body["edges"] if e["id"] == "edge_004")
    assert edge["from"] == "cj_south" and edge["path_type"] == "stairs" and len(edge["geometry_m"]) >= 2
    kinds = {a["kind"] for a in body["areas"]}
    assert kinds == {"platform", "concourse", "building_footprint", "track_bed"}
    platform = next(a for a in body["areas"] if a["id"] == "platform_10_area")
    assert platform["polygon_m"][0] == platform["polygon_m"][-1] and len(platform["polygon_m"]) == 5
    assert body["panoramas"] == [] and "scripts/stations.py panoramas" in body["panoramas_note"]
    assert body["provenance"]["mode"] == "cached" and "schematic" in body["provenance"]["source"]


def test_tour_reports_ar_unavailable_without_a_localizer_or_flag():
    assert make().get("/api/stations/chennai_central/tour").json()["ar_guidance_available"] is False
    flag_off = make(vision=MockVisionLocalizer([]), ar_guidance_enabled="")
    assert flag_off.get("/api/stations/chennai_central/tour").json()["ar_guidance_available"] is False


@pytest.mark.parametrize("station_id", ["chennai_egmore", "ksr_bengaluru", "hyderabad_deccan"])
def test_untraced_stations_serve_tour_data_with_routing_and_ar_off(station_id):
    body = make(vision=MockVisionLocalizer([])).get(f"/api/stations/{station_id}/tour").json()
    assert body["routing_enabled"] is False and body["ar_enabled"] is False
    assert body["ar_guidance_available"] is False and body["nodes"]


def test_tour_without_a_scale_has_no_metre_coordinates(tmp_path):
    root = station_root(tmp_path)
    write_station(root, metadata={k: v for k, v in METADATA.items() if k != "map_scale"})
    body = make(root).get("/api/stations/test_station/tour").json()
    assert body["scale"] is None and body["geo_reference"] is None
    assert all(n["position_m"] is None for n in body["nodes"])
    assert all(e["geometry_m"] is None for e in body["edges"])


def test_tour_of_unknown_station_is_404():
    assert make().get("/api/stations/atlantis/tour").status_code == 404


# ---- client config ---------------------------------------------------------------------------------------------

def test_client_config_without_key_or_localizer():
    body = make().get("/api/client-config").json()
    assert body == {"google_maps_browser_key": None,
                    "features": {"ar_guidance_stations": [], "ar_capable_stations": ["chennai_central"],
                                 "simulate_closures": True}}


def test_client_config_returns_only_the_browser_key_and_flags():
    client = make(vision=MockVisionLocalizer([]), google_maps_browser_key="AIza-browser",
                  session_signing_key="s" * 32, railradar_api_key="rr-secret", gemini_api_key="gm-secret")
    res = client.get("/api/client-config")
    assert res.json() == {"google_maps_browser_key": "AIza-browser",
                          "features": {"ar_guidance_stations": ["chennai_central"],
                                       "ar_capable_stations": ["chennai_central"], "simulate_closures": True}}
    for secret in ("s" * 32, "rr-secret", "gm-secret"):
        assert secret not in res.text


def test_client_config_respects_the_per_station_flag():
    client = make(vision=MockVisionLocalizer([]), ar_guidance_enabled="ksr_bengaluru")
    assert client.get("/api/client-config").json()["features"]["ar_guidance_stations"] == []


def test_client_config_lists_ar_capable_stations_whatever_the_flags(tmp_path):
    """`ar_capable_stations` follows the station data only: AR flag off, no vision service, or production."""
    for client in (make(), make(vision=MockVisionLocalizer([]), ar_guidance_enabled="ksr_bengaluru")):
        features = client.get("/api/client-config").json()["features"]
        assert features["ar_guidance_stations"] == [] and features["ar_capable_stations"] == ["chennai_central"]
    # Production keeps AR off unless AR_GUIDANCE_ENABLED names the station (the gate is unchanged), but the station
    # is still listed as capable.
    prod = make(vision=MockVisionLocalizer([]), app_env="production", session_signing_key="s" * 32,
                railradar_api_key="rr", data_provider="railradar")
    features = prod.get("/api/client-config").json()["features"]
    assert features["ar_guidance_stations"] == [] and features["ar_capable_stations"] == ["chennai_central"]
    # A station whose data does not opt in is never listed.
    assert make(station_root(tmp_path)).get("/api/client-config").json()["features"]["ar_capable_stations"] == []


def test_client_config_simulate_closures_follows_the_route_gate():
    # The same flag that makes POST /api/navigation/route refuse simulate_closures with 403 simulation_disabled.
    off = make(public_disruption_simulation=False)
    assert off.get("/api/client-config").json()["features"]["simulate_closures"] is False
    route = {"station_id": "chennai_central", "source": "ent_wall_tax", "destination": "platform_10",
             "simulate_closures": ["edge_004"]}
    assert off.post("/api/navigation/route", json=route).json()["error"]["code"] == "simulation_disabled"
    assert make().get("/api/client-config").json()["features"]["simulate_closures"] is True


# ---- panoramas CLI ---------------------------------------------------------------------------------------------

ANCHOR = (13.0825, 80.275)


def _transport(responses):
    """responses(lat, lon) -> JSON body. Records each request URL."""
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        lat, lon = (float(v) for v in request.url.params["location"].split(","))
        return httpx.Response(200, json=responses(lat, lon))

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def test_panoramas_lists_distinct_panos_with_plan_position_and_nearest_node():
    def responses(lat, lon):
        if lat > ANCHOR[0] + 0.0002:  # north of the station: a Google pano on Wall Tax Road
            return {"status": "OK", "pano_id": "pano_north", "location": {"lat": 13.0835, "lng": 80.275},
                    "date": "2024-03", "copyright": "© Google"}
        if lat < ANCHOR[0] - 0.0002:
            return {"status": "OK", "pano_id": "sphere_south", "location": {"lat": 13.0815, "lng": 80.2751},
                    "copyright": "© A Contributor"}
        return {"status": "ZERO_RESULTS"}

    client, seen = _transport(responses)
    panos = cli.find_panoramas(STATIONS_DIR, "chennai_central", "KEY123", radius_m=60, step_m=30, client=client)
    assert {p["pano_id"] for p in panos} == {"pano_north", "sphere_south"}
    north = next(p for p in panos if p["pano_id"] == "pano_north")
    assert north["kind"] == "street_view" and north["date"] == "2024-03"
    # 111 m north of the anchor lies above the plan's top edge (the plan is about 154 m tall).
    assert north["plan_position"][0] == pytest.approx(0.49039, abs=1e-4) and north["plan_position"][1] < 0
    assert north["inside_plan"] is False and north["nearest_node"] == "ent_wall_tax"
    assert next(p for p in panos if p["pano_id"] == "sphere_south")["kind"] == "photosphere"
    assert len(seen) == len(cli.sample_points(60, 30))
    assert all(u.host == "maps.googleapis.com" and u.path == "/maps/api/streetview/metadata" for u in seen)
    assert all(u.params["key"] == "KEY123" and u.params["source"] == "default" for u in seen)


def test_anchor_maps_back_to_its_plan_position():
    station, metadata = cli._load_station(STATIONS_DIR, "chennai_central")
    geo = metadata.model_extra["geo_reference"]
    assert cli.latlon_to_plan(station, geo, MPP, *ANCHOR) == (0.49039, 0.49537)
    lat, lon = cli.offset_latlon(*ANCHOR, east_m=1821 * MPP, north_m=0)  # one plan width east
    assert cli.latlon_to_plan(station, geo, MPP, lat, lon)[0] == pytest.approx(1.49039, abs=1e-3)


def test_panoramas_stops_on_a_denied_key_without_printing_it():
    client, _ = _transport(lambda lat, lon: {"status": "REQUEST_DENIED", "error_message": "bad key"})
    with pytest.raises(cli.PanoramaLookupError, match="REQUEST_DENIED"):
        cli.find_panoramas(STATIONS_DIR, "chennai_central", "KEY123", client=client)

    def boom(request):
        raise httpx.ConnectError("failed for " + str(request.url))

    failing = httpx.Client(transport=httpx.MockTransport(boom))
    with pytest.raises(cli.PanoramaLookupError) as err:
        cli.find_panoramas(STATIONS_DIR, "chennai_central", "KEY123", client=failing)
    assert "KEY123" not in str(err.value) and err.value.__cause__ is None


def test_panoramas_command_needs_a_key_and_writes_metadata_only(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    assert cli.main(["panoramas", "chennai_central"]) == 2
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "KEY123")
    client, _ = _transport(lambda lat, lon: {"status": "OK", "pano_id": "p1", "copyright": "© Google",
                                             "location": {"lat": lat, "lng": lon}})
    monkeypatch.setattr(httpx, "Client", lambda **kw: client)  # find_panoramas imports httpx lazily
    out = tmp_path / "panos.json"
    assert cli.main(["panoramas", "chennai_central", "--radius", "30", "--out", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["station_id"] == "chennai_central" and [p["pano_id"] for p in doc["panoramas"]] == ["p1"]
    assert "KEY123" not in out.read_text(encoding="utf-8") and "KEY123" not in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == [out]  # no imagery written
