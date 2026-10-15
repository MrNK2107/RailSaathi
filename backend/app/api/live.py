"""Live station information: station search, departure boards, train schedules and running status.

Everything comes from the container's LiveSource (RailRadar in live mode, simulated data only outside production).
Every response carries `provenance` ({mode, source, as_of, note}); a board, schedule or status that cannot be
served is returned with `provenance.mode == "unavailable"` and a `reason`, never with placeholder data."""

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Request

from app.api.deps import offload
from app.navigation.curbside_topology import parse_rake_composition
from app.providers.live_source import DepartureBoard, LiveSource, TrainLiveStatus, TrainSchedule, UnknownStation

router = APIRouter(prefix="/api", tags=["Live Railway Operations"])

# Codes are interpolated into upstream URL paths, so only short alphanumerics are accepted.
StationCode = Annotated[str, Path(pattern=r"^[A-Za-z0-9]{1,8}$", description="Station code, e.g. MAS")]
TrainNo = Annotated[str, Path(pattern=r"^[A-Za-z0-9]{1,8}$", description="Train number, e.g. 12658")]


def _live(request: Request) -> LiveSource:
    live = request.app.state.container.live
    if live is None:
        raise HTTPException(503, detail={"code": "live_unavailable", "message": "Live station data is not set up."})
    return live


@router.get("/live/stations/search")
async def search_stations(request: Request,
                          q: str = Query(..., min_length=1, max_length=40, description="Station name, city or code")):
    live = _live(request)
    return {"query": q, "results": [p.as_dict() for p in live.directory.search(q)],
            "provenance": live.catalogue_provenance()}


@router.get("/live/stations/nearest")
async def nearest_station(request: Request,
                          lat: float = Query(..., ge=-90, le=90, description="Latitude"),
                          lon: float = Query(..., ge=-180, le=180, description="Longitude")):
    live = _live(request)
    hit = live.directory.nearest(lat, lon)
    station = {**hit[0].as_dict(), "distance_km": round(hit[1], 2)} if hit else None
    return {"station": station, "provenance": live.catalogue_provenance()}


@router.get("/live/stations/{station_code}/departures", response_model=DepartureBoard)
async def station_departures(request: Request, station_code: StationCode,
                             hours: int = Query(2, ge=1, le=4, description="Look-ahead window in hours")):
    live = _live(request)
    try:
        return await offload(live.departures, station_code.upper(), hours)
    except UnknownStation:
        raise HTTPException(404, detail={"code": "unknown_station",
                                         "message": "This station is not in RailSaathi's station catalogue."}) from None


@router.get("/live/trains/{train_no}/schedule", response_model=TrainSchedule)
async def train_schedule(request: Request, train_no: TrainNo):
    return await offload(_live(request).schedule, train_no.upper())


@router.get("/live/trains/{train_no}/status", response_model=TrainLiveStatus)
async def train_status(request: Request, train_no: TrainNo,
                       run_date: date | None = Query(None, alias="date",
                                                     description="Boarding date (YYYY-MM-DD); default today")):
    container = request.app.state.container
    today = container.clock.now().date()
    day = run_date or today
    if not (today - timedelta(days=2) <= day <= today + timedelta(days=1)):
        raise HTTPException(422, detail={"code": "date_out_of_range",
                                         "message": "Running status is available from two days ago to tomorrow."})
    return await offload(_live(request).live_status, train_no.upper(), day)


@router.get("/trains/rake-position")
async def get_coach_position(
    coach_composition: str = Query(..., max_length=400, description="Coach sequence (e.g. ENG-A1-B1-B2-SL)"),
    target_coach: str | None = Query(None, max_length=8, description="Specific coach code (e.g. B4)"),
):
    return parse_rake_composition(coach_composition, target_coach)
