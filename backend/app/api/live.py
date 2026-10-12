"""
API Router for Live Railway Intelligence (Pillars 1, 2 & 3)
Provides real-time station departure boards, NTES schedule tracking, and 600m coach positioning.
"""

import math
from typing import Optional, Dict, Any
from fastapi import APIRouter, Query

from app.navigation.curbside_topology import parse_rake_composition

# No live upstream is wired yet; the LiveSource provider arrives in Phase 5. Until then the
# endpoints below return the bundled sample data and must be treated as illustrative.
ntes = None

router = APIRouter(tags=["Live Railway Operations"])

# Preset Station Coordinates and Geocoding Index
STATIONS_MAP: Dict[str, Dict[str, Any]] = {
    "MAS": {"code": "MAS", "name": "Chennai Central", "city": "Chennai", "latitude": 13.0825, "longitude": 80.2750},
    "VLCY": {"code": "VLCY", "name": "Velachery MRTS", "city": "Chennai", "latitude": 12.9790, "longitude": 80.2185},
    "MS": {"code": "MS", "name": "Chennai Egmore", "city": "Chennai", "latitude": 13.0800, "longitude": 80.2600},
    "NDLS": {"code": "NDLS", "name": "New Delhi", "city": "New Delhi", "latitude": 28.6429, "longitude": 77.2195},
    "CSMT": {"code": "CSMT", "name": "Mumbai CSMT", "city": "Mumbai", "latitude": 18.9400, "longitude": 72.8353},
    "HWH": {"code": "HWH", "name": "Howrah Jn", "city": "Kolkata", "latitude": 22.5839, "longitude": 88.3426},
    "SBC": {"code": "SBC", "name": "KSR Bengaluru", "city": "Bengaluru", "latitude": 12.9774, "longitude": 77.5708},
    "CNB": {"code": "CNB", "name": "Kanpur Central", "city": "Kanpur", "latitude": 26.4547, "longitude": 80.3507},
    "BCT": {"code": "BCT", "name": "Mumbai Central", "city": "Mumbai", "latitude": 18.9696, "longitude": 72.8193},
    "PUNE": {"code": "PUNE", "name": "Pune Junction", "city": "Pune", "latitude": 18.5284, "longitude": 73.8744},
    "HYB": {"code": "HYB", "name": "Hyderabad Deccan", "city": "Hyderabad", "latitude": 17.3923, "longitude": 78.4682},
}

MOCK_MAS_TRAINS = [
    {
        "train_number": "12658",
        "train_name": "Chennai Mail (Overnight)",
        "source": "SBC",
        "destination": "MAS",
        "scheduled_arrival": "04:15",
        "expected_arrival": "04:15",
        "scheduled_departure": "--",
        "expected_departure": "--",
        "platform": "10",
        "delay_arrival": "RT",
        "delay_departure": "--",
        "status": "Arrived",
        "coach_composition": "ENG-SLR-GEN-GEN-S1-S2-S3-S4-S5-S6-B1-B2-B3-B4-B5-A1-A2-H1-GEN-EOG"
    },
    {
        "train_number": "20608",
        "train_name": "Vande Bharat Express",
        "source": "MYS",
        "destination": "MAS",
        "scheduled_arrival": "12:25",
        "expected_arrival": "12:25",
        "scheduled_departure": "--",
        "expected_departure": "--",
        "platform": "11",
        "delay_arrival": "RT",
        "delay_departure": "--",
        "status": "Expected",
        "coach_composition": "ENG-C1-C2-C3-C4-C5-C6-C7-E1-C8-ENG"
    },
    {
        "train_number": "12608",
        "train_name": "Lalbagh Express",
        "source": "SBC",
        "destination": "MAS",
        "scheduled_arrival": "11:35",
        "expected_arrival": "11:45",
        "scheduled_departure": "--",
        "expected_departure": "--",
        "platform": "7",
        "delay_arrival": "00:10",
        "delay_departure": "--",
        "status": "Running Late 10m",
        "coach_composition": "ENG-D1-D2-D3-D4-D5-C1-C2-D6-D7-D8-SLR"
    },
    {
        "train_number": "12008",
        "train_name": "Shatabdi Express",
        "source": "MYS",
        "destination": "MAS",
        "scheduled_arrival": "11:00",
        "expected_arrival": "11:00",
        "scheduled_departure": "--",
        "expected_departure": "--",
        "platform": "9",
        "delay_arrival": "RT",
        "delay_departure": "--",
        "status": "Expected",
        "coach_composition": "ENG-E1-E2-C1-C2-C3-C4-C5-C6-C7-C8-C9-C10-EOG"
    }
]


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


