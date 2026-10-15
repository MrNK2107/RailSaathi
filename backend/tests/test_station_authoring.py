"""Authored stations: honest schematic basis, provenance on navigation responses, national-only helplines."""

import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api.navigation import PROVENANCE_SOURCE
from app.config import STATIONS_DIR
from app.main import create_app
from tests.test_navigation_api import ROUTE, make

ALLOWED_NATIONAL = {"139", "182", "112", "1098"}
STATION_IDS = sorted(p.name for p in STATIONS_DIR.iterdir() if (p / "station.json").is_file())


def _load(station_id, name):
    return json.loads((STATIONS_DIR / station_id / name).read_text(encoding="utf-8"))


def test_at_least_three_stations_are_authored():
    assert len(STATION_IDS) >= 3 and "chennai_central" in STATION_IDS


@pytest.mark.parametrize("station_id", STATION_IDS)
def test_station_declares_schematic_layout_and_cites_sources(station_id):
    info, meta = _load(station_id, "info.json"), _load(station_id, "metadata.json")
    assert info["layout_basis"] == "schematic" and "not surveyed" in info["layout_note"]
    assert meta["layout_basis"] == "schematic" and meta["data_status"] == "schematic"
    sources = info["facts"]["sources"]
    assert sources and all(s["url"].startswith("https://") for s in sources)


@pytest.mark.parametrize("station_id", STATION_IDS)
def test_no_unsourced_step_free_claim(station_id):
    station = _load(station_id, "station.json")
    assert all(x["step_free"] == "unknown" for x in station["nodes"] + station["edges"])


@pytest.mark.parametrize("station_id", STATION_IDS)
def test_map_is_a_png_of_the_declared_size(station_id):
    station = _load(station_id, "station.json")
    with Image.open(STATIONS_DIR / station_id / "map.png") as im:
        assert im.format == "PNG" and im.size == (station["map"]["width"], station["map"]["height"])


@pytest.mark.parametrize("station_id", STATION_IDS)
def test_helplines_are_national_numbers_with_a_source_url(station_id):
    for h in _load(station_id, "info.json").get("helplines", []):
        assert h["number"] in ALLOWED_NATIONAL, h
        assert h["sources"] and all(s["url"].startswith("https://") for s in h["sources"]), h


def _bundled_client():
    from app.config import Settings
    from app.container import build_container

    settings = Settings(_env_file=None, stations_uri=str(STATIONS_DIR))
    return TestClient(create_app(settings, build_container(settings, use_configured_llm=False)))


@pytest.mark.parametrize("station_id", STATION_IDS)
def test_served_info_has_only_national_helplines(station_id):
    helplines = _bundled_client().get(f"/api/stations/{station_id}/info").json()["helplines"]
    assert helplines
    for h in helplines:
        assert (h["number"] or "") in ALLOWED_NATIONAL | {""}, h
        assert h["sources"] and all(s["url"].startswith("https://") for s in h["sources"]), h
    assert {h["number"] for h in helplines} >= {"139", "112", "1098"}


def test_common_helplines_all_carry_a_source_url():
    common = json.loads((STATIONS_DIR.parent / "common" / "helplines_india.json").read_text(encoding="utf-8"))
    for h in common["helplines"]:
        assert all(s["url"].startswith("https://") for s in h["sources"]), h["id"]


def test_provenance_on_detail_info_and_route(tmp_path):
    client, _ = make(tmp_path)
    for path in ("/api/stations/test_station", "/api/stations/test_station/info"):
        body = client.get(path).json()
        prov = body["provenance"]
        assert prov["mode"] == "cached" and prov["source"] == PROVENANCE_SOURCE
        assert "schematic" in prov["note"] and "not to scale" in prov["note"] and prov["as_of"]
    assert client.get("/api/stations/test_station").json()["layout_basis"] == "unknown"  # fixture declares none
    route = client.post("/api/navigation/route", json=ROUTE).json()
    assert route["status"] == "ok" and route["provenance"]["mode"] == "cached"


def test_bundled_stations_report_layout_basis_and_checked_date():
    from app.config import Settings
    from app.container import build_container

    settings = Settings(_env_file=None, stations_uri=str(STATIONS_DIR))
    client = TestClient(create_app(settings, build_container(settings, use_configured_llm=False)))
    for sid in STATION_IDS:
        body = client.get(f"/api/stations/{sid}").json()
        assert body["layout_basis"] == "schematic"
        assert body["provenance"]["as_of"].startswith("2026-10-")
        assert client.get(f"/api/stations/{sid}/info").json()["layout_note"]


TRACED = {"chennai_central"}


@pytest.mark.parametrize("station_id", STATION_IDS)
def test_routing_is_enabled_only_for_traced_stations(station_id):
    meta = _load(station_id, "metadata.json")
    assert meta.get("routing", True) is (station_id in TRACED)
    body = _bundled_client().get(f"/api/stations/{station_id}").json()
    assert body["routing_enabled"] is (station_id in TRACED)


@pytest.mark.parametrize("station_id", sorted(set(STATION_IDS) - TRACED))
def test_untraced_station_refuses_routes_but_serves_map_and_info(station_id):
    client = _bundled_client()
    station = _load(station_id, "station.json")
    ids = [n["id"] for n in station["nodes"]]
    res = client.post("/api/navigation/route", json={"station_id": station_id, "source": ids[0],
                                                     "destination": "platform_1"})
    assert res.status_code == 503
    detail = res.json()
    assert "routing_unavailable" in json.dumps(detail) and "schematic" in json.dumps(detail)
    assert "geometry" not in json.dumps(detail)
    assert client.get(f"/api/stations/{station_id}/map").status_code == 200
    assert client.get(f"/api/stations/{station_id}/info").status_code == 200


def test_traced_station_still_routes():
    res = _bundled_client().post("/api/navigation/route", json={
        "station_id": "chennai_central", "source": "ent_wall_tax", "destination": "platform_10"})
    assert res.status_code == 200 and res.json()["status"] == "ok" and res.json()["geometry"]


def test_routing_flag_is_honoured_for_any_station(tmp_path):
    from tests.station_fixture import METADATA, station_root, write_station

    root = station_root(tmp_path)
    write_station(root, metadata={**METADATA, "routing": False})
    client, _ = make(tmp_path, root=root)
    assert client.post("/api/navigation/route", json=ROUTE).status_code == 503
    assert client.get("/api/stations/test_station").json()["routing_enabled"] is False
