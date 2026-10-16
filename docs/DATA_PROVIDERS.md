# Data sources and how to replace them

Every piece of railway, station, model or AI data enters RailSaathi through one interface. That interface is
built in `backend/app/container.py`, the composition root. This page lists each source as it is wired today,
what its provenance says, and what to implement to replace it.

Prefer **authorised** sources. The one exception is a decision by the project owner: live train data comes from
NTES through `ntes-client`, an **unofficial** client of the NTES app backend, labelled "NTES (unofficial client)"
everywhere (see [NTES specifics](#ntes-specifics-the-unofficial-client)). RailSaathi has no IRCTC data feed and no
PNR lookup.

## Overview

| Data | Interface | Implementations today | Provenance |
|---|---|---|---|
| Journeys (both planners) | `JourneyProvider` (`providers/base.py`) | `NtesJourneyProvider` (`RAILWAY_DATA_MODE=ntes`), `RailRadarJourneyProvider`, `DemoJourneyProvider` (refused in production), `UnconfiguredLiveProvider` | `live` / `cached` / `stale` (NTES, RailRadar), `demo`, `unavailable` |
| Planner disruptions | `DisruptionSource` (`providers/base.py`) | `NtesDisruptionSource`, `RailRadarDisruptionSource` (live delays and cancellations of planned trains), `DemoDisruptionSource` (six simulated events) | events carry `simulated: true` unless they come from live status |
| Boards, schedules, running status | `LiveSource` (`providers/live_source.py`) | `NtesLiveSource`, `RailRadarLiveSource`, `DemoLiveSource` (outside production), `UnavailableLiveSource` | per response; `unavailable` with a `reason` |
| NTES and RailRadar request budgets and caches | `QuotaGate`, `ResponseCache` (`providers/railradar_shared.py`) | Redis (shared by every replica; namespaces `ntes` and `rr`), in-memory (one process) | `stale` when a cached answer is served because the budget is spent (or NTES failed) |
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
- **A fresh cache hit is `cached`, not `live`.** NTES and RailRadar responses reused from the response cache keep their
  original fetch time as `as_of` and carry a CACHED note; an expired copy served because the quota is used up is
  `stale`.
- **A search the quota did not allow is named.** The journey search runs no more uncached NTES or RailRadar calls
  than the shared budget has free (primary stations first). Options from a partial search carry a `PARTIAL:` note listing
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

## NTES specifics (the unofficial client)

**Owner decision, 2026-10-17.** Live train data comes from NTES (the National Train Enquiry System) through
[`ntes-client`](https://pypi.org/project/ntes-client/) 0.1.4, "an unofficial Python client for NTES (Indian
Railways)". It talks to the backend of the NTES mobile app. It is **not** an official or authorised Indian
Railways integration: it can break when NTES changes, it can be blocked, and NTES's terms of use apply. The owner
was told this and chose it, with no RailRadar key. RailRadar stays available as an alternative
(`RAILWAY_DATA_MODE=railradar`, [RAILRADAR_SETUP.md](RAILRADAR_SETUP.md)).

- **Mode:** `RAILWAY_DATA_MODE=ntes`. `python run.py` uses it unless you set the variable yourself; the backend's
  own default stays `demo`, so tests and the Playwright suite stay deterministic. The deploy workflow defaults to
  `ntes` too and mounts the RailRadar key only in RailRadar mode.
- **Label:** every answer says `source: "NTES (unofficial client)"`, with `mode` `live`, `cached` or `stale` and the
  real fetch time as `as_of`. The UI shows the source next to the LIVE chip on every option.
- **Calls used:** only the train-enquiry calls `trains_between`, `schedule`, `station_live` and `live_status` (the
  package also offers `search`, `train_info` and `exceptions`, which are allowed but not needed). **Never**
  `pnr_status` (it solves a captcha) or the IRCTC chart helpers; a test fails if the app's code mentions them.
- **Code:** `providers/ntes_client.py` (lazy import, quota, cache, error mapping), `providers/ntes_mapper.py`
  (response shapes to models), `providers/ntes.py` (`NtesJourneyProvider`, `NtesDisruptionSource`) and
  `NtesLiveSource` in `providers/live_source.py`. The package is imported on the first call, never when the app is
  imported. If it is missing, `/api/health` reports `configured: false, reason: ntes_client_not_installed`, every
  answer is `unavailable` and `/readyz` fails its `data_provider` check.
- **Budget and cache:** the client is synchronous (`requests`), so each call runs in a worker thread from the shared
  async bridge, under `NTES_CALL_BUDGET_SECONDS` (15 s) per batch, which is part of the startup lock-TTL check.
  Every call passes a quota gate first: `NTES_REQUESTS_PER_MINUTE` (20), RailSaathi's own politeness limit, shared
  by all replicas through Redis (namespace `ntes`, separate from RailRadar's). Timetable answers are cached
  `NTES_CACHE_SECONDS` (300 s); live answers (boards, running status) at most 60 s; an older copy is served
  `stale` for `NTES_STALE_SECONDS` (6 h) when the budget is used up or NTES fails. Refused calls log
  `ntes_quota_exhausted`.
- **Fan-out:** a journey search asks one `trains_between` per station pair (NTES answers are not date specific, so
  one call covers every searched date), primary stations first, and never more uncached calls than the budget has
  free. Options from a partial search carry a `PARTIAL:` note.
- **Errors:** the client raises `NTESError` with upstream text for both transport failures and server alerts. The
  adapter maps it to `ProviderError` kinds (timeout, unavailable, bad response, or an alert that becomes "no
  data") with fixed messages. Upstream text never reaches passengers or the API.
- **Smoke test:** `cd backend && uv run python scripts/ntes_smoke.py` asks NTES three times (MAS board, 12658
  schedule, MAS to SBC) and prints the mapped answers and the raw record keys. It is not run in CI.

### How NTES answers map to RailSaathi models

| NTES call and field (observed 2026-10-17) | RailSaathi model | Notes |
|---|---|---|
| `trains_between`: `Trains[]` | `JourneyOption` (one leg) | NTES answers for station *groups* (a MAS to SBC query lists trains from PER or to SMVB). Only trains between stations the passenger's places resolve to are kept |
| `TrainNumber`, `TrainName` | `Leg.train_no`, `train_name` | |
| `FromStation`, `toStation` (+ names) | `Leg.from_code`, `to_code` | Catalogue names are preferred; otherwise NTES's name in title case |
| `DepTimeFrom` + the search date | `Leg.departure` | Asia/Kolkata |
| `TravelTime` ("05:45") | `duration_minutes`; `arrival = departure + travel time` | handles overnight arrivals |
| `DayOfRun` ("Daily", "Mon,tue,thu") | which searched dates get an option | read as the days the train leaves the boarding station; an unreadable value skips the record |
| `ClassOfTravel` ("1A,2A,3A,SL,GEN") | `classes` | only the classes the planner supports (SL, 3A, 2A, CC, EC, 2S) |
| (none) | `fares = {}` | NTES gives no fares. None are invented; the UI says "Fare: check on IRCTC" |
| `schedule`: `stations[]` `StationCode`, `STA`, `STD`, `Day` | `TrainSchedule.stops`: `arrival`, `departure`, `day_offset = Day - 1` | empty STA/STD becomes `None` (origin, terminus) |
| `station_live`: `TrainsAtStation[]` `STD` ("23:10 16-Oct") | `Departure.scheduled_departure` | "DSTN" (ends here) is not a departure; the year is the one nearest to now |
| `DelayDep` ("RT", "03:47") | `Departure.delay_minutes` | RT = 0 |
| `Cancel`, `DepCancelFlag` | `Departure.cancelled` | |
| `Destination`, `DestinationName` | `Departure.towards` | the train's terminus |
| `live_status`: `LDEL` | `TrainLiveStatus.delay_minutes` | minutes late at the last reported station |
| `CPOS` / `LUPDFULL` mentioning a cancellation, or a cancellation alert | `cancelled = true` | |

## RailRadar specifics (alternative mode)

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
