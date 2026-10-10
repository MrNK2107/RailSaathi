# Connecting an authorised railway data source

The planner reads railway data only through two protocols in
`backend/app/providers/base.py`. Implement them for an **authorised** source,
change one line in `app/container.py`, and the ranking, validation, disruption
and API layers keep working unchanged.

Do not scrape restricted services or call unofficial endpoints.

> A live implementation already exists: `providers/railradar.py` (RailRadar). Setup: [RAILRADAR_SETUP.md](RAILRADAR_SETUP.md). Select it with `RAILWAY_DATA_MODE=railradar`.

## `JourneyProvider`

```python
class JourneyProvider(Protocol):
    data_mode: DataMode                      # DataMode.LIVE for verified data
    def cities(self) -> list[CityRecord]: ...
    def stations(self) -> list[StationRecord]: ...
    def station(self, code: str) -> StationRecord | None: ...
    def search(self, origin_codes, destination_codes, departure_dates) -> list[JourneyOption]: ...
    def provenance(self) -> DataProvenance: ...
```

Contract notes:

- `search` returns every option departing on the given dates between any origin and any destination station. Do **not** filter by passenger constraints; the ranking layer does that so it can explain exclusions.
- `JourneyOption.option_id` must be stable for the same service and date. `fares` is the listed fare **per passenger** per class. `station_codes` lists every boarding and alighting station (used for facility checks). Timestamps must be timezone-aware.
- `StationRecord.facilities` maps needs to `verified_supported`, `not_supported` or `unknown`. If the source says nothing, return `unknown`. **Missing data is never proof of unavailability.**
- `provenance()` must say where the data came from and when. Use `DataMode.STALE` if the data is older than your freshness policy, and `DataMode.LIVE` only for verified, authorised data. The UI and handoff payload display this value.

## `DisruptionSource`

```python
class DisruptionSource(Protocol):
    def list_events(self) -> list[DisruptionEvent]: ...
    def get_event(self, event_id: str) -> DisruptionEvent | None: ...
```

Set `simulated=False` only for events from a trusted feed. `type` is `delay`
(with `delay_minutes`) or `cancellation`. Other event types need a small
extension to `disruption/service.apply_event`.

## Wiring

```python
# app/container.py
provider = MyAuthorisedProvider(settings)       # instead of DemoJourneyProvider
disruptions = MyTrustedDisruptionFeed(settings) # instead of DemoDisruptionSource
```

Keep credentials in backend environment variables. Add caching and timeouts in
the provider, and map upstream failures to clear errors (or return
`DataMode.STALE` results with a note).

## Demo dataset

`providers/data/*.json` contains fictional daily services (`D101` and so on)
between Chennai, Coimbatore, Bengaluru, Madurai, Trichy, Salem, Erode and
Katpadi. Each is labelled as demo data. Its variety is deliberate:

- cheap but late (D105)
- fast but expensive (D107)
- a transfer route via Erode (D121 → D123)
- stations with verified, unknown and not-supported assistance
- six simulated disruptions
