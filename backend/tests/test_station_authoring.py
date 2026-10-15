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
