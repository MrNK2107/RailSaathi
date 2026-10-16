"""Optional live smoke test of the NTES source (the unofficial ntes-client). NOT run in CI.

Hits the real NTES service exactly three times, through RailSaathi's own adapters (quota gate, cache, mapping):
  1. the Chennai Central (MAS) station board,
  2. the schedule of train 12658,
  3. trains between MAS and SBC (KSR Bengaluru),
and prints a short summary of each mapped answer plus the raw record keys, so a change in NTES's response shape
shows up here first.

    cd backend && uv run python scripts/ntes_smoke.py

Exit code 0 when all three answered, 1 otherwise (for example when the network or NTES blocks the client)."""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.clock import SystemClock  # noqa: E402
from app.domain.enums import DataMode  # noqa: E402
from app.infra.async_bridge import run_sync  # noqa: E402
from app.providers.live_source import NtesLiveSource  # noqa: E402
from app.providers.ntes import NtesJourneyProvider  # noqa: E402
from app.providers.ntes_client import NtesClient  # noqa: E402
from app.providers.station_directory import StationDirectory  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def main() -> int:
    client = NtesClient(timeout_seconds=15, requests_per_minute=10)
    provider = NtesJourneyProvider(client, budget_seconds=30)
    live = NtesLiveSource(client, StationDirectory(provider.stations()), SystemClock("Asia/Kolkata"),
                          timeout_seconds=30)
    ok = True

    print("1. MAS station board (next 4 hours)")
    board = live.departures("MAS", 4)
    print(f"   provenance: {board.provenance.mode.value} | {board.provenance.source} | {board.provenance.as_of:%Y-%m-%d %H:%M} IST")
    if board.provenance.mode is DataMode.UNAVAILABLE:
        ok = False
        print(f"   unavailable: {board.reason}")
    else:
        raw = run_sync(client.station_live("MAS", 4), 30).data  # served from the cache: no extra NTES call
        print(f"   NTES listed {len(raw.get('TrainsAtStation') or [])} trains; {len(board.departures)} departures in "
              f"the window {board.window_start:%H:%M}-{board.window_end:%H:%M}")
        if raw.get("TrainsAtStation"):
            print(f"   record keys: {sorted(raw['TrainsAtStation'][0])[:14]} ...")
        for d in board.departures[:6]:
            delay = "status unknown" if d.delay_minutes is None else f"{d.delay_minutes} min late"
            towards = ", ".join(t.code for t in d.towards)
            print(f"   {d.scheduled_departure:%d %b %H:%M}  {d.train_no} {d.train_name} -> {towards} "
                  f"({'CANCELLED' if d.cancelled else delay})")

    print("2. Train 12658 schedule")
    sched = live.schedule("12658")
    print(f"   provenance: {sched.provenance.mode.value} | {sched.provenance.source}")
    if sched.provenance.mode is DataMode.UNAVAILABLE:
        ok = False
        print(f"   unavailable: {sched.reason}")
    else:
        first, last = sched.stops[0], sched.stops[-1]
        print(f"   {sched.train_name}: {len(sched.stops)} stops, {first.station_code} dep {first.departure} -> "
              f"{last.station_code} arr {last.arrival} (day +{last.day_offset})")

    print("3. Trains between MAS and SBC (tomorrow)")
    tomorrow = (datetime.now(IST) + timedelta(days=1)).date()
    try:
        options = provider.search(["MAS"], ["SBC"], [tomorrow])
    except Exception as exc:  # noqa: BLE001 - a smoke test reports, it does not crash
        ok = False
        print(f"   failed: {type(exc).__name__} {getattr(exc, 'kind', '')}")
    else:
        raw = run_sync(client.trains_between("MAS", "SBC"), 30).data  # cached
        print(f"   NTES listed {len(raw)} trains for the station groups; {len(options)} run MAS->SBC on "
              f"{tomorrow:%a %d %b}")
        if raw:
            print(f"   record keys: {sorted(raw[0])}")
        for o in options[:6]:
            leg = o.legs[0]
            classes = ",".join(str(c) for c in o.classes) or "-"
            print(f"   {leg.departure:%H:%M}->{leg.arrival:%H:%M} {leg.train_no} {leg.train_name} "
                  f"({o.duration_minutes} min, classes {classes}, fares {o.fares or 'none'})")
        if options:
            print(f"   provenance: {options[0].provenance.mode.value} | {options[0].provenance.source}")
    print("RESULT:", "all three NTES calls answered" if ok else "some NTES calls failed (see above)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
