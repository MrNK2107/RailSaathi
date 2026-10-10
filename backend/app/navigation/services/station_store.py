"""File-based persistence for station graphs.

Layout per station (``data/stations/<station_id>/``):

- ``station.json``        published graph used by the routing engine
- ``station.draft.json``  editor draft (optional, never used for routing)
- ``metadata.json``       station metadata, including the map scale if known
- ``map.png``             blueprint image
- ``backups/``            timestamped copies made before every overwrite
- ``disruptions.json``    runtime overlay of simulated disruptions
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.navigation.models.station import Station, StationMetadata

STATION_ID_RE = re.compile(r"^[a-z0-9_]{1,64}$")
BACKUP_NAME_RE = re.compile(r"^station\.\d{8}T\d{6}_\d{6}Z\.json$")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".svg"}


class StationNotFound(Exception):
    pass


class InvalidStationId(Exception):
    pass


def _check_id(station_id: str) -> str:
    if not STATION_ID_RE.match(station_id):
        raise InvalidStationId(station_id)
    return station_id


def station_dir(station_id: str) -> Path:
    return get_settings().data_dir / _check_id(station_id)


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def list_station_ids() -> list[str]:
    root = get_settings().data_dir
    if not root.is_dir():
        return []
    return sorted(
        p.name for p in root.iterdir() if p.is_dir() and STATION_ID_RE.match(p.name) and (p / "station.json").is_file()
    )


def load_raw(station_id: str, draft: bool = False) -> dict:
    d = station_dir(station_id)
    path = d / ("station.draft.json" if draft else "station.json")
    if not path.is_file():
        raise StationNotFound(station_id)
    return _read_json(path)


def has_draft(station_id: str) -> bool:
    return (station_dir(station_id) / "station.draft.json").is_file()


def load_station(station_id: str) -> Station:
    return Station.model_validate(load_raw(station_id))


def load_metadata(station_id: str) -> StationMetadata | None:
    path = station_dir(station_id) / "metadata.json"
    if not path.is_file():
        return None
    return StationMetadata.model_validate(_read_json(path))


def _backup_current(station_id: str) -> str | None:
    d = station_dir(station_id)
    current = d / "station.json"
    if not current.is_file():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    backups = d / "backups"
    backups.mkdir(exist_ok=True)
    name = f"station.{stamp}.json"
    shutil.copy2(current, backups / name)
    _prune_backups(backups)
    return name


def _prune_backups(backups: Path) -> None:
    keep = get_settings().max_backups
    files = sorted(p for p in backups.iterdir() if BACKUP_NAME_RE.match(p.name))
    for old in files[:-keep] if keep > 0 else []:
        old.unlink()


def save_published(station: Station) -> str | None:
    """Back up the current published graph, then write the new one. Returns the backup name."""
    backup = _backup_current(station.station_id)
    _atomic_write_json(station_dir(station.station_id) / "station.json", station.to_json_dict())
    draft = station_dir(station.station_id) / "station.draft.json"
    if draft.exists():
        draft.unlink()
    return backup


def save_draft(station_id: str, data: dict) -> None:
    _atomic_write_json(station_dir(station_id) / "station.draft.json", data)


def discard_draft(station_id: str) -> bool:
    draft = station_dir(station_id) / "station.draft.json"
    if draft.exists():
        draft.unlink()
        return True
    return False


def list_backups(station_id: str) -> list[str]:
    backups = station_dir(station_id) / "backups"
    if not backups.is_dir():
        return []
    return sorted((p.name for p in backups.iterdir() if BACKUP_NAME_RE.match(p.name)), reverse=True)


def load_backup(station_id: str, name: str) -> dict:
    if not BACKUP_NAME_RE.match(name):
        raise StationNotFound(name)
    path = station_dir(station_id) / "backups" / name
    if not path.is_file():
        raise StationNotFound(name)
    return _read_json(path)


def image_path(station_id: str, filename: str) -> Path:
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise StationNotFound(filename)
    path = station_dir(station_id) / filename
    if path.suffix.lower() not in IMAGE_EXTENSIONS or not path.is_file():
        raise StationNotFound(filename)
    return path


def read_json_file(path: Path) -> Any:
    return _read_json(path)


def write_json_file(path: Path, data: Any) -> None:
    _atomic_write_json(path, data)


def load_info(station_id: str) -> dict:
    """Passenger information: national helplines + station-specific info (both optional files)."""
    from app.config import REPO_ROOT

    common = None
    for root in (get_settings().data_dir.parent / "common", REPO_ROOT / "data" / "common"):
        if (root / "helplines_india.json").is_file():
            common = _read_json(root / "helplines_india.json")
            break
    path = station_dir(station_id) / "info.json"
    station = _read_json(path) if path.is_file() else {}
    helplines = (common or {}).get("helplines", []) + station.get("helplines", [])
    return {
        "checked_on": station.get("checked_on") or (common or {}).get("checked_on"),
        "disclaimer": (common or {}).get("disclaimer"),
        "helplines": sorted(helplines, key=lambda h: h.get("priority", 9)),
        "not_used": station.get("not_used", []),
        "facts": station.get("facts"),
        "amenities": station.get("amenities", []),
        "amenity_sources": station.get("amenity_sources", []),
    }