@router.get("/stations/search")
def search_stations(q: str = Query(..., min_length=1, description="Station name or code prefix")):
    query = q.strip().upper()
    matches = []
    for code, info in STATIONS_MAP.items():
        if query in code or query in info["name"].upper():
            matches.append(info)
            if len(matches) >= 20:
                break
    return {"query": q, "results": matches}


@router.get("/stations/nearest")
def get_nearest_station(
    lat: float = Query(..., description="User latitude"),
    lon: float = Query(..., description="User longitude")
):
    closest = None
    min_dist = float("inf")
    for _code, info in STATIONS_MAP.items():
        d = haversine_distance(lat, lon, info["latitude"], info["longitude"])
        if d < min_dist:
            min_dist = d
            closest = {**info, "distance_km": round(d, 2)}
    return closest or {"code": "MAS", "name": "Chennai Central", "distance_km": 0}


@router.get("/stations/{station_code}/live")
def get_station_live(station_code: str, hours: int = Query(2, ge=1, le=4)):
    code = station_code.strip().upper()
    station_meta = STATIONS_MAP.get(code, {"code": code, "name": code, "latitude": 13.0825, "longitude": 80.2750})

    if ntes:
        valid_hours = 4 if hours > 2 else 2
        try:
            raw_res = ntes.station_live(code, hours=valid_hours)
            trains_list = []
            for item in raw_res.get("TrainsAtStation", []):
                trains_list.append({
                    "train_number": item.get("TrainNumber", ""),
                    "train_name": item.get("TrainName", ""),
                    "source": item.get("Source", ""),
                    "destination": item.get("Destination", ""),
                    "scheduled_arrival": item.get("STA", ""),
                    "expected_arrival": item.get("ETA", ""),
                    "scheduled_departure": item.get("STD", ""),
                    "expected_departure": item.get("ETD", ""),
                    "platform": item.get("Platform", "--"),
                    "delay_arrival": item.get("DelayArr", "RT"),
                    "delay_departure": item.get("DelayDep", "--"),
                    "status": "Expected",
                    "coach_composition": item.get("Rake", "ENG-GEN-B1-B2-A1-GEN-SLR")
                })
            if trains_list:
                return {
                    "station_code": code,
                    "station_name": station_meta.get("name", code),
                    "latitude": station_meta.get("latitude"),
                    "longitude": station_meta.get("longitude"),
                    "trains": trains_list
                }
        except Exception:
            pass

    return {
        "station_code": code,
        "station_name": station_meta.get("name", code),
        "latitude": station_meta.get("latitude"),
        "longitude": station_meta.get("longitude"),
        "trains": MOCK_MAS_TRAINS if code == "MAS" else []
    }


