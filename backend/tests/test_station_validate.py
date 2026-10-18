"""`scripts/stations.py validate` and the checks behind it: every bundled station passes, and each check catches
the problem it is for. Also the catalogue, preview and publish commands (Cloud Storage mocked)."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.config import STATIONS_DIR
from app.navigation.models.station import Catalogue, Station, StationMetadata
from app.navigation.services.route_validator import validate_station_data
from tests.station_fixture import METADATA, png_bytes, station_raw, write_station

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import stations as cli  # noqa: E402

BUNDLED = cli.station_ids(STATIONS_DIR)


def codes(raw, level="errors"):
    report = validate_station_data(raw, StationMetadata.model_validate(METADATA), "test_station")
    return [i.code for i in getattr(report, level)]


# ---- bundled data --------------------------------------------------------------------------------------------

def test_there_are_bundled_stations():
    assert "chennai_central" in BUNDLED


@pytest.mark.parametrize("station_id", BUNDLED)
def test_bundled_station_validates(station_id):
    report = cli.validate_station(STATIONS_DIR, station_id)
    assert report.valid, [f"{e.code}: {e.message}" for e in report.errors]


def test_bundled_catalogue_lists_every_station_and_is_current(capsys):
    assert cli.main(["catalogue", "--check"]) == 0
    catalogue = Catalogue.model_validate_json((STATIONS_DIR / "catalogue.json").read_text(encoding="utf-8"))
    assert [s.station_id for s in catalogue.stations] == BUNDLED


def test_validate_command_exit_codes(tmp_path, capsys):
    assert cli.main(["validate"]) == 0
    raw = station_raw()
    raw["edges"][0]["to"] = "nowhere"
    write_station(tmp_path, raw)
    assert cli.main(["--root", str(tmp_path), "validate"]) == 1
    assert "unknown_node" in capsys.readouterr().out


# ---- the fixture is valid, and new optional fields may be absent ---------------------------------------------

def test_fixture_station_is_valid(tmp_path):
    write_station(tmp_path)
    report = cli.validate_station(tmp_path, "test_station")
    assert report.valid, report.errors
    assert report.warnings == []


def test_new_optional_fields_may_be_absent():
    raw = json.loads((STATIONS_DIR / "chennai_central" / "station.json").read_text(encoding="utf-8"))
    for key in ("ar_enabled", "levels", "areas", "panoramas"):
        raw.pop(key, None)
    for n in raw["nodes"]:
        for key in ("level", "cues", "step_free_exception"):
            n.pop(key, None)
    for e in raw["edges"]:
        e.pop("level_change", None)
    station = Station.model_validate(raw)
    assert (station.ar_enabled, station.levels, station.areas, station.panoramas) == (False, [], [], [])
    assert all(n.level == 0 and n.cues == [] for n in station.nodes)
    assert all(e.level_change == 0 for e in station.edges)


def test_schema_version_1_and_old_accessible_field_are_rejected():
    raw = station_raw(schema_version=1)
    assert "schema" in codes(raw)
    raw = station_raw()
    raw["edges"][0]["accessible"] = raw["edges"][0].pop("step_free")
    report = validate_station_data(raw)
    assert any("step-free status is required" in e.message for e in report.errors)


# ---- step-free ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("claim", ["verified", "reported"])
def test_stepped_pathway_cannot_claim_step_free(claim):
    raw = station_raw()
    raw["edges"][1]["step_free"] = claim  # e_stairs
    assert "contradictory_step_free" in codes(raw)


def test_exit_without_step_free_route_needs_an_exception():
    raw = station_raw()
    raw["edges"] = [e for e in raw["edges"] if e["id"] != "e_ramp"]  # only the stairs reach p1 now
    assert "exit_not_step_free" in codes(raw)
    next(n for n in raw["nodes"] if n["id"] == "ent")["step_free_exception"] = "Only stairs at this gate."
    assert codes(raw) == []


def test_stale_or_misplaced_step_free_exception():
    raw = station_raw()
    next(n for n in raw["nodes"] if n["id"] == "ent")["step_free_exception"] = "Only stairs."
    assert "stale_step_free_exception" in codes(raw, "warnings")
    raw = station_raw()
    next(n for n in raw["nodes"] if n["id"] == "hall")["step_free_exception"] = "x"
    assert "misplaced_step_free_exception" in codes(raw)


# ---- connectivity and direction --------------------------------------------------------------------------------

def test_disconnected_or_isolated_nodes_are_errors():
    raw = station_raw()
    raw["nodes"].append({"id": "lonely", "name": "Lonely", "type": "shop", "position": [0.9, 0.9],
                         "verification": "pending"})
    assert "isolated_node" in codes(raw)


def test_one_way_trap_is_an_error_and_one_way_edges_warn():
    raw = station_raw()
    raw["edges"][0]["bidirectional"] = False  # ent -> hall only: nobody can walk out through ent
    assert "one_way_trap" in codes(raw)
    raw = station_raw()
    raw["edges"].append({**raw["edges"][2], "id": "e_extra", "bidirectional": False})  # parallel one-way
    assert "one_way_edge" in codes(raw, "warnings") and codes(raw) == []


# ---- levels ---------------------------------------------------------------------------------------------------

def test_level_change_must_match_nodes_and_use_a_transition():
    raw = station_raw()
    raw["edges"][4]["level_change"] = 0  # lift up, but says flat
    assert "level_mismatch" in codes(raw)
    raw = station_raw()
    raw["edges"][6]["level_change"] = 1  # walkway on the bridge
    errors = codes(raw)
    assert "invalid_level_change" in errors and "level_mismatch" in errors


def test_declared_levels_must_cover_nodes_and_areas():
    raw = station_raw(levels=[{"level": 0, "name": "Ground"}])
    assert "undeclared_level" in codes(raw)
    raw = station_raw(levels=[{"level": 0, "name": "Ground"}, {"level": 1, "name": "Bridge", "elevation_m": 6}])
    assert codes(raw) == []
    raw["levels"].append({"level": 1, "name": "Again"})
    assert "duplicate_level" in codes(raw)


# ---- areas, panoramas, cues -----------------------------------------------------------------------------------

def area(polygon, **kw):
    return {"id": kw.pop("id", "a1"), "kind": "platform", "level": 0, "height_m": 1.0, "polygon": polygon, **kw}


SQUARE = [[0.4, 0.4], [0.6, 0.4], [0.6, 0.6], [0.4, 0.6], [0.4, 0.4]]


def test_area_polygons_must_be_closed_and_inside_the_image():
    assert codes(station_raw(areas=[area(SQUARE)])) == []
    assert "open_polygon" in codes(station_raw(areas=[area(SQUARE[:-1])]))
    outside = [[0.4, 0.4], [1.2, 0.4], [0.6, 0.6], [0.4, 0.4]]
    assert "invalid_coordinates" in codes(station_raw(areas=[area(outside)]))
    assert "degenerate_polygon" in codes(station_raw(areas=[area([[0.1, 0.1], [0.2, 0.2], [0.2, 0.2], [0.1, 0.1]])]))
    assert "duplicate_area_id" in codes(station_raw(areas=[area(SQUARE), area(SQUARE)]))


def test_panorama_must_reference_an_existing_node():
    pano = {"pano_id": "CAoSLEFGMVFpcE", "node_id": "ent", "heading": 90, "pitch": 0, "kind": "street_view",
            "verified_on": None}
    assert codes(station_raw(panoramas=[pano])) == []
    assert "unknown_node" in codes(station_raw(panoramas=[{**pano, "node_id": "ghost"}]))


def cue(text="Platform 1"):
    return {"kind": "signboard", "text": text, "facing_deg": 180, "source": "site photo 2026-10-01",
            "verified_on": "2026-10-01"}


def test_ar_enabled_needs_cues_on_80_percent_of_routable_nodes():
    raw = station_raw(ar_enabled=True)
    assert "insufficient_cues" in codes(raw)
    for n in raw["nodes"][:5]:  # 5 of 7 = 71%
        n["cues"] = [cue()]
    assert "insufficient_cues" in codes(raw)
    raw["nodes"][5]["cues"] = [cue()]  # 6 of 7 = 86%
    assert codes(raw) == []
    assert codes(station_raw()) == []  # without ar_enabled, no cues needed


def test_cue_requires_source_and_explicit_verified_on():
    raw = station_raw()
    bad = cue()
    del bad["verified_on"]
    raw["nodes"][0]["cues"] = [bad]
    assert "schema" in codes(raw)
    raw["nodes"][0]["cues"] = [{**cue(), "verified_on": None}]
    assert codes(raw) == []


# ---- Chennai Central AR and tour content ------------------------------------------------------------------------

def _chennai() -> tuple[Station, dict]:
    folder = STATIONS_DIR / "chennai_central"
    return (Station.model_validate(json.loads((folder / "station.json").read_text(encoding="utf-8"))),
            json.loads((folder / "metadata.json").read_text(encoding="utf-8")))


def test_chennai_ar_cues_cover_80_percent_of_routable_nodes_honestly():
    station, _ = _chennai()
    routable = {e.from_ for e in station.edges} | {e.to for e in station.edges}
    with_cues = [n for n in station.nodes if n.id in routable and n.cues]
    assert station.ar_enabled and len(with_cues) >= 0.8 * len(routable)
    # Every cue names its source and none claims an on-site check that has not happened.
    cues = [c for n in station.nodes for c in n.cues]
    assert cues and all(c.source and c.verified_on is None for c in cues)
    # Cue text comes from the station's own labels (node names, platform numbers, plan symbols), never an
    # invented landmark.
    names = {n.name for n in station.nodes}
    platforms = {f"Platform {n.name.split()[1]}" for n in station.nodes if n.name.startswith("Platform ")}
    plan_symbols = {"Information", "Toilet", "Food / Shop", "Ticketing & Reservation",
                    "Main Concourse waiting area with rows of seats"}
    assert {c.text for c in cues} <= names | platforms | plan_symbols


def test_chennai_levels_and_areas_are_declared_and_labelled_as_traced():
    station, metadata = _chennai()
    assert [lv.level for lv in station.levels] == [0]
    assert station.areas and all(a.name and "traced from the schematic plan" in a.name for a in station.areas)
    assert {a.kind for a in station.areas} == {"platform", "concourse", "building_footprint", "track_bed"}
    assert any("traced by hand from map.png" in note for note in metadata["notes"])


def test_chennai_panoramas_are_not_invented():
    station, metadata = _chennai()
    # No pano id could be verified offline: the list stays empty and the owner is told how to fill it.
    assert station.panoramas == []
    assert "scripts/stations.py panoramas" in metadata["panoramas_note"]


# ---- image bounds -----------------------------------------------------------------------------------------------

def test_coordinates_outside_the_image_are_errors():
    raw = station_raw()
    raw["nodes"][0]["position"] = [1.1, 0.5]
    assert "invalid_coordinates" in codes(raw)


def test_map_image_must_match_declared_size(tmp_path):
    write_station(tmp_path, image=png_bytes(800, 600))
    assert "map_size_mismatch" in [e.code for e in cli.validate_station(tmp_path, "test_station").errors]
    write_station(tmp_path, image=b"not a png")
    assert "invalid_map" in [e.code for e in cli.validate_station(tmp_path, "test_station").errors]


def test_folder_must_match_station_id(tmp_path):
    write_station(tmp_path, folder="other_name")
    assert "station_id_mismatch" in [e.code for e in cli.validate_station(tmp_path, "other_name").errors]


# ---- catalogue / preview / publish ------------------------------------------------------------------------------

def test_catalogue_command_writes_and_refuses_invalid(tmp_path, capsys):
    write_station(tmp_path)
    assert cli.main(["--root", str(tmp_path), "catalogue", "--check"]) == 1
    assert cli.main(["--root", str(tmp_path), "catalogue"]) == 0
    doc = json.loads((tmp_path / "catalogue.json").read_text(encoding="utf-8"))
    assert doc["stations"] == [{"station_id": "test_station", "station_name": "Test Station", "city": "Testpur",
                                "data_status": "mock", "version": "local", "path": "test_station"}]
    assert cli.main(["--root", str(tmp_path), "catalogue", "--check"]) == 0
    raw = station_raw()
    raw["edges"][0]["to"] = "nowhere"
    write_station(tmp_path, raw)
    assert cli.main(["--root", str(tmp_path), "catalogue"]) == 1


def test_preview_draws_route_on_the_map(tmp_path):
    from PIL import Image

    write_station(tmp_path)
    out = tmp_path / "preview.png"
    summary = cli.render_preview(tmp_path, "test_station", "ent", "p2", True, out)
    assert "route ent -> p2" in summary
    image = Image.open(out)
    assert image.size == (1000, 1000)
    assert image.getpixel((400, 900)) == (0, 90, 220)  # the ramp leg (step-free route) is drawn in route blue
    assert image.getpixel((400, 500)) == (230, 120, 0)  # the stairs are drawn as a stepped pathway, not the route


class FakeBucket:
    def __init__(self, existing: dict[str, bytes] | None = None):
        self.objects = dict(existing or {})
        self.uploads: list[tuple[str, dict]] = []

    def blob(self, name):
        blob = MagicMock()
        blob.upload_from_string.side_effect = lambda data, **kw: self._upload(name, data, kw)
        return blob

    def _upload(self, name, data, kw):
        if kw.get("if_generation_match") == 0 and name in self.objects:
            raise RuntimeError("precondition failed")
        self.objects[name] = data.encode() if isinstance(data, str) else data
        self.uploads.append((name, kw))

    def get_blob(self, name):
        if name not in self.objects:
            return None
        blob = MagicMock(generation=7)
        blob.download_as_bytes.return_value = self.objects[name]
        return blob


def fake_client(bucket):
    client = MagicMock()
    client.bucket.return_value = bucket
    return client


def test_publish_uploads_a_new_version_and_points_the_catalogue_at_it(tmp_path):
    write_station(tmp_path)
    other = {"station_id": "chennai_central", "station_name": "Chennai Central", "city": "Chennai",
             "data_status": "mock", "version": "20261001T000000Z", "path": "chennai_central/20261001T000000Z"}
    bucket = FakeBucket({"stations/catalogue.json": json.dumps({"schema_version": 1, "stations": [other]}).encode()})
    client = fake_client(bucket)
    where = cli.publish(tmp_path, "test_station", "gs://bkt/stations", "20261015T120000Z", client=client)
    assert where == "gs://bkt/stations/test_station/20261015T120000Z"
    client.bucket.assert_called_with("bkt")
    uploaded = dict(bucket.uploads)
    folder = "stations/test_station/20261015T120000Z/"
    for name in ("station.json", "map.png", "metadata.json", "info.json"):
        assert uploaded[folder + name]["if_generation_match"] == 0  # versions are never overwritten
    assert uploaded["stations/catalogue.json"]["if_generation_match"] == 7  # optimistic update of the catalogue
    catalogue = Catalogue.model_validate_json(bucket.objects["stations/catalogue.json"])
    assert [(s.station_id, s.path) for s in catalogue.stations] == [
        ("chennai_central", "chennai_central/20261001T000000Z"),
        ("test_station", "test_station/20261015T120000Z")]
    with pytest.raises(RuntimeError):  # same version again: refused by the generation precondition
        cli.publish(tmp_path, "test_station", "gs://bkt/stations", "20261015T120000Z", client=client)


def test_publish_uploads_osm_json_when_present(tmp_path):
    write_station(tmp_path)
    (tmp_path / "test_station" / "osm.json").write_text('{"features": []}', encoding="utf-8")
    bucket = FakeBucket({})
    cli.publish(tmp_path, "test_station", "gs://bkt/stations", "v1", client=fake_client(bucket))
    assert bucket.objects["stations/test_station/v1/osm.json"] == b'{"features": []}'


def test_publish_creates_the_catalogue_when_missing_and_refuses_invalid_stations(tmp_path):
    write_station(tmp_path)
    bucket = FakeBucket()
    cli.publish(tmp_path, "test_station", "gs://bkt", "v1", client=fake_client(bucket))
    assert dict(bucket.uploads)["catalogue.json"]["if_generation_match"] == 0
    raw = station_raw()
    raw["edges"][0]["to"] = "nowhere"
    write_station(tmp_path, raw)
    empty = FakeBucket()
    with pytest.raises(ValueError, match="invalid"):
        cli.publish(tmp_path, "test_station", "gs://bkt", "v2", client=fake_client(empty))
    assert empty.uploads == []
    with pytest.raises(ValueError, match="gs://"):
        cli.publish(tmp_path.parent, "x", "s3://nope", client=fake_client(empty))
