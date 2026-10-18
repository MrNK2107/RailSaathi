import json

from app.navigation.world import elements_to_features, load_world, to_local

ORIGIN = {"lat": 13.0825, "lon": 80.275}


def _geom(*pts):
    return [{"lat": lat, "lon": lon} for lat, lon in pts]


def _square(lat, lon, d):
    return _geom((lat, lon), (lat, lon + d), (lat + d, lon + d), (lat + d, lon), (lat, lon))


FIXTURE = {
    "elements": [
        {"type": "way", "id": 3, "tags": {"railway": "rail"},
         "geometry": _geom((13.0830, 80.2750), (13.0840, 80.2755), (13.0850, 80.2752))},
        {"type": "way", "id": 2, "tags": {"railway": "platform", "ref": "7;8"},
         "geometry": _square(13.0826, 80.2751, 0.0002)},
        {"type": "way", "id": 1, "tags": {"building": "yes", "name": "Hall", "building:levels": "3",
                                          "height": "12 m"},
         "geometry": _square(13.0820, 80.2750, 0.0003)},
        {"type": "way", "id": 4, "tags": {"building": "roof"}, "geometry": _square(13.0821, 80.2755, 0.0003)},
    ]
}


def test_to_local_origin_is_zero():
    assert to_local(13.0825, 80.275, 13.0825, 80.275) == (0.0, 0.0)


def test_to_local_100m_north():
    east, north = to_local(13.0825 + 0.000899, 80.275, 13.0825, 80.275)
    assert east == 0.0
    assert abs(north - 100) < 0.5


def test_elements_to_features_kinds():
    feats = elements_to_features(FIXTURE, ORIGIN)
    assert [f["id"] for f in feats] == ["way/1", "way/2", "way/3", "way/4"]
    kinds = {f["id"]: f["kind"] for f in feats}
    assert kinds == {"way/1": "building", "way/2": "platform", "way/3": "rail", "way/4": "roof"}
    by_id = {f["id"]: f for f in feats}
    assert by_id["way/2"]["ref"] == "7;8"
    assert by_id["way/1"]["name"] == "Hall"
    assert by_id["way/1"]["levels"] == 3
    assert by_id["way/1"]["height_m"] == 12.0
    assert len(by_id["way/1"]["points"]) == 4  # open ring
    assert len(by_id["way/3"]["points"]) == 3  # polyline
    east, north = by_id["way/3"]["points"][-1]
    assert east > 0 and north > 0  # east, north from the origin


def test_deterministic_output():
    a = json.dumps(elements_to_features(FIXTURE, ORIGIN))
    b = json.dumps(elements_to_features(json.loads(json.dumps(FIXTURE)), ORIGIN))
    assert a == b


def test_drops_tiny_buildings():
    tiny = {"elements": [{"type": "way", "id": 9, "tags": {"building": "yes"},
                          "geometry": _square(13.0825, 80.275, 0.00002)}]}  # ~2 m x 2 m
    assert elements_to_features(tiny, ORIGIN) == []


def test_load_world_missing_returns_none(tmp_path):
    assert load_world(tmp_path) is None


def test_load_world_reads_file(tmp_path):
    (tmp_path / "osm.json").write_text(json.dumps({"features": []}), encoding="utf-8")
    assert load_world(tmp_path) == {"features": []}


def test_osm_cli_from_saved_input(tmp_path, monkeypatch):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import stations

    root = tmp_path / "stations"
    (root / "chennai_central").mkdir(parents=True)
    (root / "chennai_central" / "station.json").write_text("{}", encoding="utf-8")
    saved = tmp_path / "saved.json"
    saved.write_text(json.dumps({**FIXTURE, "osm3s": {"timestamp_osm_base": "2026-01-01T00:00:00Z"}}), encoding="utf-8")
    code = stations.main(["--root", str(root), "osm", "chennai_central", "--input", str(saved),
                          "--heritage-way", "way/1"])
    assert code == 0
    world = load_world(root / "chennai_central")
    assert world["attribution"] == "© OpenStreetMap contributors"
    assert world["heritage_way"] == "way/1"
    assert [f["kind"] for f in world["features"]] == ["heritage", "platform", "rail", "roof"]
