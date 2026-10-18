"""Fitting the traced plan to OpenStreetMap: the transform maths, the fallback and the validate check."""

import json
import math
import random
import sys
from pathlib import Path

import pytest

from app.config import STATIONS_DIR
from app.navigation.alignment import RESIDUAL_LIMIT_M, fit, fit_similarity, fit_translation
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
