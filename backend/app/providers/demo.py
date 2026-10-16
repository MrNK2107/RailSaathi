"""Deterministic demo provider backed by bundled JSON fixtures (simulated data)."""

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.domain.enums import DataMode, TravelClass
from app.domain.options import DataProvenance, JourneyOption, Leg
from app.providers.base import CityRecord, DisruptionEvent, StationRecord

DATA_DIR = Path(__file__).parent / "data"
DEMO_SOURCE = "RailSaathi sample timetable"


def _load(name: str) -> dict:
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def _at(day: date, hhmm: str, offset: int, tz: ZoneInfo) -> datetime:
    hh, mm = (int(p) for p in hhmm.split(":"))
    return datetime.combine(day + timedelta(days=offset), time(hh, mm), tzinfo=tz)


class DemoJourneyProvider:
    def __init__(self, tz: str = "Asia/Kolkata") -> None:
        self._tz = ZoneInfo(tz)
        stations_doc = _load("stations.json")
        journeys_doc = _load("journeys.json")
        self._cities = [CityRecord(**c) for c in stations_doc["cities"]]
        self._stations = {s["code"]: StationRecord(**s) for s in stations_doc["stations"]}
        self._services = journeys_doc["services"]
        self._as_of = datetime.fromisoformat(journeys_doc["as_of"])

    @property
    def data_mode(self) -> DataMode:
        return DataMode.DEMO

    def provenance(self) -> DataProvenance:
        return DataProvenance(
            mode=DataMode.DEMO,
            source=DEMO_SOURCE,
            as_of=self._as_of,
            note="Illustrative journeys and fares. Not real Indian Railways schedules, "
            "fares or availability.",
        )

    def cities(self) -> list[CityRecord]:
        return list(self._cities)

    def stations(self) -> list[StationRecord]:
        return list(self._stations.values())

    def station(self, code: str) -> StationRecord | None:
        return self._stations.get(code)

    def search(
        self, origin_codes: list[str], destination_codes: list[str], departure_dates: list[date]
    ) -> list[JourneyOption]:
        results: list[JourneyOption] = []
        for service in self._services:
            legs = service["legs"]
            if legs[0]["from"] not in origin_codes or legs[-1]["to"] not in destination_codes:
                continue
            for day in departure_dates:
                results.append(self._build_option(service, day))
        return results

    def _build_option(self, service: dict, day: date) -> JourneyOption:
        legs = [self._build_leg(raw, day) for raw in service["legs"]]
        buffers = [
            int((nxt.departure - prev.arrival).total_seconds() // 60)
            for prev, nxt in zip(legs, legs[1:])
        ]
        codes = [legs[0].from_code] + [leg.to_code for leg in legs]
        return JourneyOption(
            option_id=f"{service['id']}@{day.isoformat()}",
            legs=legs,
            departure=legs[0].departure,
            arrival=legs[-1].arrival,
            duration_minutes=int((legs[-1].arrival - legs[0].departure).total_seconds() // 60),
            transfers=len(legs) - 1,
            min_transfer_minutes=min(buffers) if buffers else None,
            fares={TravelClass(k): float(v) for k, v in service["fares"].items()},
            station_codes=codes,
            provenance=self.provenance(),
        )

    def _build_leg(self, raw: dict, day: date) -> Leg:
        origin = self._stations[raw["from"]]
        dest = self._stations[raw["to"]]
        return Leg(
            train_no=raw["train_no"],
            train_name=raw["name"],
            from_code=origin.code,
            from_name=origin.name,
            to_code=dest.code,
            to_name=dest.name,
            departure=_at(day, raw["dep"], raw["dep_day"], self._tz),
            arrival=_at(day, raw["arr"], raw["arr_day"], self._tz),
        )


class DemoDisruptionSource:
    def __init__(self) -> None:
        doc = _load("disruptions.json")
        prov = DataProvenance(
            mode=DataMode.DEMO,
            source="RailSaathi simulated disruption feed",
            as_of=datetime.fromisoformat("2026-10-01T00:00:00+05:30"),
            note="Simulated events. Not NTES or official railway alerts.",
        )
        self._events = {
            e["id"]: DisruptionEvent(**e, simulated=True, provenance=prov) for e in doc["events"]
        }

    def list_events(self) -> list[DisruptionEvent]:
        return list(self._events.values())

    def get_event(self, event_id: str) -> DisruptionEvent | None:
        return self._events.get(event_id)
