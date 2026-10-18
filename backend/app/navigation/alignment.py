"""Fit a station's hand-traced plan onto its OpenStreetMap world file.

Pure functions, no network. Frames (ruling R4): plan metres have y pointing down the plan, so a plan point
(x, y) enters the fit as (x, -y); the result maps it to (east, north) metres in the osm.json frame.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Sequence

RESIDUAL_LIMIT_M = 15.0
Point = tuple[float, float]


@dataclass(frozen=True)
class Similarity:
    """dst = scale * R(rotation_deg) * src + (tx, ty); residual_m is the RMS error over the fitted pairs."""

    scale: float
    rotation_deg: float
    tx: float
    ty: float
    residual_m: float

    def apply(self, x: float, y: float) -> Point:
        a = math.radians(self.rotation_deg)
        c, s = self.scale * math.cos(a), self.scale * math.sin(a)
        return (c * x - s * y + self.tx, s * x + c * y + self.ty)


def _centroid(pts: Sequence[Point]) -> Point:
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def _rms(model: Similarity, src: Sequence[Point], dst: Sequence[Point]) -> float:
    err = [math.dist(model.apply(*s), d) for s, d in zip(src, dst)]
    return math.sqrt(sum(e * e for e in err) / len(err))


def _check(src: Sequence[Point], dst: Sequence[Point]) -> None:
    if len(src) != len(dst) or len(src) < 2:
        raise ValueError("need at least two matching point pairs")


def fit_similarity(src: Sequence[Point], dst: Sequence[Point]) -> Similarity:
    """Umeyama/Procrustes least-squares scale + rotation + translation in 2D. Reflection is never allowed."""
    _check(src, dst)
    (sx, sy), (dx, dy) = _centroid(src), _centroid(dst)
    # Complex form: with z = x + iy the optimal rotation+scale is a = sum(conj(s) * d) / sum(|s|^2).
    num = sum(complex(s[0] - sx, s[1] - sy).conjugate() * complex(d[0] - dx, d[1] - dy) for s, d in zip(src, dst))
    den = sum((s[0] - sx) ** 2 + (s[1] - sy) ** 2 for s in src)
    if den == 0:
        raise ValueError("source points are all identical")
    a = num / den
    scale, rot = abs(a), math.degrees(math.atan2(a.imag, a.real))
    ar = math.radians(rot)
    tx = dx - scale * (math.cos(ar) * sx - math.sin(ar) * sy)
    ty = dy - scale * (math.sin(ar) * sx + math.cos(ar) * sy)
    model = Similarity(scale, rot, tx, ty, 0.0)
    return Similarity(scale, rot, tx, ty, _rms(model, src, dst))


def fit_translation(src: Sequence[Point], dst: Sequence[Point]) -> Similarity:
    """Scale 1, rotation 0: the mean offset only. The fallback when a similarity fit is not credible."""
    _check(src, dst)
    (sx, sy), (dx, dy) = _centroid(src), _centroid(dst)
    model = Similarity(1.0, 0.0, dx - sx, dy - sy, 0.0)
    return Similarity(1.0, 0.0, model.tx, model.ty, _rms(model, src, dst))


def fit(src: Sequence[Point], dst: Sequence[Point], limit_m: float = RESIDUAL_LIMIT_M) -> tuple[str, Similarity]:
    """('similarity', fit) when its RMS residual is within the limit, otherwise ('translation', fit)."""
    sim = fit_similarity(src, dst)
    if sim.residual_m <= limit_m:
        return "similarity", sim
    return "translation", fit_translation(src, dst)


def polygon_centroid(points: Sequence[Sequence[float]]) -> Point:
    """Area centroid of a polygon; the vertex mean for degenerate shapes."""
    n = len(points)
    a = cx = cy = 0.0
    for i in range(n):
        x1, y1 = points[i][0], points[i][1]
        x2, y2 = points[(i + 1) % n][0], points[(i + 1) % n][1]
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(a) < 1e-9:
        return _centroid([(p[0], p[1]) for p in points])
    return (cx / (3 * a), cy / (3 * a))


def platform_axis_points(points: Sequence[Sequence[float]], toward: Point, length: float | None = None
                         ) -> tuple[Point, Point, float]:
    """(head, mid, length) of an elongated footprint. The principal axis is found by PCA; head is the middle of
    the end nearer `toward`; mid sits `length / 2` in from the head (the footprint's own length by default, never
    past its far end). A traced plan shows only the building end of each platform, so matching these instead of
    whole-footprint centroids stops a 600 m OSM platform from being compared to a 110 m traced one."""
    pts = [(p[0], p[1]) for p in points]
    cx, cy = _centroid(pts)
    sxx = sum((x - cx) ** 2 for x, _ in pts)
    syy = sum((y - cy) ** 2 for _, y in pts)
    sxy = sum((x - cx) * (y - cy) for x, y in pts)
    theta = 0.5 * math.atan2(2 * sxy, sxx - syy)
    ux, uy = math.cos(theta), math.sin(theta)
    t = [(x - cx) * ux + (y - cy) * uy for x, y in pts]
    v = [-(x - cx) * uy + (y - cy) * ux for x, y in pts]
    t_lo, t_hi, v_mid = min(t), max(t), (min(v) + max(v)) / 2
    mid_xy = (cx - v_mid * uy, cy + v_mid * ux)  # lateral centre line at the centroid's along-axis position

    def at(tt: float) -> Point:
        return (mid_xy[0] + ux * tt, mid_xy[1] + uy * tt)

    extent = t_hi - t_lo
    head_t, sign = (t_lo, 1.0) if math.dist(at(t_lo), toward) <= math.dist(at(t_hi), toward) else (t_hi, -1.0)
    run = min(extent if length is None else length, extent)
    return at(head_t), at(head_t + sign * run / 2), extent


def platform_number(name: str) -> int | None:
    m = re.search(r"Platform\s+(\d+)", name or "")
    return int(m.group(1)) if m else None


def _unit(a: Point, b: Point) -> Point:
    d = math.dist(a, b) or 1.0
    return ((b[0] - a[0]) / d, (b[1] - a[1]) / d)


def _lateral(point: Point, u: Point) -> float:
    """Signed position of a point across the platforms: its component along u rotated +90 degrees."""
    return -point[0] * u[1] + point[1] * u[0]


def pair_platforms(station_areas: list[dict[str, Any]], features: list[dict[str, Any]], width_px: int,
                   height_px: int, mpp: float, reach_m: float = 250.0, mirror: bool = False,
                   window_ids: list[str] | None = None) -> tuple[list[dict[str, Any]], dict]:
    """Pair the traced platform areas with OSM platforms by geometry, orientation-first.

    Each traced platform is a strip leading away from the traced building; each OSM platform (one that has a ref,
    is at least as long as the traced strips and starts within `reach_m` of the OSM station building) leads away
    from it too. A proper rotation (no mirror) maps one set of strips onto the other, which fixes the order
    across the platforms. OSM platforms are islands serving two numbers, so consecutive traced areas are taken
    two to an island, and the run of consecutive OSM islands whose fit has the lowest residual is kept.
    Returns (pairs, info). Each pair holds the area id, plan number, OSM feature id and ref and the plan (x, -y)
    and world points to fit (building-end point and the point half a traced length in); info lists the
    alternatives tried. Labels stay the traced plan's (`label_source: station_plan`); `ref_agrees` says whether the
    OSM ref also names that number. `mirror=True` reflects the plan across its platform axis first (plan (x, y)
    instead of (x, -y)), for the parity check; `window_ids` restricts the search to that run of OSM islands."""
    building = next((a for a in station_areas if a["kind"] == "building_footprint"), None)
    heritage = next((f for f in features if f["kind"] == "heritage"), None)
    if building is None or heritage is None:
        raise ValueError("need a traced building_footprint area and an OSM heritage building to orient platforms")

    def metres(area: dict[str, Any]) -> list[Point]:
        sign = 1.0 if mirror else -1.0
        return [(p[0] * width_px * mpp, sign * p[1] * height_px * mpp) for p in area["polygon"]]

    plan_toward, world_toward = polygon_centroid(metres(building)), polygon_centroid(heritage["points"])
    plan = [(a, platform_axis_points(metres(a), plan_toward)) for a in station_areas
            if a["kind"] == "platform" and platform_number(a["name"]) is not None]
    if not plan:
        raise ValueError("station has no traced platform areas")
    length = min(ext for _, (_, _, ext) in plan)
    up = _unit(*plan[0][1][:2])
    plan.sort(key=lambda it: _lateral(it[1][0], up))

    islands = []
    for f in features:
        if f["kind"] != "platform" or not f.get("ref") or not re.search(r"\d", str(f["ref"])):
            continue
        head, mid, ext = platform_axis_points(f["points"], world_toward, length)
        if ext >= length and math.dist(head, world_toward) <= reach_m:
            islands.append((f, (head, mid)))
    if not islands:
        raise ValueError("no OSM platforms near the station building")
    uw = _unit(*islands[0][1])
    islands.sort(key=lambda it: _lateral(it[1][0], uw))
    need = (len(plan) + 1) // 2
    best: tuple[float, list[dict[str, Any]]] | None = None
    tried = []
    for start in range(0, len(islands) - need + 1):
        window = islands[start:start + need]
        if window_ids is not None and [f["id"] for f, _ in window] != window_ids:
            continue
        pairs = []
        for i, (area, (head, mid, _)) in enumerate(plan):
            feat, (whead, wmid) = window[i // 2]
            n = platform_number(area["name"])
            pairs.append({"area": area["id"], "number": n, "feature": feat["id"], "ref": feat["ref"],
                          "ref_agrees": str(n) in str(feat["ref"]).split(";"),
                          "plan": [head, mid], "world": [whead, wmid]})
        src, dst = fit_points(pairs)
        residual = fit_similarity(src, dst).residual_m
        tried.append({"features": [f["id"] for f, _ in window], "residual_m": round(residual, 2)})
        if best is None or residual < best[0]:
            best = (residual, pairs)
    if best is None:
        raise ValueError("no run of OSM platforms matches the requested window")
    ranked = sorted(tried, key=lambda t: t["residual_m"])
    return best[1], {"candidates_tried": tried, "runner_up": ranked[1] if len(ranked) > 1 else None}


def fit_points(pairs: list[dict[str, Any]]) -> tuple[list[Point], list[Point]]:
    """Fit inputs from `pair_platforms`. Island platforms carry two numbers ("7;8"), so the traced areas that share
    an OSM platform are averaged first; otherwise two plan points would be forced onto one OSM point."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for p in pairs:
        groups.setdefault(p["feature"], []).append(p)
    src: list[Point] = []
    dst: list[Point] = []
    for members in groups.values():
        for k in range(len(members[0]["plan"])):
            src.append(_centroid([m["plan"][k] for m in members]))
            dst.append(members[0]["world"][k])
    return src, dst
