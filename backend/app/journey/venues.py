"""Venue directory for the goal planner, loaded from `data/common/venues.json` and validated by Pydantic.

A venue lists its access stations with the straight-line distance to each; last-mile times derived from that are
estimates and labelled as such. Unknown venues are not guessed: the planner asks the passenger for the station."""

import json
import math
import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.config import DATA_DIR

VENUES_PATH = DATA_DIR / "common" / "venues.json"
URBAN_CAB_KMH = 22.0  # average urban cab speed including traffic
STATION_EXIT_MINUTES = 8.0  # leaving the station and boarding a cab


class AccessStation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[A-Z]{1,6}$")
    distance_km: float = Field(ge=0, le=200)


class Venue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=1)
    aliases: list[str]
    city: str
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    access_stations: list[AccessStation]

    def distance_to(self, station_code: str) -> float | None:
        return next((s.distance_km for s in self.access_stations if s.code == station_code), None)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


class VenueDirectory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notice: str | None = Field(default=None, alias="_notice")
    venues: list[Venue]

    def find(self, query: str) -> Venue | None:
        """Exact match on id, name or alias (case and punctuation insensitive). No fuzzy guessing."""
        q = _norm(query)
        if not q:
            return None
        for venue in self.venues:
            names = {_norm(venue.id), _norm(venue.name), *(_norm(a) for a in venue.aliases)}
            if q in names:
                return venue
        return None


def estimate_last_mile_minutes(distance_km: float) -> int:
    """Cab time for a straight-line distance at urban speed, plus a station exit allowance (minimum 10)."""
    if distance_km <= 0.5:
        return 5
    return max(int(math.ceil(distance_km / URBAN_CAB_KMH * 60.0 + STATION_EXIT_MINUTES)), 10)


@lru_cache(maxsize=4)
def load_venues(path: Path = VENUES_PATH) -> VenueDirectory:
    return VenueDirectory.model_validate(json.loads(path.read_text(encoding="utf-8")))
