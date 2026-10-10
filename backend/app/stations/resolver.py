"""Station / city resolution. Never silently substitutes a similar name:
anything other than an exact alias match is returned as ambiguous for the
passenger to confirm."""

import difflib
import re
from dataclasses import dataclass, field

from app.domain.journey import Place
from app.providers.base import JourneyProvider

_NOISE = re.compile(r"\b(railway|station|junction|jn|rly)\b")


def _norm(text: str) -> str:
    cleaned = _NOISE.sub(" ", text.lower())
    return re.sub(r"\s+", " ", cleaned).strip(" .,!?")


@dataclass(frozen=True)
class Resolution:
    status: str  # "resolved" | "ambiguous" | "not_found"
    query: str
    place: Place | None = None
    candidates: list[Place] = field(default_factory=list)


@dataclass(frozen=True)
class TextMatch:
    place: Place
    start: int
    end: int
    alias: str


class StationResolver:
    def __init__(self, provider: JourneyProvider) -> None:
        self._aliases: dict[str, Place] = {}
        for city in provider.cities():
            place = Place(id=city.id, label=city.label, kind="city", station_codes=city.stations)
            for alias in city.aliases:
                self._aliases[alias.lower()] = place
        for st in provider.stations():
            place = Place(id=st.code, label=f"{st.name} ({st.code})", kind="station",
                          station_codes=[st.code])
            # Station codes are matched only by resolve(), never in free text ("MS", "ED"...).
            for alias in [*st.aliases, st.name]:
                self._aliases.setdefault(alias.lower(), place)
        self._by_id = {p.id: p for p in self._aliases.values()}
        # Longest aliases first so "chennai central" wins over "chennai".
        self._ordered = sorted(self._aliases, key=len, reverse=True)

    def place_by_id(self, place_id: str) -> Place | None:
        return self._by_id.get(place_id)

    def all_places(self) -> list[Place]:
        return sorted(self._by_id.values(), key=lambda p: (p.kind, p.label))

    def resolve(self, query: str) -> Resolution:
        q = _norm(query)
        if not q:
            return Resolution(status="not_found", query=query)
        if q in self._aliases:
            return Resolution(status="resolved", query=query, place=self._aliases[q])
        if q.upper() in self._by_id:
            return Resolution(status="resolved", query=query, place=self._by_id[q.upper()])
        candidates = self._fuzzy_candidates(q)
        if candidates:
            return Resolution(status="ambiguous", query=query, candidates=candidates)
        return Resolution(status="not_found", query=query)

    def _fuzzy_candidates(self, q: str) -> list[Place]:
        close = difflib.get_close_matches(q, list(self._aliases), n=5, cutoff=0.75)
        partial = [a for a in self._aliases if len(q) >= 4 and q in a]
        seen: dict[str, Place] = {}
        for alias in [*close, *partial]:
            place = self._aliases[alias]
            seen.setdefault(place.id, place)
        return list(seen.values())[:5]

    def find_in_text(self, text: str) -> list[TextMatch]:
        """Locate known place names inside free text (English or Tamil script)."""
        lowered = text.lower()
        taken: list[tuple[int, int]] = []
        matches: list[TextMatch] = []
        for alias in self._ordered:
            pattern = re.escape(alias)
            if alias.isascii():
                pattern = rf"\b{pattern}\b"
            for m in re.finditer(pattern, lowered):
                if any(m.start() < e and s < m.end() for s, e in taken):
                    continue
                taken.append((m.start(), m.end()))
                matches.append(TextMatch(self._aliases[alias], m.start(), m.end(), alias))
        return sorted(matches, key=lambda tm: tm.start)
