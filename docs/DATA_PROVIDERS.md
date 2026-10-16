# Data sources and how to replace them

Every piece of railway, station, model or AI data enters RailSaathi through one interface. That interface is
built in `backend/app/container.py`, the composition root. This page lists each source as it is wired today,
what its provenance says, and what to implement to replace it.

Use only **authorised** sources. Do not scrape restricted services or call unofficial endpoints. RailSaathi has no
NTES integration and no IRCTC data feed.

## Overview

| Data | Interface | Implementations today | Provenance |
|---|---|---|---|
| Journeys (both planners) | `JourneyProvider` (`providers/base.py`) | `RailRadarJourneyProvider`, `DemoJourneyProvider` (refused in production), `UnconfiguredLiveProvider` | `live` / `cached` / `stale` (RailRadar), `demo`, `unavailable` |
| Planner disruptions | `DisruptionSource` (`providers/base.py`) | `RailRadarDisruptionSource` (live delays and cancellations of planned trains), `DemoDisruptionSource` (six simulated events) | events carry `simulated: true` unless they come from live status |
| Boards, schedules, running status | `LiveSource` (`providers/live_source.py`) | `RailRadarLiveSource`, `DemoLiveSource` (outside production), `UnavailableLiveSource` | per response; `unavailable` with a `reason` |
| RailRadar quota and cache | `QuotaGate`, `ResponseCache` (`providers/railradar_shared.py`) | Redis (shared by every replica), in-memory (one process) | `stale` when a cached answer is served because the quota is spent |
| Station catalogue for search | `providers/data/station_catalogue.json` | about 36 major stations and 32 cities with real codes | `catalogue_provenance()` |
| Station layouts (navigation) | `StationCatalogue` (`navigation/services/station_store.py`) | `STATIONS_URI`: a local directory or `gs://bucket/prefix`, published by `scripts/stations.py` | `cached`, "RailSaathi station catalogue (schematic)", dated by `checked_on` |
| Station closures | `DisruptionStore` (`navigation/services/disruption_store.py`) | `RedisDisruptionStore` with a TTL, written only by the internal OIDC endpoints; in-memory for tests | the `simulated` flag per closure |
| Ticketing knowledge | read-only SQLite (`knowledge/database.py`) | built from `knowledge/seed_data.py` at image build | each record cites `source_url` and `as_of` |
| Chat LLM | `ChatLLM` (`llm/base.py`) | `GeminiChatLLM` (Vertex AI), `KeywordChatLLM` (the rule-based agent), `MockChatLLM` (tests only) | `live` (Gemini), `fallback` (rules), `unavailable` |
| Planner intent extraction | `IntentLLM` (`intent/`) | Gemini, Bedrock (optional), always backed by the rule-based extractor | `extraction.source` on each message response |
| AR localisation | `VisionLocalizer` (`llm/vision.py`) | `GeminiVisionLocalizer` (Vertex AI) | `live`, with the note "Approximate…" |
| Delay estimate | `DelayModel` (`delay/model.py`) | `model.joblib` + `metrics.json` (`DELAY_MODEL_URI`, local or `gs://`), `history_only` fallback | `fallback` (a modelled estimate), `unavailable` |
| Delay observations | `ObservationSink` (`delay/observations.py`) | `LocalObservationSink`, `GcsObservationSink`: JSONL to `OBSERVATIONS_URI` | not used for training yet |
| Venues for the goal planner | `data/common/venues.json` (Pydantic-validated) | a small list; an unknown venue makes the planner ask for the station | — |
| Helplines | `data/common/helplines_india.json` and per-station `info.json` | national numbers only, each with sources and `checked_on` | shown with their sources |

## Rules every source follows

- **Provenance** comes from one model, `DataProvenance` (`domain/options.py`), with the modes in `DataMode`
  (`domain/enums.py`): `live`, `cached`, `stale`, `unavailable`, `demo` and `fallback`. Use `live` only for data
  fetched now from an authorised source.
- **Missing data is never proof of absence.** A facility the source does not mention is `unknown`. An empty
  answer caused by an error is `unavailable` with a reason, never "no trains".
