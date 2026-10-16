"""`GET /api/client-config`: what the browser needs at start-up and nothing else.

The Google Maps key here is the public, referrer-restricted browser key (GOOGLE_MAPS_BROWSER_KEY, mounted from
Secret Manager on Cloud Run). Without it the value is null and the tour links out to Google Maps instead.

`features.simulate_closures` mirrors the gate on POST /api/navigation/route (`simulate_closures` is refused with 403
`simulation_disabled` unless `settings.disruption_simulation_enabled`), so the app offers the what-if closure tool only
where the backend accepts it.

`features.ar_guidance_stations` lists the stations where camera guidance works now (the data opts in, the per-station
`AR_GUIDANCE_ENABLED` flag is on and a Gemini vision localiser exists). `features.ar_capable_stations` lists every
station whose data opts in, whatever the flags: the app shows a disabled AR tab with the reason for the ones not in
the first list. It is a discovery hint only; POST /api/stations/{id}/localize keeps its own gate."""

from fastapi import APIRouter, Request

from app.api.localize import ar_capable_stations, ar_guidance_stations

router = APIRouter(tags=["system"])


@router.get("/api/client-config")
async def client_config(request: Request) -> dict:
    c = request.app.state.container
    key = (c.settings.google_maps_browser_key or "").strip() or None
    return {"google_maps_browser_key": key, "features": {
        "ar_guidance_stations": ar_guidance_stations(c),
        "ar_capable_stations": ar_capable_stations(c),
        "simulate_closures": c.settings.disruption_simulation_enabled,
    }}
