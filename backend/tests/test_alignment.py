"""Fitting the traced plan to OpenStreetMap: the transform maths, the fallback and the validate check."""

import json
import math
import random
import sys
from pathlib import Path

import pytest

from app.config import STATIONS_DIR
from app.navigation.alignment import (RESIDUAL_LIMIT_M, fit, fit_points, fit_similarity, fit_translation,
                                      pair_platforms, platform_axis_points)
from app.navigation.models.station import StationMetadata

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import stations as cli  # noqa: E402

PLAN = [(0.0, 0.0), (80.0, 5.0), (75.0, -60.0), (10.0, -48.0), (40.0, -30.0), (90.0, -20.0)]


def transform(pts, scale, deg, tx, ty):
    a = math.radians(deg)
    return [(scale * (math.cos(a) * x - math.sin(a) * y) + tx, scale * (math.sin(a) * x + math.cos(a) * y) + ty)
            for x, y in pts]


def test_fit_recovers_known_transform():
    rng = random.Random(7)
    dst = [(x + rng.uniform(-0.3, 0.3), y + rng.uniform(-0.3, 0.3)) for x, y in transform(PLAN, 1.03, 12, 40, -25)]
    sim = fit_similarity(PLAN, dst)
    assert abs(sim.rotation_deg - 12) < 0.5
    assert abs(sim.scale - 1.03) < 0.01
    assert abs(sim.tx - 40) < 1.0 and abs(sim.ty + 25) < 1.0
    for p, d in zip(PLAN, dst):
        assert math.dist(sim.apply(*p), d) < 1.0
    assert sim.residual_m < 0.5


def test_fit_rejects_reflection():
    mirrored = [(x, -y) for x, y in PLAN]
    sim = fit_similarity(PLAN, mirrored)
    # a proper rotation cannot reproduce a mirror image, so the fit is poor instead of flipping an axis
    assert sim.residual_m > 5.0
    o, a, b = sim.apply(0, 0), sim.apply(1, 0), sim.apply(0, 1)
    assert (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]) > 0


def test_large_residual_falls_back_to_translation():
    dst = transform(PLAN, 1.0, 0, 10, 10)
    dst[0] = (dst[0][0] + 200, dst[0][1] - 150)
    dst[3] = (dst[3][0] - 120, dst[3][1] + 160)
    assert fit_similarity(PLAN, dst).residual_m > RESIDUAL_LIMIT_M
    method, sim = fit(PLAN, dst)
    assert method == "translation"
    assert (sim.scale, sim.rotation_deg) == (1.0, 0.0)
    assert sim.residual_m == pytest.approx(fit_translation(PLAN, dst).residual_m)


