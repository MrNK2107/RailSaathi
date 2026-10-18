"""Station authoring CLI: validate, preview, build the catalogue and publish to Cloud Storage.

The runtime only reads station data; this is the one way it changes. Usage (from backend/):
    uv run python scripts/stations.py validate                      # every station under data/stations
    uv run python scripts/stations.py validate chennai_central
    uv run python scripts/stations.py catalogue                     # rewrite data/stations/catalogue.json
    uv run python scripts/stations.py catalogue --check             # fail if catalogue.json is out of date
    uv run python scripts/stations.py preview chennai_central --from ent_wall_tax --to platform_10 --step-free
    uv run python scripts/stations.py publish chennai_central --dest gs://BUCKET/stations
    uv run python scripts/stations.py panoramas chennai_central --radius 150 --out panos.json
    uv run python scripts/stations.py osm chennai_central           # OpenStreetMap footprints -> osm.json
    uv run python scripts/stations.py align chennai_central         # fit the traced plan to osm.json

`publish` validates first, uploads the station folder to a new versioned folder
(`<dest>/<station_id>/<version>/`, never overwritten) and then points `<dest>/catalogue.json` at it. Earlier
versions stay in the bucket, so rolling back is re-pointing the catalogue. Credentials come from Application
Default Credentials; bucket IAM is the access control.

`panoramas` lists Street View pano ids near the station's geo_reference (Street View Static API metadata
endpoint, key from GOOGLE_MAPS_API_KEY) with their plan position and nearest node, so an author can map them to
nodes in station.json. It stores metadata only, never imagery, as the Google Maps terms require.

`osm` runs one read-only Overpass query (or reads a saved response with --input) and writes the station's
`osm.json`: building, platform, rail and subway footprints in metres from the OSM station node. Commit the file;
the runtime never calls Overpass. Data (c) OpenStreetMap contributors, ODbL-1.0.

`align` fits the hand-traced plan onto `osm.json` (platform footprints; see app/navigation/alignment.py) and
writes `world_alignment` into metadata.json: a similarity transform from plan metres (x, -y) to (east, north)
metres, or a translation when the similarity residual exceeds 15 m. `geo_reference` is never touched; `validate`
errors when the recorded residual is over the limit.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import STATIONS_DIR  # noqa: E402
from app.navigation.alignment import RESIDUAL_LIMIT_M, fit, fit_points, fit_similarity, pair_platforms  # noqa: E402
from app.navigation.models.station import (  # noqa: E402
    Catalogue,
    CatalogueEntry,
    RoutePreferences,
    RouteRequest,
    Station,
    StationMetadata,
    ValidationIssue,
    ValidationReport,
)
from app.navigation.services.graph_builder import build_graph  # noqa: E402
from app.navigation.services.route_validator import check_map_image, validate_station_data  # noqa: E402
from app.navigation.services.routing_engine import find_route  # noqa: E402
from app.navigation.services.station_store import CATALOGUE_FILE, MODEL_FILE, STATION_ID_RE  # noqa: E402
from app.navigation.world import WORLD_FILE, elements_to_features, to_local  # noqa: E402

VERSION_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,63}$")
OPTIONAL_FILES = ("metadata.json", "info.json", WORLD_FILE)


# ---- validate -----------------------------------------------------------------------------------------------

def station_ids(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and (p / "station.json").is_file())


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def check_alignment(metadata: StationMetadata | None) -> list[ValidationIssue]:
    """The recorded world_alignment residual must be within RESIDUAL_LIMIT_M."""
    alignment = ((metadata.model_extra or {}) if metadata else {}).get("world_alignment")
    if not isinstance(alignment, dict):
        return []
    residual = alignment.get("residual_m")
    if not isinstance(residual, (int, float)) or isinstance(residual, bool):
        return [ValidationIssue(level="error", code="alignment_invalid",
                                message="world_alignment.residual_m is missing or not a number")]
    if residual > RESIDUAL_LIMIT_M:
        return [ValidationIssue(level="error", code="alignment_residual_high",
                                message=f"world_alignment residual {residual} m is over the {RESIDUAL_LIMIT_M} m limit")]
    return []


def validate_station(root: Path, station_id: str) -> ValidationReport:
    """Schema, graph, step-free, level, area, panorama, cue and map-image checks for one station folder."""
    folder = root / station_id
    issues: list[ValidationIssue] = []
    if not STATION_ID_RE.match(station_id):
        issues.append(ValidationIssue(level="error", code="invalid_station_id",
                                      message=f"Folder name '{station_id}' is not a valid station id"))
    if not (folder / "station.json").is_file():
        issues.append(ValidationIssue(level="error", code="missing_station", message="station.json is missing"))
        return ValidationReport(valid=False, errors=issues, warnings=[])
    metadata = None
    if (folder / "metadata.json").is_file():
        try:
            metadata = StationMetadata.model_validate(_read_json(folder / "metadata.json"))
        except ValueError as exc:
            issues.append(ValidationIssue(level="error", code="invalid_metadata", message=str(exc)[:300]))
    try:
        raw = _read_json(folder / "station.json")
    except ValueError as exc:
        issues.append(ValidationIssue(level="error", code="invalid_json", message=f"station.json: {exc}"))
        return ValidationReport(valid=False, errors=issues, warnings=[])
    report = validate_station_data(raw, metadata, expected_station_id=station_id)
    errors = issues + report.errors + check_alignment(metadata)
    if report.valid:
        station = Station.model_validate(raw)
        image = folder / station.map.image
        errors += check_map_image(station, image.read_bytes() if image.is_file() else None)
    return ValidationReport(valid=not errors, errors=errors, warnings=report.warnings)


def _print_report(station_id: str, report: ValidationReport) -> None:
    state = "OK" if report.valid else "INVALID"
    print(f"{station_id}: {state} ({len(report.errors)} error(s), {len(report.warnings)} warning(s))")
    for issue in report.errors + report.warnings:
        print(f"  {issue.level.upper():7} {issue.code}: {issue.message}")


def cmd_validate(args) -> int:
    root = Path(args.root)
    ids = args.stations or station_ids(root)
    if not ids:
        print(f"No stations found under {root}")
        return 1
    ok = True
    for sid in ids:
        report = validate_station(root, sid)
        _print_report(sid, report)
        ok &= report.valid
    return 0 if ok else 1


# ---- catalogue ----------------------------------------------------------------------------------------------

def local_entry(root: Path, station_id: str) -> CatalogueEntry:
    station = _read_json(root / station_id / "station.json")
    meta_path = root / station_id / "metadata.json"
    meta = StationMetadata.model_validate(_read_json(meta_path)) if meta_path.is_file() else None
    return CatalogueEntry(
        station_id=station_id,
        station_name=station["station_name"],
        city=meta.city if meta else None,
        data_status=meta.data_status if meta else "mock",
        version="local",
        path=station_id,
    )


def build_local_catalogue(root: Path) -> Catalogue:
    return Catalogue(stations=[local_entry(root, sid) for sid in station_ids(root)])


def catalogue_text(catalogue: Catalogue) -> str:
    return json.dumps(catalogue.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


def cmd_catalogue(args) -> int:
    root = Path(args.root)
    invalid = [sid for sid in station_ids(root) if not validate_station(root, sid).valid]
    if invalid:
        print(f"Refusing to build the catalogue: invalid station(s) {', '.join(invalid)} (run validate)")
        return 1
    catalogue = build_local_catalogue(root)
    path = root / CATALOGUE_FILE
    if args.check:
        current = Catalogue.model_validate_json(path.read_bytes()) if path.is_file() else None
        if current != catalogue:
            print(f"{path} is out of date; run: uv run python scripts/stations.py catalogue")
            return 1
        print(f"{path} is up to date")
        return 0
    path.write_bytes(catalogue_text(catalogue).encode("utf-8"))
    print(f"Wrote {path}")
    return 0


# ---- preview ------------------------------------------------------------------------------------------------

def _load_station(root: Path, station_id: str) -> tuple[Station, StationMetadata | None]:
    folder = root / station_id
    meta = folder / "metadata.json"
    return (Station.model_validate(_read_json(folder / "station.json")),
            StationMetadata.model_validate(_read_json(meta)) if meta.is_file() else None)


def render_preview(root: Path, station_id: str, source: str | None, destination: str | None,
                   step_free: bool, out: Path) -> str:
    """Draw every pathway (stepped ones in orange) and, when asked, a route on the station map. Returns a summary."""
    from PIL import Image, ImageDraw

    station, metadata = _load_station(root, station_id)
    image = Image.open(root / station_id / station.map.image).convert("RGB")
    w, h = image.size
    draw = ImageDraw.Draw(image)

    def px(points):
        return [(x * w, y * h) for x, y in points]

    for e in station.edges:
        colour = (230, 120, 0) if e.stepped else (110, 110, 110)
        draw.line(px(e.geometry), fill=colour, width=3)
    summary = f"{station_id}: {len(station.nodes)} nodes, {len(station.edges)} pathways"
    if source and destination:
        prefs = RoutePreferences(wheelchair=step_free, avoid_stairs=step_free)
        req = RouteRequest(station_id=station_id, source=source, destination=destination, preferences=prefs)
        route = find_route(build_graph(station, metadata), req)
        if route.status == "ok":
            draw.line(px(route.geometry), fill=(0, 90, 220), width=9)
            dist = route.estimated_distance_m
            summary += (f"; route {source} -> {destination} via {len(route.edge_ids)} pathway(s)"
                        + (f", about {dist:.0f} m (estimate)" if dist is not None else ""))
        else:
            summary += f"; no route {source} -> {destination}: {route.explanation}"
    for n in station.nodes:
        x, y = n.position[0] * w, n.position[1] * h
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=(200, 0, 60) if n.type.value == "entrance" else (20, 20, 20))
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, format="PNG")
    return summary


def cmd_preview(args) -> int:
    if bool(args.source) != bool(args.destination):
        print("Give both --from and --to, or neither")
        return 2
    out = Path(args.out or f"{args.station}-preview.png")
    print(render_preview(Path(args.root), args.station, args.source, args.destination, args.step_free, out))
    print(f"Wrote {out}")
    return 0


# ---- publish ------------------------------------------------------------------------------------------------

def _storage_client():
    from google.cloud import storage

    return storage.Client()


def _parse_dest(dest: str) -> tuple[str, str]:
    if not dest.startswith("gs://"):
        raise ValueError("--dest must look like gs://bucket/prefix")
    bucket, _, prefix = dest[5:].partition("/")
    if not bucket:
        raise ValueError("--dest must look like gs://bucket/prefix")
    return bucket, prefix.strip("/")


def publish(root: Path, station_id: str, dest: str, version: str | None = None, client=None) -> str:
    """Upload a validated station to a new version folder and point the bucket catalogue at it. Returns the folder.

    Objects are created with if_generation_match=0, so an existing version is never overwritten, and the
    catalogue is replaced with if_generation_match on the generation read, so concurrent publishes cannot lose an
    entry (the loser fails and can retry)."""
    bucket_name, prefix = _parse_dest(dest)
    version = version or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if not VERSION_RE.match(version):
        raise ValueError(f"Invalid version '{version}'")
    report = validate_station(root, station_id)
    if not report.valid:
        raise ValueError(f"{station_id} is invalid ({len(report.errors)} error(s)); run validate")
    bucket = (client or _storage_client()).bucket(bucket_name)

    def key(rel: str) -> str:
        return f"{prefix}/{rel}" if prefix else rel

    folder = root / station_id
    station = Station.model_validate(_read_json(folder / "station.json"))
    files = [("station.json", "application/json"), (station.map.image, "image/png")]
    files += [(name, "application/json") for name in OPTIONAL_FILES if (folder / name).is_file()]
    if (folder / MODEL_FILE).is_file():
        files.append((MODEL_FILE, "model/gltf-binary"))
    rel_folder = f"{station_id}/{version}"
    for name, content_type in files:
        bucket.blob(key(f"{rel_folder}/{name}")).upload_from_string(
            (folder / name).read_bytes(), content_type=content_type, if_generation_match=0)

    current = bucket.get_blob(key(CATALOGUE_FILE))
    catalogue = (Catalogue.model_validate_json(current.download_as_bytes()) if current is not None
                 else Catalogue())
    entry = local_entry(root, station_id).model_copy(update={"version": version, "path": rel_folder})
    stations = [s for s in catalogue.stations if s.station_id != station_id] + [entry]
    updated = Catalogue(stations=sorted(stations, key=lambda s: s.station_id))
    blob = bucket.blob(key(CATALOGUE_FILE))
    blob.cache_control = "no-cache"
    blob.upload_from_string(catalogue_text(updated), content_type="application/json",
                            if_generation_match=current.generation if current is not None else 0)
    return f"gs://{bucket_name}/{key(rel_folder)}"


def cmd_publish(args) -> int:
    try:
        where = publish(Path(args.root), args.station, args.dest, args.version)
    except ValueError as exc:
        print(f"Not published: {exc}")
        return 1
    print(f"Published {args.station} to {where} and updated the catalogue")
    return 0


# ---- panoramas ----------------------------------------------------------------------------------------------

STREET_VIEW_METADATA_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"
EARTH_RADIUS_M = 6_371_008.8
MAX_PANORAMA_QUERIES = 400
FATAL_STATUSES = frozenset({"REQUEST_DENIED", "OVER_QUERY_LIMIT", "INVALID_REQUEST", "UNKNOWN_ERROR"})


class PanoramaLookupError(Exception):
    pass


def _geo_reference(metadata: StationMetadata | None) -> dict:
    geo = ((metadata.model_extra or {}) if metadata else {}).get("geo_reference")
    if not isinstance(geo, dict) or not isinstance(geo.get("anchor"), dict):
        raise PanoramaLookupError("metadata.json has no geo_reference anchor")
    return geo


def offset_latlon(lat: float, lon: float, east_m: float, north_m: float) -> tuple[float, float]:
    """Small-offset (equirectangular) move from (lat, lon)."""
    return (lat + math.degrees(north_m / EARTH_RADIUS_M),
            lon + math.degrees(east_m / (EARTH_RADIUS_M * math.cos(math.radians(lat)))))


def latlon_to_plan(station: Station, geo: dict, mpp: float, lat: float, lon: float) -> tuple[float, float]:
    """Inverse of the geo_reference: anchor point, metres per pixel and the rotation of plan-up from north
    (degrees clockwise)."""
    anchor = geo["anchor"]
    north = math.radians(lat - anchor["lat"]) * EARTH_RADIUS_M
    east = math.radians(lon - anchor["lon"]) * EARTH_RADIUS_M * math.cos(math.radians(anchor["lat"]))
    rot = math.radians(float(geo.get("rotation_deg") or 0))
    right = east * math.cos(rot) - north * math.sin(rot)  # along plan x
    up = east * math.sin(rot) + north * math.cos(rot)  # along plan-up
    x = anchor["x"] + right / mpp / station.map.width
    y = anchor["y"] - up / mpp / station.map.height
    return round(x, 5), round(y, 5)


def sample_points(radius_m: float, step_m: float) -> list[tuple[float, float]]:
    """(east, north) offsets on a square grid clipped to the circle, centre first."""
    n = int(radius_m // step_m)
    points = [(i * step_m, j * step_m) for i in range(-n, n + 1) for j in range(-n, n + 1)
              if math.hypot(i * step_m, j * step_m) <= radius_m]
    return sorted(points, key=lambda p: math.hypot(*p))


def find_panoramas(root: Path, station_id: str, api_key: str, radius_m: float = 150, step_m: float = 30,
                   source: str = "default", client=None) -> list[dict]:
    """Query the Street View metadata endpoint on a grid around the geo_reference and return each distinct pano
    with its location, plan position and nearest node. Metadata only: no imagery is requested or stored."""
    import httpx

    station, metadata = _load_station(root, station_id)
    if metadata is None or metadata.map_scale is None:
        raise PanoramaLookupError("metadata.json needs map_scale.metres_per_pixel")
    geo = _geo_reference(metadata)
    mpp = metadata.map_scale.metres_per_pixel
    if step_m <= 0 or radius_m <= 0:
        raise PanoramaLookupError("--radius and --step must be positive")
    points = sample_points(radius_m, step_m)
    if len(points) > MAX_PANORAMA_QUERIES:
        raise PanoramaLookupError(f"{len(points)} queries needed; increase --step or reduce --radius")
    anchor = geo["anchor"]
    w, h = station.map.width, station.map.height
    http = client or httpx.Client(timeout=10.0)
    found: dict[str, dict] = {}
    try:
        for east, north in points:
            lat, lon = offset_latlon(anchor["lat"], anchor["lon"], east, north)
            params = {"location": f"{lat:.6f},{lon:.6f}", "radius": str(max(1, round(step_m))), "source": source,
                      "key": api_key}
            try:
                res = http.get(STREET_VIEW_METADATA_URL, params=params)
                res.raise_for_status()
                body = res.json()
            except (httpx.HTTPError, ValueError):  # the request URL carries the key: report the type only
                raise PanoramaLookupError("Street View metadata request failed") from None
            status = body.get("status")
            if status in FATAL_STATUSES:
                raise PanoramaLookupError(f"Street View metadata API answered {status}")
            pano_id = body.get("pano_id")
            if status != "OK" or not pano_id or pano_id in found:
                continue
            loc = body.get("location") or {}
            plat, plon = float(loc["lat"]), float(loc["lng"])
            x, y = latlon_to_plan(station, geo, mpp, plat, plon)
            nearest = min(station.nodes, key=lambda n: math.hypot((n.position[0] - x) * w, (n.position[1] - y) * h))
            node_m = math.hypot((nearest.position[0] - x) * w, (nearest.position[1] - y) * h) * mpp
            copyright_ = str(body.get("copyright") or "")
            found[pano_id] = {
                "pano_id": pano_id, "lat": plat, "lng": plon, "date": body.get("date"), "copyright": copyright_,
                "kind": "street_view" if "Google" in copyright_ else "photosphere",
                "plan_position": [x, y], "inside_plan": 0 <= x <= 1 and 0 <= y <= 1,
                "nearest_node": nearest.id, "nearest_node_m": round(node_m, 1),
            }
    finally:
        if client is None:
            http.close()
    return sorted(found.values(), key=lambda p: p["nearest_node_m"])


def cmd_panoramas(args) -> int:
    api_key = os.environ.get(args.key_env, "").strip()
    if not api_key:
        print(f"Set {args.key_env} to a Maps Platform key with the Street View Static API enabled")
        return 2
    try:
        panos = find_panoramas(Path(args.root), args.station, api_key, args.radius, args.step, args.source)
    except PanoramaLookupError as exc:
        print(f"Panorama lookup failed: {exc}")
        return 1
    text = json.dumps({"station_id": args.station, "radius_m": args.radius, "panoramas": panos}, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Wrote {len(panos)} panorama(s) to {args.out}")
    else:
        print(text, end="")
    print("Map each pano to a node in station.json panoramas (heading, kind, verified_on once checked).",
          file=sys.stderr)
    return 0


# ---- osm ----------------------------------------------------------------------------------------------------

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OSM_DEFAULT_BBOX = (13.0780, 80.2690, 13.0905, 80.2790)  # s, w, n, e: widened north so platforms 1-11 fit
# The origin is the OSM station node. The heritage way is the main building's footprint, chosen by looking at the
# building ways around the forecourt: 214739119 is the longest (about 120 m) and the one nearest the road the
# station faces (3 m); OSM tags it building=roof, layer=1 (the front block and its colonnade). Poonamallee High
# Road is mapped as EVR Periyar Salai, which lies 540 m west and is not the road beside the forecourt.
OSM_ORIGINS = {"chennai_central": {"node": 2481969291, "lat": 13.0824232, "lon": 80.2759622,
                                   "heritage_way": "way/214739119"}}
OSM_USER_AGENT = "gdg-devfest-station-tooling/1.0 (offline OSM extract for a station tour)"


class WorldBuildError(Exception):
    pass


def overpass_query(bbox: tuple[float, float, float, float]) -> str:
    b = ",".join(f"{v:.4f}" for v in bbox)
    parts = [
        f'way["building"]({b});',
        f'relation["building"]({b});',
        f'way["railway"~"^(rail|platform|subway|station)$"]({b});',
        f'way["public_transport"~"^(platform|station)$"]({b});',
        f'relation["railway"="station"]({b});',
        f'way["highway"~"^(footway|pedestrian|corridor)$"]["tunnel"]["layer"~"^-"]({b});',
    ]
    nl = chr(10)
    return f"[out:json][timeout:90];{nl}({nl}  " + f"{nl}  ".join(parts) + f"{nl});{nl}out geom;"


def fetch_overpass(query: str, client=None, pause_s: float = 10.0) -> dict:
    """One read-only Overpass POST; a single retry after a pause when it fails or is rate limited."""
    import time

    import httpx

    http = client or httpx.Client(timeout=120.0)
    headers = {"User-Agent": OSM_USER_AGENT, "Accept": "application/json"}
    last: Exception | None = None
    try:
        for attempt in range(2):
            try:
                res = http.post(OVERPASS_URL, data={"data": query}, headers=headers)
                res.raise_for_status()
                return res.json()
            except (httpx.HTTPError, ValueError) as exc:
                last = exc
                if attempt == 0:
                    time.sleep(pause_s)
    finally:
        if client is None:
            http.close()
    raise WorldBuildError(f"Overpass request failed twice: {last!r}")


def build_world(overpass_json: dict, station_id: str, bbox, query: str, heritage_way: str | None = None) -> dict:
    origin = OSM_ORIGINS.get(station_id)
    if origin is None:
        raise WorldBuildError(f"no OSM origin configured for {station_id}")
    heritage = heritage_way or origin["heritage_way"]
    origin = {"lat": origin["lat"], "lon": origin["lon"]}
    features = elements_to_features(overpass_json, origin, heritage)
    if not any(f["id"] == heritage and f["kind"] == "heritage" for f in features):
        raise WorldBuildError(f"heritage building {heritage} is not in the data")
    return {
        "source": "OpenStreetMap",
        "attribution": "© OpenStreetMap contributors",
        "licence": "ODbL-1.0",
        "osm_timestamp": str((overpass_json.get("osm3s") or {}).get("timestamp_osm_base", "")),
        "bbox": list(bbox),
        "query": query,
        "origin": origin,
        "heritage_way": heritage,
        "features": features,
    }


def cmd_osm(args) -> int:
    root = Path(args.root)
    if args.station not in station_ids(root):
        print(f"Unknown station {args.station!r}")
        return 2
    try:
        bbox = tuple(float(v) for v in args.bbox.split(",")) if args.bbox else OSM_DEFAULT_BBOX
        if len(bbox) != 4 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
            raise ValueError
    except ValueError:
        print("--bbox must be south,west,north,east")
        return 2
    query = overpass_query(bbox)
    try:
        if args.input:
            data = json.loads(Path(args.input).read_text(encoding="utf-8"))
        else:
            data = fetch_overpass(query)
        world = build_world(data, args.station, bbox, query, args.heritage_way)
    except (WorldBuildError, OSError, ValueError) as exc:
        print(f"OSM extract failed: {exc}")
        return 1
    out = root / args.station / WORLD_FILE
    out.write_text(json.dumps(world, separators=(",", ":"), ensure_ascii=False) + chr(10), encoding="utf-8")
    kinds: dict[str, int] = {}
    for f in world["features"]:
        kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
    print(f"Wrote {len(world['features'])} feature(s) to {out} ({kinds}); heritage {world['heritage_way']}")
    return 0


# ---- align --------------------------------------------------------------------------------------------------

def build_alignment(station: dict, metadata: dict, world: dict) -> dict:
    """The world_alignment block for a station: traced platforms fitted to OSM platforms (see alignment.py)."""
    w, h = station["map"]["width"], station["map"]["height"]
    mpp = metadata["map_scale"]["metres_per_pixel"]
    pairs, info = pair_platforms(station["areas"], world["features"], w, h, mpp)
    src, dst = fit_points(pairs)
    method, sim = fit(src, dst)
    mpairs, _ = pair_platforms(station["areas"], world["features"], w, h, mpp, mirror=True,
                               window_ids=sorted({p["feature"] for p in pairs}, key=[p["feature"] for p in pairs].index))
    msim = fit_similarity(*fit_points(mpairs))
    runner = info["runner_up"]
    block = {
        "method": method,
        "scale": round(sim.scale, 4),
        "rotation_deg": round(sim.rotation_deg, 3),
        "tx": round(sim.tx, 2),
        "ty": round(sim.ty, 2),
        "residual_m": round(sim.residual_m, 2),
        "frame": "plan metres (x, -y) -> OSM (east, north) metres from osm.json origin; "
                 "world = scale * R(rotation_deg) * (x, -y) + (tx, ty)",
        "pairs": [{"area": p["area"], "osm": p["feature"], "osm_ref": p["ref"]} for p in pairs],
        "platform_labels": [{"area": p["area"], "label": str(p["number"]), "osm_ref": p["ref"],
                             "label_source": "station_plan", "osm_ref_agrees": p["ref_agrees"]} for p in pairs],
        "candidates_tried": info["candidates_tried"],
        "runner_up": {**runner, "note": "Second-best run of OSM islands; side-to-side placement is uncertain by "
                                        "about one island (~20 m)."} if runner else None,
        "parity_check": {
            "mirrored_residual_m": round(msim.residual_m, 2),
            "mirrored_transform": {"scale": round(msim.scale, 4), "rotation_deg": round(msim.rotation_deg, 3),
                                   "tx": round(msim.tx, 2), "ty": round(msim.ty, 2),
                                   "applied": "plan y is not negated: world = scale * R(rotation_deg) * (x, +y) + "
                                              "(tx, ty), i.e. the plan mirrored across its platform axis, fitted to "
                                              "the same OSM islands"},
            "mirrored_pairs": [{"area": p["area"], "osm": p["feature"], "osm_ref": p["ref"]} for p in mpairs],
        },
        "parity_basis": "Default is the proper (non-mirrored) fit because the brief forbids reflection. The "
                        "residual cannot tell the two apart (see parity_check). Evidence for mirrored: Wikipedia "
                        "(Chennai Central / Wall Tax Road) says Wall Tax Road runs along the station's east side "
                        "and its entrance leads to platform 1, so platform numbers rise westward, matching the OSM "
                        "refs, while the proper fit puts plan platform 12 east of plan platform 7. Evidence for "
                        "proper: ent_wall_tax lands on the east side under it, but that node sits on the plan's "
                        "'MAIN ENTRANCE (Jawaharlal Nehru Road)' label, so this is weak. Status: unconfirmed, "
                        "needs a user or site check.",
        "source": "Traced platform strips 7-12 (building end and mid-length point) fitted to OpenStreetMap platform "
                  "footprints in osm.json, two traced platforms per OSM island platform; (c) OpenStreetMap "
                  "contributors, ODbL-1.0.",
        "verification": "pending",
    }
    if method == "translation":
        block["fallback_reason"] = (f"similarity residual exceeded {RESIDUAL_LIMIT_M} m; translation only "
                                    "(scale 1, rotation 0)")
    return block


def cmd_align(args) -> int:
    folder = Path(args.root) / args.station
    try:
        station, metadata = _read_json(folder / "station.json"), _read_json(folder / "metadata.json")
        world = _read_json(folder / WORLD_FILE)
        block = build_alignment(station, metadata, world)
    except (OSError, ValueError, KeyError) as exc:
        print(f"{args.station}: cannot align: {exc}")
        return 1
    metadata["world_alignment"] = block
    (folder / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
                                           encoding="utf-8")
    print(f"{args.station}: {block['method']} scale={block['scale']} rotation={block['rotation_deg']} deg "
          f"t=({block['tx']}, {block['ty']}) residual={block['residual_m']} m")
    for p in block["platform_labels"]:
        print(f"  {p['area']:18} -> {p['osm_ref']:5} (plan label {p['label']}, ref agrees: {p['osm_ref_agrees']})")
    return 0


# ---- entry point --------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default=str(STATIONS_DIR), help="station data directory (default: %(default)s)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="validate station folders")
    p.add_argument("stations", nargs="*")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("catalogue", help="write catalogue.json from the station folders")
    p.add_argument("--check", action="store_true", help="only check that catalogue.json is up to date")
    p.set_defaults(func=cmd_catalogue)

    p = sub.add_parser("preview", help="draw pathways and an optional route on the map")
    p.add_argument("station")
    p.add_argument("--from", dest="source")
    p.add_argument("--to", dest="destination")
    p.add_argument("--step-free", action="store_true", help="route without stairs, steps or escalators")
    p.add_argument("--out", help="output PNG (default: ./<station>-preview.png)")
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser("publish", help="upload a validated station to Cloud Storage")
    p.add_argument("station")
    p.add_argument("--dest", required=True, help="gs://bucket/prefix")
    p.add_argument("--version", help="version folder name (default: UTC timestamp)")
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("panoramas", help="list Street View pano ids near the station (metadata only)")
    p.add_argument("station")
    p.add_argument("--radius", type=float, default=150, help="search radius in metres (default: %(default)s)")
    p.add_argument("--step", type=float, default=30, help="grid spacing in metres (default: %(default)s)")
    p.add_argument("--source", choices=("default", "outdoor"), default="default",
                   help="'outdoor' excludes indoor and user photospheres")
    p.add_argument("--key-env", default="GOOGLE_MAPS_API_KEY", help="environment variable holding the API key")
    p.add_argument("--out", help="write the JSON here instead of stdout")
    p.set_defaults(func=cmd_panoramas)

    p = sub.add_parser("osm", help="write osm.json (OpenStreetMap footprints) for a station")
    p.add_argument("station")
    p.add_argument("--bbox", help="south,west,north,east (default: %s)" % ",".join(map(str, OSM_DEFAULT_BBOX)))
    p.add_argument("--input", help="read a saved Overpass response instead of querying the API")
    p.add_argument("--heritage-way", help="way/<id> of the main building (default: the station's configured footprint)")
    p.set_defaults(func=cmd_osm)

    p = sub.add_parser("align", help="fit the traced plan to osm.json and write metadata.json world_alignment")
    p.add_argument("station")
    p.set_defaults(func=cmd_align)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
