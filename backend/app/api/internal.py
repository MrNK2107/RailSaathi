"""Internal endpoints called by Google Cloud services, never by browsers. Protected by Cloud Run OIDC."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import offload
from app.api.internal_auth import require_internal_caller
from app.delay.observations import collect_observations

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
