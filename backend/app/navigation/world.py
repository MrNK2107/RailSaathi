"""Offline OpenStreetMap world data for a station: projection, trimming and loading.

Pure functions only; nothing here touches the network. `scripts/stations.py osm` fetches an Overpass response once
and writes `osm.json` next to the station; the runtime only reads that file. Points are [east, north] metres from
the world file's origin. Data (c) OpenStreetMap contributors, ODbL-1.0.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Literal, TypedDict

EARTH_RADIUS_M = 6_371_008.8
WORLD_FILE = "osm.json"
MIN_BUILDING_AREA_M2 = 12.0
SIMPLIFY_TOLERANCE_M = 0.5

Kind = Literal["building", "roof", "platform", "rail", "subway", "station", "heritage"]


class WorldFeature(TypedDict):
    id: str
    kind: Kind
    name: str | None
    ref: str | None
    levels: int | None
    height_m: float | None
    layer: int | None
    points: list[list[float]]


def to_local(lat: float, lon: float, origin_lat: float, origin_lon: float) -> tuple[float, float]:
    """East and north metres of (lat, lon) from the origin (equirectangular), rounded to 0.01 m."""
    north = math.radians(lat - origin_lat) * EARTH_RADIUS_M
    east = math.radians(lon - origin_lon) * EARTH_RADIUS_M * math.cos(math.radians(origin_lat))
    return round(east + 0.0, 2), round(north + 0.0, 2)


def _origin(origin: Any) -> tuple[float, float]:
    if isinstance(origin, dict):
        return float(origin["lat"]), float(origin["lon"])
    return float(origin[0]), float(origin[1])


def _perp_distance(p: list[float], a: list[float], b: list[float]) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    return abs(dx * (a[1] - p[1]) - (a[0] - p[0]) * dy) / length


def simplify(points: list[list[float]], tolerance: float = SIMPLIFY_TOLERANCE_M) -> list[list[float]]:
    """Douglas-Peucker (iterative); always keeps the first and last point."""
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        lo, hi = stack.pop()
        far, far_d = -1, tolerance
        for i in range(lo + 1, hi):
            d = _perp_distance(points[i], points[lo], points[hi])
            if d > far_d:
                far, far_d = i, d
        if far != -1:
            keep[far] = True
            stack.append((lo, far))
            stack.append((far, hi))
    return [p for p, k in zip(points, keep) if k]


def _area(points: list[list[float]]) -> float:
    s = 0.0
    for i, (x1, y1) in enumerate(points):
        x2, y2 = points[(i + 1) % len(points)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def _num(value: Any) -> float | None:
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)", str(value)) if value is not None else None
    return float(m.group(1)) if m else None


def _int(value: Any) -> int | None:
    n = _num(value)
    return int(n) if n is not None else None


def _kind(tags: dict[str, str]) -> Kind | None:
    building = tags.get("building")
    if building == "roof":
        return "roof"
    if building and building != "no":
        return "building"
    railway = tags.get("railway")
    if railway == "platform" or tags.get("public_transport") == "platform":
        return "platform"
    if railway == "rail":
        return "rail"
    if railway == "subway" or (tags.get("highway") in {"footway", "pedestrian", "corridor"}
                               and tags.get("tunnel") in {"yes", "building_passage"}
                               and tags.get("layer", "0").lstrip("-").isdigit() and int(tags["layer"]) < 0):
        return "subway"
    if railway == "station" or tags.get("public_transport") == "station":
        return "station"
    return None


def _join_rings(ways: list[list[dict]]) -> list[list[dict]]:
    """Chain member way geometries end to end into closed rings; unclosed leftovers are dropped."""
    pending = [list(w) for w in ways if len(w) >= 2]
    rings: list[list[dict]] = []
    while pending:
        ring = pending.pop(0)
        while ring[0] != ring[-1]:
            for i, w in enumerate(pending):
                if w[0] == ring[-1]:
                    ring += w[1:]
                elif w[-1] == ring[-1]:
                    ring += w[::-1][1:]
                else:
                    continue
                pending.pop(i)
                break
            else:
                break
        if ring[0] == ring[-1] and len(ring) >= 4:
            rings.append(ring)
    return rings


def _geometries(el: dict) -> list[list[dict]]:
    if el["type"] == "way":
        return [el["geometry"]] if el.get("geometry") else []
    if el["type"] == "relation":
        outers = [m["geometry"] for m in el.get("members", []) if m.get("role") == "outer" and m.get("geometry")]
        rings = _join_rings(outers)
        return rings[:1]  # footprints only: inner rings (courtyards) and extra outer parts are ignored
    return []


def elements_to_features(overpass_json: dict, origin: Any, heritage_id: str | None = None) -> list[WorldFeature]:
    """Overpass `out geom` elements to world features, sorted by id. Buildings under 12 m2 are dropped and
    geometry is simplified at 0.5 m. `heritage_id` ("way/<id>") re-kinds that building as "heritage"."""
    olat, olon = _origin(origin)
    features: list[WorldFeature] = []
    for el in overpass_json.get("elements", []):
        tags = el.get("tags") or {}
        kind = _kind(tags)
        if kind is None or el.get("type") not in {"way", "relation"}:
            continue
        for geom in _geometries(el):
            pts = [list(to_local(p["lat"], p["lon"], olat, olon)) for p in geom]
            closed = len(pts) > 3 and pts[0] == pts[-1]
            if closed:
                pts = pts[:-1]
            pts = simplify(pts + [pts[0]] if closed else pts)
            if closed:
                pts = pts[:-1]
            if kind in {"building", "roof"} and (len(pts) < 3 or _area(pts) < MIN_BUILDING_AREA_M2):
                continue
            fid = f"{el['type']}/{el['id']}"
            features.append({
                "id": fid,
                "kind": "heritage" if fid == heritage_id else kind,
                "name": tags.get("name"),
                "ref": tags.get("ref"),
                "levels": _int(tags.get("building:levels")),
                "height_m": _num(tags.get("height")),
                "layer": _int(tags.get("layer")),
                "points": pts,
            })
    return sorted(features, key=lambda f: f["id"])


def load_world(station_dir: Path) -> dict | None:
    """The station's osm.json, or None when it has none (or it is unreadable)."""
    path = Path(station_dir) / WORLD_FILE
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