@router.get("/trains/{train_number}/schedule")
def get_train_schedule(train_number: str):
    t_no = train_number.strip()
    if ntes:
        try:
            data = ntes.schedule(t_no)
            stops = []
            for s in data.get("stations", []):
                stn_code = (s.get("StationCode") or "").upper().strip()
                stn_meta = STATIONS_MAP.get(stn_code, {})
                stops.append({
                    "serial": s.get("Sr"),
                    "station_code": stn_code,
                    "station_name": s.get("StationName", ""),
                    "arrival_time": s.get("STA", "").strip() or "Source",
                    "departure_time": s.get("STD", "").strip() or "Destination",
                    "halt_minutes": s.get("Halt", "0"),
                    "distance_km": s.get("Distance", 0),
                    "day": s.get("Day", 1),
                    "latitude": stn_meta.get("latitude"),
                    "longitude": stn_meta.get("longitude")
                })
            return {
                "train_number": t_no,
                "train_name": data.get("TrainName", "Express"),
                "total_stations": len(stops),
                "route": stops
            }
        except Exception:
            pass

    return {
        "train_number": t_no,
        "train_name": "Chennai Mail",
        "total_stations": 6,
        "route": [
            {"serial": 1, "station_code": "SBC", "station_name": "KSR Bengaluru", "arrival_time": "Source", "departure_time": "22:45"},
            {"serial": 2, "station_code": "BNC", "station_name": "Bengaluru Cant", "arrival_time": "22:55", "departure_time": "22:57"},
            {"serial": 3, "station_code": "KJM", "station_name": "Krishnarajapuram", "arrival_time": "23:08", "departure_time": "23:10"},
            {"serial": 4, "station_code": "BWT", "station_name": "Bangarapet", "arrival_time": "00:01", "departure_time": "00:02"},
            {"serial": 5, "station_code": "AJJ", "station_name": "Arakkonam", "arrival_time": "03:08", "departure_time": "03:10"},
            {"serial": 6, "station_code": "MAS", "station_name": "Chennai Central", "arrival_time": "04:15", "departure_time": "Destination"}
        ]
    }


@router.get("/plan/journey")
def plan_direct_journey(
    from_station: str = Query(..., description="Origin station code"),
    to_station: str = Query(..., description="Destination station code")
):
    f = from_station.strip().upper()
    t = to_station.strip().upper()
    if ntes:
        try:
            raw_res = ntes.trains_between(f, t)
            trains_list = []
            for tr in raw_res.get("Trains", []):
                trains_list.append({
                    "train_number": tr.get("TrainNumber", ""),
                    "train_name": tr.get("TrainName", ""),
                    "from_station_code": tr.get("FromStation", f),
                    "from_station_name": tr.get("FromStationName", ""),
                    "departure_time": tr.get("DepTimeFrom", ""),
                    "to_station_code": tr.get("toStation", t),
                    "to_station_name": tr.get("ToStationName", ""),
                    "arrival_time": tr.get("ArrTimeTo", ""),
                    "duration": tr.get("TravelTime", ""),
                    "classes": tr.get("Classes", ["1A", "2A", "3A", "SL"])
                })
            if trains_list:
                return {
                    "from_station": f,
                    "to_station": t,
                    "total_trains": len(trains_list),
                    "trains": trains_list
                }
        except Exception:
            pass

    # High-quality fallback for SBC -> MAS
    return {
        "from_station": f,
        "to_station": t,
        "total_trains": 4,
        "trains": [
            {"train_number": "12658", "train_name": "Chennai Mail", "departure_time": "22:45", "arrival_time": "04:15", "duration": "05:30", "classes": ["1A", "2A", "3A", "SL"], "from_station_code": f, "to_station_code": t},
            {"train_number": "20608", "train_name": "Vande Bharat Express", "departure_time": "05:45", "arrival_time": "10:10", "duration": "04:25", "classes": ["EC", "CC"], "from_station_code": f, "to_station_code": t},
            {"train_number": "12008", "train_name": "Shatabdi Express", "departure_time": "06:00", "arrival_time": "11:00", "duration": "05:00", "classes": ["1A", "EC", "CC"], "from_station_code": f, "to_station_code": t},
            {"train_number": "12608", "train_name": "Lalbagh Express", "departure_time": "06:20", "arrival_time": "12:15", "duration": "05:55", "classes": ["CC", "2S"], "from_station_code": f, "to_station_code": t}
        ]
    }


@router.get("/trains/rake-position")
def get_coach_position(
    coach_composition: str = Query(..., description="Coach sequence (e.g. ENG-A1-B1-B2-SL)"),
    target_coach: Optional[str] = Query(None, description="Specific coach code (e.g. B4)")
):
    return parse_rake_composition(coach_composition, target_coach)
