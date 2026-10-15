"""`GET /api/client-config`: what the browser needs at start-up and nothing else.

The Google Maps key here is the public, referrer-restricted browser key (GOOGLE_MAPS_BROWSER_KEY, mounted from
Secret Manager on Cloud Run). Without it the value is null and the tour links out to Google Maps instead."""

from fastapi import APIRouter, Request

from app.api.localize import ar_guidance_stations

router = APIRouter(tags=["system"])


@router.get("/api/client-config")
async def client_config(request: Request) -> dict:
    c = request.app.state.container
    key = (c.settings.google_maps_browser_key or "").strip() or None
    return {"google_maps_browser_key": key, "features": {"ar_guidance_stations": ar_guidance_stations(c)}}
