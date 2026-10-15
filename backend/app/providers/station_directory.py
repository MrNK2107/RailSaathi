"""Station directory for live boards: the planner's station catalogue plus coordinates.

Codes, names and cities come from the active JourneyProvider (the RailRadar catalogue in live mode, the demo
stations in demo mode), so search, "nearest station" and departure-board neighbours only ever offer stations the
rest of the app understands. Coordinates come from the bundled station GeoJSON (`data/stations_catalogue.json`);
a station without coordinates is still searchable but has no neighbours and is never "nearest"."""

import functools
import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path

from app.providers.base import StationRecord

log = logging.getLogger("railsaathi.live")

GEOJSON = Path(__file__).resolve().parents[2] / "data" / "stations_catalogue.json"


@dataclass(frozen=True)
class StationPoint:
    code: str
    name: str
    city: str
    latitude: float | None
    longitude: float | None

    def as_dict(self) -> dict:
        return {"code": self.code, "name": self.name, "city": self.city,
                "latitude": self.latitude, "longitude": self.longitude}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def load_coordinates(path: Path = GEOJSON, codes: set[str] | None = None) -> dict[str, tuple[float, float]]:
    """(lat, lon) by station code from the GeoJSON FeatureCollection; missing file or geometry -> no entry."""
    everything = _read_coordinates(path)
    return everything if codes is None else {c: everything[c] for c in codes if c in everything}


@functools.lru_cache(maxsize=4)
def _read_coordinates(path: Path) -> dict[str, tuple[float, float]]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        log.warning("Station coordinates unavailable (%s); live boards will have no neighbours", path.name)
        return {}
    coords: dict[str, tuple[float, float]] = {}
    for feature in doc.get("features", []):
        props = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        code = str(props.get("code") or "").upper()
        point = geometry.get("coordinates") if geometry.get("type") == "Point" else None
        if not code or not isinstance(point, list) or len(point) < 2:
            continue
        lon, lat = point[0], point[1]
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            coords.setdefault(code, (float(lat), float(lon)))
    return coords


class StationDirectory:
    def __init__(self, stations: list[StationRecord],
                 coordinates: dict[str, tuple[float, float]] | None = None) -> None:
        codes = {s.code.upper() for s in stations}
        coords = coordinates if coordinates is not None else load_coordinates(codes=codes)
        self._points: dict[str, StationPoint] = {}
        for st in stations:
            code = st.code.upper()
            lat, lon = coords.get(code, (None, None))
            self._points[code] = StationPoint(code, st.name, st.city, lat, lon)

    def get(self, code: str) -> StationPoint | None:
        return self._points.get(code.strip().upper())

    def search(self, query: str, limit: int = 20) -> list[StationPoint]:
        q = query.strip().upper()
        if not q:
            return []
        hits = [p for p in self._points.values() if q in p.code or q in p.name.upper() or q in p.city.upper()]
        hits.sort(key=lambda p: (p.code != q, not p.code.startswith(q), p.name))
        return hits[:limit]

    def nearest(self, lat: float, lon: float) -> tuple[StationPoint, float] | None:
        best: tuple[StationPoint, float] | None = None
        for p in self._points.values():
            if p.latitude is None or p.longitude is None:
                continue
            d = haversine_km(lat, lon, p.latitude, p.longitude)
            if best is None or d < best[1]:
                best = (p, d)
        return best

    def neighbours(self, code: str, k: int) -> list[StationPoint]:
        """The k nearest catalogue stations in a DIFFERENT city (same-city pairs are suburban hops, not the
        long-distance departures a board is for), at most one per city so queries are not spent twice on one place."""
        origin = self.get(code)
        if origin is None or origin.latitude is None or origin.longitude is None or k <= 0:
            return []
        others = [p for p in self._points.values()
                  if p.code != origin.code and p.city != origin.city
                  and p.latitude is not None and p.longitude is not None]
        others.sort(key=lambda p: haversine_km(origin.latitude, origin.longitude, p.latitude, p.longitude))
        picked: list[StationPoint] = []
        cities: set[str] = set()
        for p in others:
            if p.city not in cities:
                cities.add(p.city)
                picked.append(p)
        return picked[:k]