def _station_copy(tmp_path, residual):
    src = STATIONS_DIR / "chennai_central"
    dest = tmp_path / "chennai_central"
    dest.mkdir()
    for f in src.iterdir():
        if f.is_file():
            (dest / f.name).write_bytes(f.read_bytes())
    meta = json.loads((dest / "metadata.json").read_text(encoding="utf-8"))
    meta["world_alignment"]["residual_m"] = residual
    (dest / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    return tmp_path


def test_validate_flags_residual_over_limit(tmp_path):
    root = _station_copy(tmp_path, RESIDUAL_LIMIT_M + 5)
    report = cli.validate_station(root, "chennai_central")
    assert "alignment_residual_high" in [e.code for e in report.errors]


def test_validate_accepts_committed_alignment():
    assert cli.validate_station(STATIONS_DIR, "chennai_central").valid


def test_geo_reference_unchanged():
    meta = StationMetadata.model_validate(
        json.loads((STATIONS_DIR / "chennai_central" / "metadata.json").read_text(encoding="utf-8")))
    geo = meta.model_extra["geo_reference"]
    assert geo["method"] == "anchor_scale_rotation"
    assert geo["anchor"] == {"lat": 13.0825, "lon": 80.275, "x": 0.49039, "y": 0.49537}
    assert geo["expected_error_m"] == 50
    assert "world_alignment" in meta.model_extra


# ---- pairing: a synthetic plan rotated -90 degrees onto OSM-like islands -----------------------------------------

TX, TY = 300.0, 40.0  # truth: world = R(-90) * (x, y') + (TX, TY) = (y' + TX, -x + TY), plan metres (x, y' = -y)
ISLANDS = {"way/1": (-185, "20;21"), "way/2": (-150, "18;19"), "way/3": (-95, "6;7"), "way/4": (-70, "4;5"),
           "way/5": (-45, "2;3")}  # island centre east; the first two are a decoy window with a different pitch
# traced strips across the platforms by world east (west first): two per island at the true pitch (25 m)
STRIPS = [("platform_a", 12, -99), ("platform_b", 11, -91), ("platform_c", 10, -74), ("platform_d", 9, -66),
          ("platform_e", 8, -49), ("platform_f", 7, -41)]


def world_rect(east, n0, n1, half):
    return [[east - half, n0], [east + half, n0], [east + half, n1], [east - half, n1]]


def synthetic():
    features = [{"id": "way/9", "kind": "heritage", "name": None, "ref": None,
                 "points": world_rect(-30, -20, -5, 30)}]
    for fid, (east, ref) in ISLANDS.items():
        features.append({"id": fid, "kind": "platform", "name": None, "ref": ref,
                         "points": world_rect(east, 20, 320, 4)})

    def to_plan_area(aid, kind, name, rect):  # 100 px = 100 m, so normalized = metres / 100 and y is down
        pts = [[(TY - n) / 100, -((e - TX)) / 100] for e, n in rect]
        return {"id": aid, "kind": kind, "name": name, "polygon": pts}

    areas = [to_plan_area("building", "building_footprint", "Building", world_rect(-30, -20, -5, 30))]
    for aid, number, east in STRIPS:
        areas.append(to_plan_area(aid, "platform", f"Platform {number}", world_rect(east, 20, 130, 3)))
    return areas, features


def test_pair_platforms_picks_the_true_window_in_proper_orientation():
    areas, features = synthetic()
    pairs, info = pair_platforms(areas, features, 100, 100, 1.0)
    assert {p["area"]: p["feature"] for p in pairs} == {
        "platform_a": "way/3", "platform_b": "way/3", "platform_c": "way/4", "platform_d": "way/4",
        "platform_e": "way/5", "platform_f": "way/5"}
    assert [p["number"] for p in pairs] == [7, 8, 9, 10, 11, 12]  # ordered across the platforms (plan lateral order)
    best = min(info["candidates_tried"], key=lambda t: t["residual_m"])
    assert best["features"] == ["way/5", "way/4", "way/3"]  # runs are listed in across-platform order and best["residual_m"] < 0.01
    assert info["runner_up"]["features"] != best["features"] and info["runner_up"]["residual_m"] > 5
    sim = fit_similarity(*fit_points(pairs))
    assert sim.rotation_deg == pytest.approx(-90, abs=0.1)
    assert sim.scale == pytest.approx(1.0, abs=0.01)
    assert (sim.tx, sim.ty) == pytest.approx((TX, TY), abs=0.1)
    o, a, b = sim.apply(0, 0), sim.apply(1, 0), sim.apply(0, 1)
    assert (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]) > 0  # determinant > 0: no reflection


def test_pair_platforms_mirror_reverses_the_order_and_window_can_be_forced():
    areas, features = synthetic()
    mirrored, _ = pair_platforms(areas, features, 100, 100, 1.0, mirror=True,
                                 window_ids=["way/5", "way/4", "way/3"])
    assert {p["area"]: p["feature"] for p in mirrored} == {
        "platform_a": "way/5", "platform_b": "way/5", "platform_c": "way/4", "platform_d": "way/4",
        "platform_e": "way/3", "platform_f": "way/3"}
    with pytest.raises(ValueError):
        pair_platforms(areas, features, 100, 100, 1.0, window_ids=["way/5", "way/3", "way/1"])


def test_platform_axis_points_head_is_the_end_nearest_the_building():
    strip = world_rect(-95, 20, 320, 4)
    head, mid, extent = platform_axis_points(strip, toward=(-30.0, -12.0), length=110)
    assert extent == pytest.approx(300)
    assert head == pytest.approx((-95, 20), abs=1e-6)
    assert mid == pytest.approx((-95, 75), abs=1e-6)  # half of 110 m in from the head
    assert platform_axis_points(strip, toward=(-95.0, 900.0))[0] == pytest.approx((-95, 320), abs=1e-6)


def test_committed_alignment_is_reproduced_from_the_committed_data():
    folder = STATIONS_DIR / "chennai_central"
    load = lambda name: json.loads((folder / name).read_text(encoding="utf-8"))  # noqa: E731
    metadata = load("metadata.json")
    block = cli.build_alignment(load("station.json"), metadata, load("osm.json"))
    committed = metadata["world_alignment"]
    assert block["method"] == committed["method"] == "similarity"
    assert block["pairs"] == committed["pairs"]
    assert block["residual_m"] == pytest.approx(committed["residual_m"], abs=0.01)
    assert block["parity_check"]["mirrored_residual_m"] == pytest.approx(
        committed["parity_check"]["mirrored_residual_m"], abs=0.01)
    assert block["runner_up"]["features"] == committed["runner_up"]["features"]
