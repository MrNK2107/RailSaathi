# Live train data with RailRadar

The planner can use live train data from [RailRadar](https://railradar.in/docs),
a **third-party** service. It is not an official Indian Railways or IRCTC
source, and RailSaathi has no NTES integration. Every result carries its
provenance (`live`, `cached`, `stale` or `unavailable`, source RailRadar), and
the passenger is told to verify on official Indian Railways channels before
travelling.

`RAILWAY_DATA_MODE=demo` (the application default) uses the clearly labelled
demo data, and only outside production: with `APP_ENV=production`, demo data is
refused and the deploy workflow defaults to `railradar`.
`RAILWAY_DATA_MODE=railradar` uses RailRadar only. If the key is missing or
RailRadar fails, the planner reports that live data is unavailable. It **never**
falls back to demo or fictional journeys in live mode.

## Enable it

1. Get an API key from railradar.in.
2. In `backend/.env` (git-ignored):
   ```ini
   RAILWAY_DATA_MODE=railradar      # DATA_PROVIDER is accepted as an alias
   RAILRADAR_API_KEY=<your key>
   ```
3. Check the connection. The script prints the observed field names and types of the first record, maps the trains, saves the first 5 raw records to `scripts/railradar_sample.json` (git-ignored) and checks live status. It never prints the key:
   ```bash
   cd backend
   uv run python scripts/check_railradar.py            # Coimbatore → Chennai Central, tomorrow
   uv run python scripts/check_railradar.py SBC MAS 2026-10-20
   ```
4. Restart the backend. `GET /api/health` should show
   `"data_mode": "live"` and `"data_provider": {"active": "railradar", ...}`.
   Journey options and boards in the app then carry a live (or cached or stale) RailRadar provenance badge.

## What is used

| RailRadar endpoint | Used for |
|---|---|
| `GET /v1/trains/between/{from}/{to}?date=YYYY-MM-DD` | Journey search (one call per station pair and date, cached `RAILRADAR_CACHE_SECONDS`) |
| `GET /v1/trains/{number}/live?date=YYYY-MM-DD` | "Check live status of my trains" in the disruption panel: real delays and cancellations |

The key is sent as `Authorization: Bearer <key>` from the **backend only**. It
never reaches the browser and is never logged (it is a `SecretStr` in config).

## How live data differs from demo

| Topic | Demo | Live (RailRadar) |
|---|---|---|
| Trains and timings | Fictional `D###` trains | Real trains from RailRadar |
| Fares | Illustrative | Used **only if** RailRadar returns them. Otherwise the card says "Fare not available", no "Lowest cost" label is given, and a strict budget becomes *unverified* (not passed, not excluded) |
| Classes | Listed | Used if returned; otherwise a strict class requirement is *unverified* |
| Assistance / wheelchair | Simulated verified, unknown or unsupported | Always **unknown**, because RailRadar has no facility data |
| Disruptions | Simulated events | Live delay or cancellation for the trains in your plan |
| Stations | 10 demo stations | About 36 major stations with real codes (`providers/data/station_catalogue.json`); extend the file to add more |
| Transfers | One demo transfer route | Direct trains only (no multi-leg search yet) |

## Verified against the live API (2026-10-10, without a valid key)

| Check | Observed |
|---|---|
| `GET /` | 200 `{"name": "RailRadar API", ...}` |
| `GET /v1/trains/between/CBE/MAS?date=…` | 401 `{"success": false, "error": {"code": "UNAUTHORIZED", "message": "API Key is required"}, "meta": {timestamp, traceId}}`, so the route exists |
| `GET /v1/trains/{number}/live?date=…` | 401 (route exists) |
| `GET /api/v1/trains/between/...` (the path on RailRadar's marketing page) | 404 `NOT_FOUND "Route not found"`, so that path is wrong |
| Fake key via `Authorization: Bearer`, `X-API-Key` or `?apiKey=` | All three give 401 "Invalid API Key", so all three headers are read; the planner uses Bearer |
| Planner with `RAILWAY_DATA_MODE=railradar` and a fake key | Chat shows "Live train data is unavailable (RailRadar returned HTTP 401: UNAUTHORIZED: Invalid API Key)"; no journeys shown |

### With a real key (2026-10-10)

| Check | Result |
|---|---|
| `trains/between` CBE→MAS, 11 Oct and 12 Oct | 200; 12 and 13 trains; **12/12 records mapped** |
| Observed item fields | `train.{number,name,type,runDays,runningDaysBitmap}`, `from.{code,name,city,departure "HH:MM",day,sequence}`, `to.{code,name,city,arrival "HH:MM",day,sequence}`, `duration` (min), `distance`, `totalHaltsBetween`. **No class or fare fields.** |
| Meaning of `date=` | The passenger's boarding date at the origin. Train 22208 (runs Wed/Sun, reaches CBE on run day 2) is listed for **Monday**, not Sunday |
| `trains/{number}/live` | 200; fields `trainNumber, trainName, train, startDate, status, delayMinutes, isLive, trackingMode, lastUpdatedAt, currentLocation, nextHalt, route` |
| Rate limit | **10 requests/minute**: `429 TOO_MANY_REQUESTS "Rate limit exceeded. Maximum 10 requests per minute."` Enforced locally by `RAILRADAR_REQUESTS_PER_MINUTE` |
| `byCity=true` | Covers more stations per city (e.g. MDU,TMQ → MS,MBM,PER) but **omitted the MAS train the plain call returned**, so it is not used |
| Planner end to end (live) | Scenarios A–E and G ran through the API and UI with real trains; correction, confirmation (handoff `mode: live`, `fare_available: false`) and live reassessment ("no delays currently reported") all worked |

## Failure handling

| Problem | What the passenger sees |
|---|---|
| Key missing in live mode | No journeys are shown. Chat says "Live train data is unavailable (RailRadar API key is not configured)"; `/api/health` shows `configured: false, reason: railradar_api_key_missing` |
| 401/403 (bad or expired key), 429 (rate limit), timeout, 5xx | Chat says "Live train data is unavailable right now (…). Your details are saved — say 'show options' to try again." Status becomes `error`. It never shows "no trains found" and never substitutes demo trains. |
| Response format not understood (no `data.trains`, or no record can be mapped) | Same message, with kind `bad_response`; never an empty "no trains" result. Run the check script |
| 404 | Reported as an error. RailRadar uses 404 for unknown routes, so it is never read as "no trains" |
| `data.count == 0` / empty `trains` | "No train in the live RailRadar results meets…" |

Network and 5xx errors are retried once. Search responses are cached for 5
minutes by default (`RAILRADAR_CACHE_SECONDS`), in Redis when `REDIS_URL` is set,
so every replica shares the cache. The planner's live-status check is never
cached, but departure boards opt in to the cache.

The quota (`RAILRADAR_REQUESTS_PER_MINUTE`, 10) is enforced before a request is
sent, by one Redis sliding window shared across replicas. When it is spent:

- a cached answer up to `RAILRADAR_STALE_SECONDS` (6 h) old is served and
  labelled `stale`;
- otherwise the answer is `unavailable`.

Each refusal logs one `railradar_quota_exhausted` event, which the Cloud
Monitoring alert counts (`infra/monitoring/`, [RUNBOOK.md](RUNBOOK.md)). Each result shows its real
retrieval time ("retrieved 10:00 IST"), including when it came from the cache.

## Field mapping (verify with a real key)

RailRadar's public docs describe the endpoints and the `{success, data, meta}`
envelope, but not every field name. `app/providers/railradar_mapper.py`
therefore accepts several spellings, for example `trainNumber`, `train_number`
or `train.number`. Departure and arrival can be `HH:MM`, ISO timestamps or
minutes; duration can be minutes, `HH:MM` or `7h 45m`.

If the check script reports `0/N mapped`, open `scripts/railradar_sample.json`
and add the real field names to the `*_KEYS` tuples in the mapper. Records the
mapper can't read are skipped; if none can be read, the planner reports an
error instead of an empty result.
