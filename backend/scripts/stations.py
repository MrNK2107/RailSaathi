"""Station authoring CLI: validate, preview, build the catalogue and publish to Cloud Storage.

The runtime only reads station data; this is the one way it changes. Usage (from backend/):
    uv run python scripts/stations.py validate                      # every station under data/stations
    uv run python scripts/stations.py validate chennai_central
    uv run python scripts/stations.py catalogue                     # rewrite data/stations/catalogue.json
    uv run python scripts/stations.py catalogue --check             # fail if catalogue.json is out of date
    uv run python scripts/stations.py preview chennai_central --from ent_wall_tax --to platform_10 --step-free
    uv run python scripts/stations.py publish chennai_central --dest gs://BUCKET/stations

`publish` validates first, uploads the station folder to a new versioned folder
(`<dest>/<station_id>/<version>/`, never overwritten) and then points `<dest>/catalogue.json` at it. Earlier
versions stay in the bucket, so rolling back is re-pointing the catalogue. Credentials come from Application
Default Credentials; bucket IAM is the access control.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import STATIONS_DIR  # noqa: E402
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
from app.navigation.services.station_store import CATALOGUE_FILE, STATION_ID_RE  # noqa: E402

VERSION_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,63}$")
OPTIONAL_FILES = ("metadata.json", "info.json")


# ---- validate -----------------------------------------------------------------------------------------------

def station_ids(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and (p / "station.json").is_file())


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


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
    errors = issues + report.errors
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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
