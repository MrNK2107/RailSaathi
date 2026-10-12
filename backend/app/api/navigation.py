"""
API Router for Indoor Concourse Navigation & 2D Station Blueprints (Pillar 5)
Handles curbside gates, FOBs, coach berth markers, and Dijkstra route geometry.
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.config import get_settings
from app.navigation.models.station import RouteRequest, RouteResponse, Station
from app.navigation.services import disruption_store, station_store
from app.navigation.services.geometry import project_to_polyline
from app.navigation.services.graph_builder import StationGraph, build_graph
from app.navigation.services.route_validator import check_route_integrity, validate_graph
from app.navigation.services.routing_engine import RoutingError, find_route
from app.navigation.curbside_topology import get_station_topology

router = APIRouter(tags=["Indoor Concourse Navigation"])


def _graph(station_id: str, apply_disruptions: bool = True) -> tuple[Station, StationGraph]:
    try:
        station = station_store.load_published(station_id)
        metadata = station_store.load_metadata(station_id)
    except Exception as exc:
        raise HTTPException(404, f"Station {station_id} not found in store") from exc

    errors, _ = validate_graph(station, metadata)
    if errors:
        raise HTTPException(
            422,
            {"message": "Station graph is invalid", "errors": [e.model_dump() for e in errors]}
        )
    disruptions = disruption_store.list_disruptions(station_id) if apply_disruptions else []
    return station, build_graph(station, metadata, disruptions)


def _verify(station: Station, resp: RouteResponse) -> list[str]:
    if not resp.segments or not resp.segments[0].partial:
        return check_route_integrity(station, resp.node_ids, resp.edge_ids, resp.geometry)
    first = resp.segments[0]
    edge = next((e for e in station.edges if e.id == first.edge_id), None)
    if edge is None:
        return [f"unknown edge {first.edge_id}"]
    w, h = station.map.width, station.map.height
    if any(project_to_polyline(edge.geometry, p, w, h)[0] > 1.0 for p in first.geometry):
        return [f"partial segment does not lie on {edge.id}"]
    rest = resp.geometry[len(first.geometry) - 1 :]
    return check_route_integrity(station, resp.node_ids[1:], resp.edge_ids[1:], rest) if len(resp.edge_ids) > 1 else []


@router.get("/api/stations")
def list_stations() -> list[dict]:
    out = []
    for sid in station_store.list_station_ids():
        try:
            raw = station_store.load_raw(sid)
            meta = station_store.load_metadata(sid)
            out.append({
                "station_id": sid,
                "station_name": raw.get("station_name", sid),
                "node_count": len(raw.get("nodes", [])),
                "edge_count": len(raw.get("edges", [])),
                "has_draft": station_store.has_draft(sid),
                "data_status": meta.data_status if meta else "unknown",
                "city": meta.city if meta else None,
            })
        except Exception:
            continue
    return out


@router.get("/api/stations/{station_id}")
def get_station_details(station_id: str, draft: bool = Query(False)) -> dict:
    try:
        station_store.ensure_station_exists(station_id)
        source = "draft" if draft and station_store.has_draft(station_id) else "published"
        raw = station_store.load_raw(station_id, draft=source == "draft")
        meta = station_store.load_metadata(station_id)
        return {
            "station": raw,
            "metadata": meta.model_dump(mode="json") if meta else None,
            "source": source,
            "has_draft": station_store.has_draft(station_id),
        }
    except Exception as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/api/stations/{station_id}/map")
def get_station_map(station_id: str) -> FileResponse:
    """The station's blueprint image. Only `map.png` inside an allowlisted station id is served;
    this replaces the former public mount of the whole data directory."""
    try:
        path = station_store.image_path(station_id, "map.png")
    except Exception as exc:
        raise HTTPException(404, "Station map not found") from exc
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/api/stations/{station_id}/info")
def get_station_info(station_id: str) -> dict:
    """Helplines, station facts, and amenities gathered for station."""
    try:
        return station_store.load_info(station_id)
    except Exception as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/stations/{station_code}/navigation")
@router.get("/api/stations/{station_code}/navigation")
def get_navigation_topology(station_code: str):
    """Returns curbside gates, security checkpoints, and FOB connections."""
    topology = get_station_topology(station_code)
    if not topology:
        raise HTTPException(status_code=404, detail=f"Navigation topology not mapped for {station_code.upper()}")
    return topology


@router.post("/api/navigation/route", response_model=RouteResponse)
def calculate_route(req: RouteRequest) -> RouteResponse:
    station, graph = _graph(req.station_id, req.apply_disruptions)
    try:
        resp = find_route(graph, req, get_settings().walking_speed_mps)
    except RoutingError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message}) from exc
    if resp.status == "ok":
        problems = _verify(station, resp)
        if problems:
            raise HTTPException(500, {"message": "Route integrity check failed", "problems": problems})
    return resp


@router.get("/api/disruptions/{station_id}")
def list_disruptions(station_id: str):
    return [d.model_dump(mode="json") for d in disruption_store.list_disruptions(station_id)]
