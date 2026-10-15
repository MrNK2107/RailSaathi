"""Internal endpoints called by Google Cloud services, never by browsers. Protected by Cloud Run OIDC."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import offload
from app.api.internal_auth import require_internal_caller
from app.delay.observations import collect_observations
from app.navigation.models.station import DisruptionCreate
from app.navigation.services.disruption_store import DisruptionTargetNotFound, new_disruption
from app.navigation.services.station_store import StationCatalogue, StationNotFound

log = logging.getLogger("railsaathi.internal")
router = APIRouter(prefix="/internal", tags=["internal"], include_in_schema=False)


@router.post("/collect")
async def collect(request: Request, _caller: str = Depends(require_internal_caller)) -> dict:
    """Sample live status for recently seen trains and append the fresh observations to storage."""
    c = request.app.state.container
    if c.live is None or c.seen_trains is None or c.observation_sink is None:
        raise HTTPException(503, detail={"code": "collector_unavailable",
                                         "message": "The observation collector is not set up."})
    try:
        return await offload(collect_observations, c.live, c.seen_trains, c.observation_sink, c.clock,
                             c.settings.observation_max_trains)
    except Exception:  # noqa: BLE001 - storage errors must not leak details
        log.exception("Observation collection failed")
        raise HTTPException(502, detail={"code": "collect_failed",
                                         "message": "Observations could not be saved."}) from None


# ---- station disruptions (written only here; read publicly via GET /api/disruptions/{station_id}) -------------

def _station_and_store(request: Request, station_id: str):
    c = request.app.state.container
    try:
        loaded = (c.stations or StationCatalogue()).get(station_id)
    except StationNotFound:
        raise HTTPException(404, detail={"code": "station_not_found", "message": "Station not found."}) from None
    if c.station_disruptions is None:
        raise HTTPException(503, detail={"code": "disruptions_unavailable",
                                         "message": "The disruption store is not set up."})
    return c, loaded, c.station_disruptions


@router.post("/stations/{station_id}/disruptions", status_code=201)
async def create_station_disruption(request: Request, station_id: str, body: DisruptionCreate,
                                    caller: str = Depends(require_internal_caller)) -> dict:
    c, loaded, store = _station_and_store(request, station_id)
    if body.simulated and c.settings.is_production:
        raise HTTPException(403, detail={"code": "simulation_disabled",
                                         "message": "Simulated disruptions are refused in production."})
    try:
        disruption = new_disruption(loaded.station, body, c.clock.now(), c.settings.disruption_ttl_seconds)
    except DisruptionTargetNotFound as exc:
        raise HTTPException(404, detail={"code": "unknown_target", "message": str(exc)}) from None
    await offload(store.add, disruption)
    log.info("Station disruption %s added for %s by %s", disruption.id, station_id, caller)
    return disruption.model_dump(mode="json")


@router.delete("/stations/{station_id}/disruptions/{disruption_id}")
async def delete_station_disruption(request: Request, station_id: str, disruption_id: str,
                                    caller: str = Depends(require_internal_caller)) -> dict:
    _, _, store = _station_and_store(request, station_id)
    if not await offload(store.delete, station_id, disruption_id):
        raise HTTPException(404, detail={"code": "disruption_not_found", "message": "Disruption not found."})
    log.info("Station disruption %s removed for %s by %s", disruption_id, station_id, caller)
    return {"deleted": disruption_id}


@router.delete("/stations/{station_id}/disruptions")
async def clear_station_disruptions(request: Request, station_id: str,
                                    caller: str = Depends(require_internal_caller)) -> dict:
    _, _, store = _station_and_store(request, station_id)
    cleared = await offload(store.clear, station_id)
    log.info("Station disruptions cleared for %s by %s (%d)", station_id, caller, cleared)
    return {"cleared": cleared}