- **Demo and simulated data are refused when `APP_ENV=production`.** The container builds the unavailable
  implementations instead (`data_provider.active` is `none`), and `/readyz` reports not ready through its
  `data_provider` check, whatever `RAILRADAR_API_KEY` holds.
- **A fresh cache hit is `cached`, not `live`.** RailRadar responses reused from the response cache keep their
  original fetch time as `as_of` and carry a CACHED note; an expired copy served because the quota is used up is
  `stale`.
- **A search the quota did not allow is named.** The journey search runs no more uncached RailRadar calls than the
  shared quota has free (primary stations first). Options from a partial search carry a `PARTIAL:` note listing
  the searches that did not run; if nothing usable came back, the search is `unavailable`, never "no trains".
- **Failures never become 500s.** Map upstream errors to `ProviderError` kinds (`providers/errors.py`) or to an
  `unavailable` answer.

## `JourneyProvider`

```python
class JourneyProvider(Protocol):
    data_mode: DataMode
    def cities(self) -> list[CityRecord]: ...
    def stations(self) -> list[StationRecord]: ...
    def station(self, code: str) -> StationRecord | None: ...
    def search(self, origin_codes, destination_codes, departure_dates) -> list[JourneyOption]: ...
    def provenance(self) -> DataProvenance: ...
```

- `search` returns every option departing on the given dates between any origin and any destination. **Do not
  filter by passenger constraints.** The ranking layer does that, so that it can explain exclusions.
- `JourneyOption.option_id` must be stable for the same service and date. `fares` is the listed fare **per
  passenger** per class. Leave it empty when the source has no fares; the ranking then reports budgets as
  unverified. Timestamps must be timezone-aware. Each option carries its own `provenance`.
- `StationRecord.facilities` maps needs to `verified_supported`, `not_supported` or `unknown`.
- The goal planner (`journey/provider_adapter.py`) reads the same provider, so one change covers both planners.

## `LiveSource`

```python
class LiveSource(Protocol):
    directory: StationDirectory
    def catalogue_provenance(self) -> DataProvenance: ...
    def departures(self, station_code: str, hours: int) -> DepartureBoard: ...
    def schedule(self, train_no: str) -> TrainSchedule: ...
    def live_status(self, train_no: str, run_date: date) -> TrainLiveStatus: ...
```

Set `complete: false` on a board when some upstream queries failed. Set `delay_minutes` and `cancelled` to `None`
when the running status is unknown, never to 0 or false.

## Wiring a new source

```python
# app/container.py: build_providers() / build_live_source()
provider = MyAuthorisedProvider(settings)        # instead of RailRadarJourneyProvider
disruptions = MyTrustedDisruptionFeed(settings)  # simulated=False only for a trusted feed
```

- Keep credentials in backend environment variables (Secret Manager on Cloud Run). They never go into the
  frontend bundle and never into logs.
- Add timeouts and caching in the provider. Share any per-key quota across replicas with a Redis `QuotaGate`, as
  `RailRadarClient` does.
- Report `stale` when you serve data older than your freshness policy.

## RailRadar specifics

These are covered in [RAILRADAR_SETUP.md](RAILRADAR_SETUP.md): the endpoints, field mapping, the 10
requests/minute limit, the cache (`RAILRADAR_CACHE_SECONDS`, 300 s fresh; `RAILRADAR_STALE_SECONDS`, 6 h stale
window) and failure handling. Every refused call logs one `railradar_quota_exhausted` event, which the
monitoring metric counts.

## Demo dataset (development and tests only)

`providers/data/*.json` holds fictional daily services (`D101` and so on) between Chennai, Coimbatore, Bengaluru,
Madurai, Trichy, Salem, Erode and Katpadi, each labelled demo. It is varied on purpose:

- a cheap but late train (D105);
- a fast but expensive train (D107);
- a transfer via Erode (D121 → D123);
- verified, unknown and not-supported assistance;
- six simulated disruptions.

[DEMO_SCENARIOS.md](DEMO_SCENARIOS.md) uses it.
