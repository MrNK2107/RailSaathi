"""Indoor station navigation: read-only station data, routing over prebuilt graphs, and the disruption overlay.

Everything here is read-only. Stations are authored and published with `scripts/stations.py`; disruptions are
written only through the OIDC-protected internal endpoints in `app/api/internal.py`.
"""

import logging
from datetime import UTC, date, datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from redis.exceptions import RedisError

from app.api.deps import offload
from app.container import Container
from app.domain.enums import DataMode
from app.domain.options import DataProvenance
from app.navigation.models.station import RouteRequest, RouteResponse, Station
from app.navigation.services.geometry import project_to_polyline
from app.navigation.services.graph_builder import UnknownClosureTarget, apply_closures
from app.navigation.services.route_validator import check_route_integrity
from app.navigation.services.routing_engine import RoutingError, find_route
from app.navigation.services.station_store import LoadedStation, StationCatalogue, StationNotFound

log = logging.getLogger("railsaathi.navigation")
router = APIRouter(tags=["Indoor Concourse Navigation"])
DISRUPTIONS_UNAVAILABLE = "Current closure information is unavailable, so closures may not be reflected in this route."


def _c(request: Request) -> Container:
    return request.app.state.container


def _catalogue(c: Container) -> StationCatalogue:
    return c.stations or StationCatalogue()


def _station(c: Container, station_id: str) -> LoadedStation:
    try:
        return _catalogue(c).get(station_id)
    except StationNotFound:
        raise HTTPException(404, {"code": "station_not_found", "message": "Station not found."}) from None


PROVENANCE_SOURCE = "RailSaathi station catalogue (schematic)"
PROVENANCE_NOTE = "The layout is schematic: not surveyed, not to scale. Verify on site and ask station staff."


def _layout_basis(loaded: LoadedStation) -> str:
    extra = (loaded.metadata.model_extra or {}) if loaded.metadata else {}
    return loaded.info.get("layout_basis") or extra.get("layout_basis") or "unknown"


def _routing_enabled(loaded: LoadedStation) -> bool:
    return loaded.metadata.routing if loaded.metadata else False


def _station_code(loaded: LoadedStation) -> str | None:
    facts = loaded.info.get("facts")
    code = facts.get("station_code") if isinstance(facts, dict) else None
    return code.strip().upper() if isinstance(code, str) and code.strip() else None


def _provenance(c: Container, loaded: LoadedStation) -> DataProvenance:
    """Station layouts are authored static data, so they are reported as `cached`, dated by the authoring check."""
    try:
        as_of = datetime.combine(date.fromisoformat(str(loaded.info.get("checked_on"))), datetime.min.time(), UTC)
    except ValueError:
        as_of = c.clock.now()
    return DataProvenance(mode=DataMode.CACHED, source=PROVENANCE_SOURCE, as_of=as_of, note=PROVENANCE_NOTE)


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
async def list_stations(request: Request) -> list[dict]:
    catalogue = _catalogue(_c(request))
    out = []
    for sid in catalogue.ids():
        loaded = catalogue.get(sid)
        out.append({
            "station_id": sid,
            "station_name": loaded.station.station_name,
            "node_count": len(loaded.station.nodes),
            "edge_count": len(loaded.station.edges),
            "version": loaded.entry.version,
            "data_status": loaded.metadata.data_status if loaded.metadata else loaded.entry.data_status,
            "city": loaded.metadata.city if loaded.metadata else loaded.entry.city,
            # Indian Railways station code from info.json facts (e.g. MAS), so a journey leg can find its floor plan.
            "station_code": _station_code(loaded),
        })
    return out


@router.get("/api/stations/{station_id}")
async def get_station_details(request: Request, station_id: str) -> dict:
    loaded = _station(_c(request), station_id)
    return {
        "station": loaded.station.to_json_dict(),
        "metadata": loaded.metadata.model_dump(mode="json") if loaded.metadata else None,
        "version": loaded.entry.version,
        "layout_basis": _layout_basis(loaded),
        "routing_enabled": _routing_enabled(loaded),
        "provenance": _provenance(_c(request), loaded).model_dump(mode="json"),
    }


