"""Manually verify the live RailRadar connection (not part of the automated tests).

Usage (from backend/):
    uv run python scripts/check_railradar.py                 # CBE -> MAS, tomorrow
    uv run python scripts/check_railradar.py SBC MAS 2026-10-20

Reads RAILRADAR_API_KEY etc. from backend/.env. Saves the raw response to
scripts/railradar_sample.json so the field mapping can be checked. Never prints the key.
"""

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.providers.errors import ProviderError  # noqa: E402
from app.providers.railradar import RailRadarJourneyProvider  # noqa: E402
from app.providers.railradar_client import RailRadarClient  # noqa: E402
from app.providers.railradar_mapper import MappingError, map_live_status  # noqa: E402

HINTS = {
    "auth_failed": "Check RAILRADAR_API_KEY (no quotes/spaces) and that the key is active on railradar.in.",
    "rate_limited": "Free-tier limit reached; wait and retry, or raise RAILRADAR_CACHE_SECONDS.",
    "timeout": "Network/proxy issue or slow API; raise RAILRADAR_TIMEOUT_SECONDS.",
    "unavailable": "RailRadar is unreachable or returned 5xx; retry later.",
    "bad_request": "Check the station codes and date.",
    "bad_response": "The response shape differs from the mapper. Share scripts/railradar_sample.json.",
}


def describe(value, prefix: str = "") -> list[str]:
    """Field names and value types only (structure, not data)."""
    if isinstance(value, dict):
        lines: list[str] = []
        for key, inner in value.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(inner, dict):
                lines += describe(inner, path)
            else:
                kind = type(inner).__name__
                example = f" e.g. {inner!r}"[:40] if isinstance(inner, (int, float)) or (isinstance(inner, str) and len(inner) < 30) else ""
                lines.append(f"{path}: {kind}{example}")
        return lines
    return [f"{prefix}: {type(value).__name__}"]


def main() -> int:
    settings = Settings()
    args = sys.argv[1:]
    origin, dest = (args[0].upper(), args[1].upper()) if len(args) >= 2 else ("CBE", "MAS")
    tz = ZoneInfo(settings.timezone)
    day = date.fromisoformat(args[2]) if len(args) >= 3 else datetime.now(tz).date() + timedelta(days=1)
    key = settings.railradar_api_key.get_secret_value().strip() if settings.railradar_api_key else ""
    print(f"RAILWAY_DATA_MODE={settings.data_provider}  BASE_URL={settings.railradar_base_url}  "
          f"KEY={'set' if key else '(unset)'}")
    if not key:
        print("Set RAILRADAR_API_KEY in backend/.env first.")
        return 2
    client = RailRadarClient(settings.railradar_base_url, key, settings.railradar_timeout_seconds, cache_seconds=0)
    try:
        fetched = client.trains_between(origin, dest, day)
        raw = fetched.data
        sample = Path(__file__).parent / "railradar_sample.json"
        sample.write_text(json.dumps(raw[:5], indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"1/3 trains_between {origin}->{dest} {day}: {len(raw)} raw records at {fetched.fetched_at:%H:%M:%S %Z} "
              f"(first 5 saved to {sample.name})")
        if raw:
            print("    observed fields of first record:")
            for line in describe(raw[0]):
                print("     ", line)
        provider = RailRadarJourneyProvider(client, settings.timezone)
        options = provider.search([origin], [dest], [day])
        print(f"2/3 mapped {len(options)}/{len(raw)} records:")
        for o in options[:8]:
            leg = o.legs[0]
            fares = ", ".join(f"{c}:₹{v:.0f}" for c, v in o.fares.items()) or "no fares"
            classes = ",".join(c.value for c in o.classes) or "classes unknown"
            print(f"    {leg.train_no:>6} {leg.train_name[:28]:<28} {o.departure:%d %b %H:%M} -> {o.arrival:%d %b %H:%M}"
                  f"  ({o.duration_minutes} min)  [{classes}] {fares}")
        if options:
            train = options[0].legs[0].train_no
            live = client.live_status(train, day).data
            delay, cancelled = map_live_status(live)
            print(f"3/3 live status {train}: delay={delay} cancelled={cancelled}; observed top-level fields: "
                  f"{sorted(live)[:20]}")
    except (ProviderError, MappingError) as err:
        kind = getattr(err, "kind", None)
        print(f"FAILED: {kind.value if kind else 'mapping'} - {err}")
        print("Hint:", HINTS.get(kind.value if kind else "bad_response", "See docs/RAILRADAR_SETUP.md"))
        return 1
    print("RailRadar is working. Set RAILWAY_DATA_MODE=railradar and restart the backend.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
