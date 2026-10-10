"""Simulated disruptions kept in a runtime overlay file per station.

The overlay never edits ``station.json``: the original layout, geometry and
accessibility properties are preserved.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

from app.navigation.models.station import Disruption, DisruptionCreate, Station
from app.navigation.services import station_store

_lock = threading.Lock()


class DisruptionTargetNotFound(Exception):
    pass


def _path(station_id: str):
    return station_store.station_dir(station_id) / "disruptions.json"


def list_disruptions(station_id: str) -> list[Disruption]:
    path = _path(station_id)
    if not path.is_file():
        return []
    return [Disruption.model_validate(d) for d in station_store.read_json_file(path)]


def create_disruption(station: Station, req: DisruptionCreate) -> Disruption:
    if req.target_type == "edge":
        if req.target_id not in {e.id for e in station.edges}:
            raise DisruptionTargetNotFound(f"Unknown edge '{req.target_id}'")
        kind = "pathway_closure"
    else:
        if req.target_id not in {n.id for n in station.nodes}:
            raise DisruptionTargetNotFound(f"Unknown node '{req.target_id}'")
        kind = "facility_outage"
    event = Disruption(
        id=f"sim_{uuid.uuid4().hex[:10]}",
        station_id=station.station_id,
        target_type=req.target_type,
        target_id=req.target_id,
        kind=kind,
        reason=req.reason,
        created_at=datetime.now(timezone.utc),
    )
    with _lock:
        events = list_disruptions(station.station_id)
        events.append(event)
        _write(station.station_id, events)
    return event


def delete_disruption(station_id: str, event_id: str) -> bool:
    with _lock:
        events = list_disruptions(station_id)
        kept = [e for e in events if e.id != event_id]
        if len(kept) == len(events):
            return False
        _write(station_id, kept)
    return True


def clear_disruptions(station_id: str) -> int:
    with _lock:
        n = len(list_disruptions(station_id))
        _write(station_id, [])
    return n


def _write(station_id: str, events: list[Disruption]) -> None:
    station_store.write_json_file(_path(station_id), [e.model_dump(mode="json") for e in events])
