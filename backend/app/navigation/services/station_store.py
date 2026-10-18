"""Read-only station catalogue, loaded once at startup with a prebuilt routing graph per station.

The station data root (``Settings.stations_uri``) is a local directory in development or ``gs://bucket/prefix``
in production. It holds ``catalogue.json`` and, per catalogue entry, a folder with:

- ``station.json``   the station graph (schema version 2)
- ``map.png``        the plan image the coordinates are normalized against
- ``metadata.json``  station metadata, including the map scale if known (optional)
- ``info.json``      passenger information (optional)

Nothing here writes. Stations are authored, validated and published with ``scripts/stations.py``; a station that
fails validation at load is left out of the catalogue and logged, never served.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from app.config import DATA_DIR
from app.navigation.models.station import Catalogue, CatalogueEntry, Station, StationMetadata
from app.navigation.services.graph_builder import StationGraph, build_graph
from app.navigation.services.route_validator import check_map_image, validate_graph
from app.navigation.world import WORLD_FILE

log = logging.getLogger("railsaathi.stations")

STATION_ID_RE = re.compile(r"^[a-z0-9_]{1,64}$")
CATALOGUE_FILE = "catalogue.json"
MODEL_FILE = "heritage.glb"
COMMON_HELPLINES = DATA_DIR / "common" / "helplines_india.json"


class StationNotFound(Exception):
    pass


class StationSource(Protocol):
    """Read access to the station data root. `read` returns None when the object does not exist."""

    def read(self, relpath: str) -> bytes | None: ...


class LocalStationSource:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def read(self, relpath: str) -> bytes | None:
        path = self.root / relpath
        return path.read_bytes() if path.is_file() else None


class GcsStationSource:
    def __init__(self, bucket: str, prefix: str, client=None) -> None:
        if client is None:
            from google.cloud import storage  # lazy: only needed when a bucket is configured

            client = storage.Client()
        self._bucket = client.bucket(bucket)
        self._prefix = prefix.strip("/")

    def read(self, relpath: str) -> bytes | None:
        from google.api_core.exceptions import NotFound

        key = f"{self._prefix}/{relpath}" if self._prefix else relpath
        try:
            return self._bucket.blob(key).download_as_bytes()
        except NotFound:
            return None


def build_source(uri: str) -> StationSource:
    if uri.startswith("gs://"):
        bucket, _, prefix = uri[5:].partition("/")
        if not bucket:
            raise ValueError("STATIONS_URI must look like gs://bucket/prefix")
        return GcsStationSource(bucket, prefix)
    return LocalStationSource(uri)


@dataclass(frozen=True)
class LoadedStation:
    entry: CatalogueEntry
    station: Station
    metadata: StationMetadata | None
    info: dict[str, Any]
    map_png: bytes
    graph: StationGraph  # prebuilt, no closures applied
    world: dict[str, Any] | None = None  # osm.json (offline OpenStreetMap footprints), when the station has one
    model_glb: bytes | None = None  # heritage.glb, the low-poly main building, when the station has one


@dataclass
class StationCatalogue:
    stations: dict[str, LoadedStation] = field(default_factory=dict)
    # station id (or "catalogue") -> why it was not loaded; logged, reported by /readyz, never served.
    failures: dict[str, str] = field(default_factory=dict)
    common_info: dict[str, Any] = field(default_factory=dict)

    def get(self, station_id: str) -> LoadedStation:
        loaded = self.stations.get(station_id) if STATION_ID_RE.match(station_id or "") else None
        if loaded is None:
            raise StationNotFound(station_id)
        return loaded

    def ids(self) -> list[str]:
        return sorted(self.stations)

    def info(self, station_id: str) -> dict[str, Any]:
        """Passenger information: national helplines plus the station's own info.json."""
        station = self.get(station_id).info
        common = self.common_info
        helplines = common.get("helplines", []) + station.get("helplines", [])
        return {
            "checked_on": station.get("checked_on") or common.get("checked_on"),
            "disclaimer": common.get("disclaimer"),
            "helplines": sorted(helplines, key=lambda h: h.get("priority", 9)),
            "not_used": station.get("not_used", []),
            "facts": station.get("facts"),
            "amenities": station.get("amenities", []),
            "amenity_sources": station.get("amenity_sources", []),
        }


def _json(source: StationSource, relpath: str) -> Any | None:
    raw = source.read(relpath)
    return None if raw is None else json.loads(raw.decode("utf-8"))


def load_station(source: StationSource, entry: CatalogueEntry) -> LoadedStation:
    """Load and fully validate one catalogue entry. Raises ValueError describing the first problems found."""
    raw = _json(source, f"{entry.path}/station.json")
    if raw is None:
        raise ValueError("station.json is missing")
    station = Station.model_validate(raw)
    meta_raw = _json(source, f"{entry.path}/metadata.json")
    metadata = StationMetadata.model_validate(meta_raw) if meta_raw is not None else None
    map_png = source.read(f"{entry.path}/{station.map.image}")
    errors, _ = validate_graph(station, metadata, expected_station_id=entry.station_id)
    errors += check_map_image(station, map_png)
    if errors:
        raise ValueError("; ".join(f"{e.code}: {e.message}" for e in errors[:5]))
    info = _json(source, f"{entry.path}/info.json") or {}
    try:  # the world is decoration: a broken osm.json must not stop the station loading
        world = _json(source, f"{entry.path}/{WORLD_FILE}")
    except ValueError:
        log.warning("Station %s: %s is not valid JSON; serving without a world", entry.station_id, WORLD_FILE)
        world = None
    model = source.read(f"{entry.path}/{MODEL_FILE}")
    return LoadedStation(entry, station, metadata, info, map_png or b"", build_graph(station, metadata),
                         world if isinstance(world, dict) else None, model)


def load_catalogue(source: StationSource) -> StationCatalogue:
    """Read catalogue.json and every station it lists. Never raises: failures are recorded and logged."""
    out = StationCatalogue(common_info=_common_info())
    try:
        raw = _json(source, CATALOGUE_FILE)
        if raw is None:
            raise ValueError(f"{CATALOGUE_FILE} is missing")
        catalogue = Catalogue.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 - a broken catalogue must not stop the rest of the service
        log.error("Station catalogue could not be loaded: %s", _describe(exc))
        out.failures["catalogue"] = _describe(exc)
        return out
    for entry in catalogue.stations:
        try:
            out.stations[entry.station_id] = load_station(source, entry)
        except Exception as exc:  # noqa: BLE001 - one bad station must not hide the others
            log.error("Station %s was not loaded: %s", entry.station_id, _describe(exc))
            out.failures[entry.station_id] = _describe(exc)
    log.info("Loaded %d station(s) for navigation", len(out.stations))
    return out


def _describe(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return f"schema: {exc.error_count()} error(s), first: {exc.errors()[0].get('msg')}"
    return f"{type(exc).__name__}: {exc}"[:500]


def _common_info() -> dict[str, Any]:
    try:
        return json.loads(COMMON_HELPLINES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("National helplines file %s is missing or unreadable", COMMON_HELPLINES)
        return {}