@router.get("/api/stations/{station_id}/map")
async def get_station_map(request: Request, station_id: str) -> Response:
    """The station's plan image, served from the loaded catalogue (never a mount of the data directory)."""
    loaded = _station(_c(request), station_id)
    return Response(loaded.map_png, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/api/stations/{station_id}/model.glb")
async def get_station_model(request: Request, station_id: str) -> Response:
    """The station's low-poly heritage building (plain glTF binary), served from the loaded catalogue."""
    loaded = _station(_c(request), station_id)
    if not loaded.model_glb:
        raise HTTPException(404, {"code": "model_not_found", "message": "This station has no 3D model."})
    return Response(loaded.model_glb, media_type="model/gltf-binary", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/api/stations/{station_id}/info")
async def get_station_info(request: Request, station_id: str) -> dict:
    """Helplines, station facts, and amenities gathered for the station."""
    c = _c(request)
    loaded = _station(c, station_id)
    return {**_catalogue(c).info(station_id), "layout_basis": _layout_basis(loaded),
            "layout_note": loaded.info.get("layout_note"), "provenance": _provenance(c, loaded).model_dump(mode="json")}


TOUR_FRAME = ("Metres from the plan's top-left corner: x to the right, y down the plan. Bearings are degrees clockwise "
              "from plan-up; geo_reference.rotation_deg relates plan-up to true north.")


MODEL_HEIGHT_M = 41  # the heritage clock tower; the model is built to this (scripts/build_station_model.py)


def _world_block(loaded: LoadedStation) -> dict | None:
    """OpenStreetMap footprints, the plan-to-world alignment and the heritage model, or None without osm.json."""
    world = loaded.world
    if not world:
        return None
    extra = (loaded.metadata.model_extra or {}) if loaded.metadata else {}
    heritage = world.get("heritage_way")
    model = None
    if loaded.model_glb and heritage:
        model = {"url": f"/api/stations/{loaded.station.station_id}/model.glb", "feature_id": heritage,
                 "height_m": MODEL_HEIGHT_M}
    return {"attribution": world.get("attribution"), "licence": world.get("licence"),
            "osm_timestamp": world.get("osm_timestamp"), "features": world.get("features", []),
            "alignment": extra.get("world_alignment"), "model": model}


@router.get("/api/stations/{station_id}/tour")
async def get_station_tour(request: Request, station_id: str) -> dict:
    """Everything the 3D tour draws, in one payload: levels, areas and the graph in metres, and panoramas."""
    c = _c(request)
    loaded = _station(c, station_id)
    station, meta = loaded.station, loaded.metadata
    extra = (meta.model_extra or {}) if meta else {}
    scale = meta.map_scale if meta else None
    w, h = station.map.width, station.map.height

    def m(point) -> list[float] | None:
        if scale is None:
            return None
        return [round(point[0] * w * scale.metres_per_pixel, 2), round(point[1] * h * scale.metres_per_pixel, 2)]

    def path_m(points) -> list[list[float]] | None:
        return None if scale is None else [m(p) for p in points]

    return {
        "station_id": station.station_id,
        "station_name": station.station_name,
        "version": loaded.entry.version,
        "layout_basis": _layout_basis(loaded),
        "routing_enabled": _routing_enabled(loaded),
        "ar_enabled": station.ar_enabled,
        "ar_guidance_available": station.ar_enabled and c.settings.ar_guidance_on(station_id) and c.vision is not None,
        "map": {"url": f"/api/stations/{station.station_id}/map", "width_px": w, "height_px": h},
        "scale": None if scale is None else {
            "metres_per_pixel": scale.metres_per_pixel, "width_m": round(w * scale.metres_per_pixel, 2),
            "height_m": round(h * scale.metres_per_pixel, 2), "source": scale.source,
            "verification": scale.verification},
        "frame": TOUR_FRAME,
        "geo_reference": extra.get("geo_reference"),
        "levels": [lv.model_dump(mode="json") for lv in station.levels],
        "areas": [{"id": a.id, "kind": a.kind, "name": a.name, "level": a.level, "height_m": a.height_m,
                   "polygon": [list(p) for p in a.polygon], "polygon_m": path_m(a.polygon)} for a in station.areas],
        "nodes": [{"id": n.id, "name": n.name, "type": n.type.value, "level": n.level, "position": list(n.position),
                   "position_m": m(n.position), "verification": n.verification, "step_free": n.step_free,
                   "status": n.status, "cues": [cue.model_dump(mode="json") for cue in n.cues]}
                  for n in station.nodes],
        "edges": [{"id": e.id, "from": e.from_, "to": e.to, "bidirectional": e.bidirectional,
                   "path_type": e.path_type.value, "level_change": e.level_change, "steps": e.steps,
                   "step_free": e.step_free, "status": e.status, "verification": e.verification,
                   "distance_m": e.distance_m, "geometry": [list(p) for p in e.geometry],
                   "geometry_m": path_m(e.geometry)} for e in station.edges],
        "panoramas": [p.model_dump(mode="json") for p in station.panoramas],
        "panoramas_note": extra.get("panoramas_note"),
        "world": _world_block(loaded),
        "provenance": _provenance(c, loaded).model_dump(mode="json"),
    }


@router.post("/api/navigation/route", response_model=RouteResponse)
async def calculate_route(request: Request, req: RouteRequest) -> RouteResponse:
    return await offload(_calculate_route, _c(request), req)


def _calculate_route(c: Container, req: RouteRequest) -> RouteResponse:
    loaded = _station(c, req.station_id)
    if not _routing_enabled(loaded):
        raise HTTPException(503, {"code": "routing_unavailable", "message": (
            "Step-by-step directions are not available for this station: its layout is a schematic that has not been "
            "traced from a plan or surveyed. The map and station information are still available.")})
    if req.simulate_closures and not c.settings.disruption_simulation_enabled:
        raise HTTPException(403, {"code": "simulation_disabled",
                                  "message": "Simulated closures are not available on this service."})
    disruptions, overlay_missing = [], False
    if req.apply_disruptions and c.station_disruptions is not None:
        try:
            disruptions = c.station_disruptions.list(req.station_id)
        except (RedisError, OSError):
            log.warning("Disruption store unavailable; routing without closures", exc_info=True)
            overlay_missing = True
    try:
        graph = apply_closures(loaded.graph, disruptions, req.simulate_closures)
    except UnknownClosureTarget as exc:
        raise HTTPException(404, {"code": "unknown_closure_target",
                                  "message": f"Unknown node or edge '{exc.args[0]}' in simulate_closures."}) from None
    try:
        resp = find_route(graph, req, c.settings.walking_speed_mps)
    except RoutingError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message}) from exc
    resp.provenance = _provenance(c, loaded)
    if overlay_missing:
        resp.warnings.insert(0, DISRUPTIONS_UNAVAILABLE)
    if resp.status == "ok":
        problems = _verify(loaded.station, resp)
        if problems:
            # Internal node/edge ids stay in the server log; the passenger gets a generic, actionable message.
            log.error("Route integrity check failed for %s: %s", loaded.station.station_id, "; ".join(problems))
            raise HTTPException(500, {"code": "route_integrity_failed",
                                      "message": "This route failed a safety check, so it is not shown. Please try "
                                                 "again or ask station staff for directions."})
    return resp


@router.get("/api/disruptions/{station_id}")
async def list_disruptions(request: Request, station_id: str) -> list[dict]:
    c = _c(request)
    _station(c, station_id)
    if c.station_disruptions is None:
        return []
    try:
        disruptions = await offload(c.station_disruptions.list, station_id)
    except (RedisError, OSError):
        log.warning("Disruption store unavailable", exc_info=True)
        raise HTTPException(503, {"code": "disruptions_unavailable",
                                  "message": "Current closure information is unavailable."}) from None
    return [d.model_dump(mode="json") for d in disruptions]
