"""A small two-level test station and helpers to write it as a station data root.

    ent ── hall ──stairs── p1 ──lift(+1)── fob ── fob2
            │               │               │       │
            j ────ramp──────┘    escalator(-1)    lift(-1)
                                            └── p2 ─┘

`hall -> p1` by stairs is the short way; `hall -> j -> p1` by ramp is the step-free way. From the bridge, the
escalator is the short way down to p2 and the second lift the step-free one.
"""

import copy
import io
import json
from pathlib import Path

MAP_W, MAP_H = 1000, 1000


def _node(nid, ntype, x, y, level=0, **kw):
    return {"id": nid, "name": nid.upper(), "type": ntype, "position": [x, y], "level": level,
            "verification": "pending", "step_free": "unknown", "status": "open", **kw}


def _edge(eid, a, b, path_type, points, level_change=0, **kw):
    return {"id": eid, "from": a, "to": b, "bidirectional": True, "path_type": path_type,
            "level_change": level_change, "step_free": "unknown", "status": "open", "verification": "pending",
            "geometry": points, **kw}


BASE = {
    "schema_version": 2,
    "station_id": "test_station",
    "station_name": "Test Station",
    "map": {"image": "map.png", "width": MAP_W, "height": MAP_H},
    "nodes": [
        _node("ent", "entrance", 0.1, 0.5),
        _node("hall", "concourse", 0.3, 0.5),
        _node("j", "junction", 0.3, 0.9),
        _node("p1", "platform", 0.5, 0.5),
        _node("fob", "foot_over_bridge", 0.5, 0.2, level=1),
        _node("fob2", "junction", 0.8, 0.2, level=1),
        _node("p2", "platform", 0.6, 0.6),
    ],
    "edges": [
        _edge("e_ent_hall", "ent", "hall", "walkway", [[0.1, 0.5], [0.3, 0.5]]),
        _edge("e_stairs", "hall", "p1", "stairs", [[0.3, 0.5], [0.5, 0.5]], steps=12),
        _edge("e_hall_j", "hall", "j", "walkway", [[0.3, 0.5], [0.3, 0.7], [0.3, 0.9]]),
        _edge("e_ramp", "j", "p1", "ramp", [[0.3, 0.9], [0.5, 0.9], [0.5, 0.7], [0.5, 0.5]]),
        _edge("e_lift_up", "p1", "fob", "lift", [[0.5, 0.5], [0.5, 0.2]], level_change=1),
        _edge("e_escalator", "fob", "p2", "escalator", [[0.5, 0.2], [0.55, 0.4], [0.6, 0.6]], level_change=-1),
        _edge("e_bridge", "fob", "fob2", "walkway", [[0.5, 0.2], [0.8, 0.2]]),
        _edge("e_lift_down", "fob2", "p2", "lift", [[0.8, 0.2], [0.8, 0.4], [0.8, 0.6], [0.6, 0.6]], level_change=-1),
    ],
}

METADATA = {
    "station_id": "test_station",
    "station_name": "Test Station",
    "city": "Testpur",
    "map_scale": {"metres_per_pixel": 0.1, "source": "test", "verification": "pending"},
    "data_status": "mock",
}


def station_raw(**overrides) -> dict:
    raw = copy.deepcopy(BASE)
    raw.update(overrides)
    return raw


def png_bytes(width: int = MAP_W, height: int = MAP_H) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, format="PNG")
    return buf.getvalue()


def write_station(root: Path, raw: dict | None = None, metadata: dict | None = None,
                  image: bytes | None = None, folder: str | None = None) -> Path:
    raw = raw or station_raw()
    path = root / (folder or raw["station_id"])
    path.mkdir(parents=True, exist_ok=True)
    (path / "station.json").write_text(json.dumps(raw), encoding="utf-8")
    (path / "metadata.json").write_text(json.dumps(metadata or METADATA), encoding="utf-8")
    (path / "map.png").write_bytes(image if image is not None else png_bytes())
    (path / "info.json").write_text(json.dumps({"facts": {"note": "test"}}), encoding="utf-8")
    return path


def write_catalogue(root: Path, entries: list[dict]) -> None:
    (root / "catalogue.json").write_text(json.dumps({"schema_version": 1, "stations": entries}), encoding="utf-8")


def entry(station_id: str = "test_station", path: str | None = None, version: str = "local") -> dict:
    return {"station_id": station_id, "station_name": station_id, "data_status": "mock", "version": version,
            "path": path or station_id}


def station_root(tmp_path: Path, raw: dict | None = None) -> Path:
    root = tmp_path / "stations"
    write_station(root, raw)
    write_catalogue(root, [entry()])
    return root
