# RailSaathi AI API (v2.0.0)

One FastAPI service (`backend/app/main.py`) serves every capability. Interactive docs are at `/docs` and the
schema at `/openapi.json`. Example requests are in [requests.http](requests.http).

- **Local development:** the backend runs at `http://localhost:8000` (or whatever port you pass to uvicorn), and
  the Vite dev server proxies `/api` to it.
- **Production:** the browser talks only to the frontend's HTTPS origin on Cloud Run. nginx there reverse-proxies
  `/api/*` to the backend service, so the browser never calls the backend's own URL and there is no CORS. Plain
  HTTP is never served in production. Camera, microphone and motion sensors need a secure context: HTTPS, or
  `localhost` in development.

`backend/tests/test_api_docs.py` compares the endpoint tables below with the routes the app actually serves, in
both directions. An undocumented route, or a documented route that does not exist, fails CI.

## Conventions

**Provenance.** Every response that carries railway, station, model or AI data includes
`provenance: {mode, source, as_of, note}`. The modes are:

| Mode | Meaning |
|---|---|
| `live` | Fetched now from the named source (RailRadar or Gemini). |
| `cached` | Served from a cache, or authored static data such as the station layouts. |
| `stale` | An old cached copy, served because the RailRadar quota was spent. |
| `unavailable` | Could not be served. The response carries a `reason` and **no placeholder data**. |
| `demo` | Bundled simulated data. Never served when `APP_ENV=production`. |
| `fallback` | A statistical estimate or rule-based answer rather than live data: the delay model, or the rule-based ticketing agent. |

**Session tokens.** `POST /api/planner/sessions` returns `session_id` and a signed `session_token`. Send the token
as the `X-Session-Token` header:

- Planner session routes reject a missing token, a forged token, or a token issued for another session with 401
  `invalid_session_token`.
- Goal plans are bound to the token that created them. Another token's `plan_id` behaves like an unknown one.
- `/api/chat` and `/api/navigation/localize` issue a token when none is sent and return it as `session_token`.
  A caller that omits the token therefore starts a new session (and a fresh per-session `/localize` budget) on every
  call; only the per-IP tier bounds such a caller.

Tokens are HMAC-signed with `SESSION_SIGNING_KEY`. Sessions, plans and conversations expire after
`SESSION_TTL_MINUTES` (120) without activity.

**Errors.** Every error, from every router, has one shape. Exception text never reaches a response.

```json
{"error": {"code": "not_ready", "message": "Required journey details are missing or invalid.", "details": {}}, "request_id": "4f2c..."}
```

**Request ids.** The `X-Request-Id` header is echoed back, or generated when absent. It appears in every log line
for that request.

**Limits.**

| Limit | Value |
|---|---|
| Body size | `MAX_BODY_BYTES` (16 KiB) for every body except the AR frame upload (1.5 MB frame). |
| Chat-like text | `MAX_MESSAGE_CHARS` (1,000). Longer text gets 422 `message_too_long`. |
| Rate limits | Sliding windows per client IP and per session token. 429 `rate_limited`, with `Retry-After`. |

The rate-limit tiers are:

- **Standard:** `RATE_LIMIT_PER_MINUTE` (60/min).
- **LLM:** `RATE_LIMIT_LLM_PER_MINUTE` (20/min). It covers `/api/chat`, `/api/journey/plan`, `/api/journey/refine`,
  `/api/navigation/localize` and planner `/messages`.
- **Health:** the health routes are exempt.

## 1. Conversational journey planner

Natural-language planning in English, Tamil and common Tanglish. It works like this:

1. The rule-based extractor, or Gemini when configured, proposes raw values. Deterministic code validates them.
2. The planner asks one question at a time until the details are complete.
3. It ranks options against hard and soft constraints and explains each recommendation from computed values.
4. Re-planning on disruptions needs the passenger to confirm again.

**No ticket is ever booked.** Every `/api/planner/sessions/{session_id}/...` route needs the `X-Session-Token`
issued by `POST /api/planner/sessions`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/planner/reference` | Places, classes, needs, budget priorities and disruption events for the edit forms |
| GET | `/api/planner/disruption-events` | Disruption events from the active source: labelled simulated events in demo mode, or live delays and cancellations seen for planned trains in RailRadar mode |
| POST | `/api/planner/sessions` | Start a session `{"language": "en" \| "ta"}`. Returns 201 with `session_id` and `session_token` |
| GET | `/api/planner/sessions/{session_id}` | Current state |
| POST | `/api/planner/sessions/{session_id}/messages` | Process a passenger message `{"message", "language"?}` |
| PATCH | `/api/planner/sessions/{session_id}/journey` | Manual field corrections. Only the fields sent change; `null` clears a field |
| POST | `/api/planner/sessions/{session_id}/recommendations` | (Re)compute recommendations. Needs valid details |
| POST | `/api/planner/sessions/{session_id}/select` | Select an option `{"option_id"}`. Status becomes `awaiting_confirmation` |
| POST | `/api/planner/sessions/{session_id}/confirm` | Confirm for handoff `{"option_id"?}`. **Does not book** |
| POST | `/api/planner/sessions/{session_id}/reassess` | Apply a disruption `{"event_id"?}`. Picks a relevant event if omitted |
| POST | `/api/planner/sessions/{session_id}/cancel` | Cancel the workflow |
| GET | `/api/planner/sessions/{session_id}/handoff` | Confirmed handoff payload. 409 `not_ready` before confirmation. See [INTEGRATION.md](INTEGRATION.md) |
| GET | `/api/planner/sessions/{session_id}/audit` | Audit events: statuses and field names only, never message text. Best effort and per instance: each replica keeps only the sessions it served (a bounded LRU that expires with the session TTL), so a request served by another replica can return fewer events. The durable record is the structured `audit` log line |

Every planner response has the same envelope:

```jsonc
{
  "session_id": "uuid",
  "session_token": "uuid.signature",          // only on POST /sessions
  "assistant_message": "Where will you be travelling from?",
  "status": "collecting_details",              // workflow status (docs/ARCHITECTURE.md)
  "state": { /* full SessionState, authoritative */ },
  "missing_fields": ["origin", "passenger_count"],
  "validation_errors": [{"field": "destination", "code": "ambiguous_station", "message": "...", "candidates": ["..."]}],
  "recommendations_ready": false,
  "confirmation_required": false,
  "data_mode": "demo",                         // demo | live | stale | unavailable ...
  "data_notice": "DEMO DATA: ...",
  "extraction": {"source": "rules", "fallback_reason": "llm_disabled"},   // message endpoint only
  "handoff": null                              // set once confirmed
}
```

Every option in `state.recommendations` carries its own `provenance`.

- **Demo mode:** options are fictional `D###` trains labelled `demo`.
- **RailRadar mode:** options are real trains labelled `live`, `cached` or `stale`.
  - RailRadar supplies no fares or classes, so a strict budget or class is reported as *unverified*.
  - It has no facility data, so passenger-need statuses are `unknown`.

In the message endpoint, user-level problems come back as a normal 200 with an explanatory `assistant_message`,
not an HTTP error. Examples are "confirm" with nothing selected, or a place that is not in the catalogue.

## 2. Goal-based journey planner ("reach my meeting on time")

Plans trains that arrive before a meeting time with an arrival buffer (default 45 min). It uses the same
`JourneyProvider` as the conversational planner. Missing details are asked for (`clarification_required`) and
never defaulted. Every route needs `X-Session-Token`. Plan ids are server-issued and bound to that session.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/journey/plan` | Plan from a `prompt` and/or the structured fields `origin`, `destination_venue` or `destination_station`, `meeting_date`, `meeting_time`, `required_arrival_buffer_minutes`, `preferred_class`, `preferred_train_name_or_number` and `budget_max` |
| POST | `/api/journey/refine` | Change the date, time, buffer, class, preferred train or budget of a plan you own `{"plan_id", ...}` |
| GET | `/api/journey/options/{plan_id}` | The stored plan |

The response is a `JourneyPlanResponse`:

- `status`: `answered`, `clarification_required`, `no_feasible_journey` or `provider_unavailable`.
- `summary`, `plan_id` and `provenance`.
- `best_match`, `feasible_alternatives` and `infeasible_options`, each with its arrival buffer.
- `clarification_question`.

The errors are:

| HTTP | Code | When |
|---|---|---|
| 422 | `meeting_in_past` | The meeting time has already passed |
| 422 | `validation_failed` | A parsed value fails validation |
| 404 | `plan_not_found` | The plan id is unknown, expired or belongs to another session |

## 3. Ticketing guidance agent

Answers questions about classes, quotas, RAC and waiting lists, Tatkal and refunds. It is grounded in a read-only
SQLite knowledge base built at image-build time from `app/knowledge/seed_data.py`. Each record cites an official
irctc.co.in or indianrail.gov.in page with an `as_of` date.

The agent runs on Gemini (Vertex AI) when it is configured, and on a rule-based agent otherwise. It is AI guidance,
not an official answer.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/chat` | `{"message", "conversation_id"?}`. Optional `X-Session-Token`; one is issued when absent |
| GET | `/api/sources` | The knowledge sources the answers cite: title, publisher, `source_url`, retrieval and verification dates |

The response contains `conversation_id`, `session_token`, `status`, `answer`, `sources[]`, `provenance`,
`evidence_sufficient` and `trace_id`. `status` is one of:

- `answered`;
- `execution_limit_reached`;
- `unavailable`;
- `error`.

`provenance.mode` says who answered. Nothing here is live data: answers come from a curated snapshot of official
pages.

- `cached`: Gemini over the knowledge base. `as_of` is the oldest cited source's date (or the knowledge base's
  curation date) and `source` names the curation date.
- `fallback`: the rule-based agent.
- `unavailable`: Gemini is configured but failed or timed out. This is still a 200, with
  `message: "guidance unavailable"` and official `links`, never a 500.

Links in the answers are code-filtered. Only `https://` links on irctc.co.in, indianrail.gov.in and
indianrailways.gov.in survive.

## 4. Live station information

Station search, departure boards, schedules and running status come from RailRadar, a third-party service and
not an official Indian Railways feed. They share one per-minute quota across every replica, with a Redis cache
in front. Demo boards are served only outside production.

A board that cannot be served returns `provenance.mode: "unavailable"` with a `reason`. It never returns
placeholder trains. When the quota is spent, a cached board is returned as `stale`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/live/stations/search` | `?q=` name, city or code. Searches the bundled station catalogue |
| GET | `/api/live/stations/nearest` | `?lat=&lon=`. The nearest catalogue station |
| GET | `/api/live/stations/{station_code}/departures` | `?hours=1..4`. A board built from cached trains-between calls to nearby catalogue stations, plus running status for the first few trains. `complete: false` means some queries failed |
| GET | `/api/live/trains/{train_no}/schedule` | The train's stops |
| GET | `/api/live/trains/{train_no}/status` | `?date=YYYY-MM-DD`, from two days ago to tomorrow. Delay and cancellation; `null` when unknown |
| GET | `/api/trains/rake-position` | `?coach_composition=ENG-A1-B1-...&target_coach=B4`. Where a coach sits in a composition **you supply**. RailSaathi has no live rake data |

## 5. Delay estimate

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/predict/delay` | `?train_number=12623&destination=MAS` (plus optional `current_delay`, `hour` and `weekday`) |

The answer comes from a scikit-learn gradient-boosting model trained on historical averages. The model card,
with its measured error, is [DELAY_MODEL.md](DELAY_MODEL.md).

The response contains:

- `predicted_delay_minutes` and `on_time_probability` (P(delay ≤ 15 min));
- `risk_level`, `historical_mean_delay_minutes` and `historical_scope` (`pair`, `station` or `none`);
- `model_version`, `mae_minutes` and `baseline_mae_minutes`;
- `basis` (`trained_model`, `history_only` or `none`);
- `provenance`, with mode `fallback` and a note saying it is a modelled estimate and not live data;
- `insights`.

`current_delay` is echoed back as `live_input_delay_minutes`, but no mode uses it as an input. A missing artifact
degrades to `history_only`, which gives no probability and makes no accuracy claim.

## 6. Station navigation, AR guidance and the virtual tour

Indoor routing runs over station layouts authored with `scripts/stations.py`. The service only reads them. Four
stations are in the catalogue: Chennai Central, Chennai Egmore, KSR Bengaluru City and Hyderabad Deccan. Every
layout is **schematic**: not surveyed and not to scale.

- Only Chennai Central, traced from a plan image, has `routing_enabled: true`.
- Route requests for the other three stations get 503 `routing_unavailable`. Their map and information are still
  served.
- Step-free status is `unknown` on every pathway today.

Details are in [STATION_NAVIGATION.md](STATION_NAVIGATION.md) and [AR_GUIDANCE.md](AR_GUIDANCE.md).

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/stations` | The station list: `station_id`, `station_name`, `station_code` (e.g. `MAS`, so a journey leg can find its floor plan), `city`, `data_status`, `version`, `node_count`, `edge_count` |
| GET | `/api/stations/{station_id}` | The graph, metadata, `layout_basis`, `routing_enabled` and `provenance` (`cached`, source "RailSaathi station catalogue (schematic)") |
| GET | `/api/stations/{station_id}/map` | The plan image (PNG), served from the loaded catalogue. The data directory is never mounted |
| GET | `/api/stations/{station_id}/info` | Helplines (national numbers only, each with its source), station facts, amenities, `layout_note` and `provenance` |
| GET | `/api/stations/{station_id}/tour` | Everything the 3D tour draws: levels, areas, nodes and edges in metres, panoramas, and `ar_guidance_available` |
| POST | `/api/navigation/route` | A route between two nodes, or from a position: `{station_id, source \| source_position, destination, preferences: {avoid_stairs, wheelchair, require_verified_accessibility}, apply_disruptions, previous_edge_ids, simulate_closures}` |
| GET | `/api/disruptions/{station_id}` | Active closures at the station. 503 `disruptions_unavailable` when the store is down |
| POST | `/api/navigation/localize` | AR: a multipart JPEG or WebP camera frame (≤ 1.5 MB) plus `station_id` and optional `previous_node_id` and `route_node_ids`. Returns `status` (`fix`, `low_confidence` or `unavailable`) with `provenance` labelled approximate. Frames are never stored |

**Route responses** contain:

- `status` (`ok` or `no_route`), `node_ids`, `edge_ids`, `geometry`, `segments` and `instructions[]`;
- `distance_m` and `distance_basis` (`measured`, `estimated_from_map_scale` or `unavailable`);
- `estimated_duration_s` at `WALKING_SPEED_MPS`;
- `accessibility_confidence` (`verified`, `unverified` or `not_applicable`) and `warnings`;
- `along_the_way`, `disruptions_applied`, `simulated_closures_applied`, `previous_route_blocked` and `provenance`.

`no_route` explains itself in `reason`, `explanation` and `blocking_edge_ids`.

**`simulate_closures`** adds what-if closures (edge or node ids) to one request. Nothing is stored. It is refused
with 403 `simulation_disabled` unless `PUBLIC_DISRUPTION_SIMULATION` is on and `APP_ENV` is not `production`.
`GET /api/client-config` reports the same flag as `features.simulate_closures`, and the app offers the closure
simulator only when that flag is true.

**AR localisation:**

| Answer | When |
|---|---|
| 404 `ar_guidance_unavailable` | AR is not enabled for the station (`AR_GUIDANCE_ENABLED`, off in production until the gate in AR_GUIDANCE.md passes) |
| 429 `rate_limited` | Over `LOCALIZE_RATE_LIMIT` (20) per session or `LOCALIZE_IP_RATE_LIMIT` (120) per IP per 10 min |
| 415, 413, 411, 400 | Wrong type, too large, no length, or an unreadable upload |

## Configuration and health

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/client-config` | What the browser needs at start-up: `google_maps_browser_key` (the public, referrer-restricted key, or `null` so the tour links out to Google Maps), `features.ar_guidance_stations` (station ids) and `features.simulate_closures` (boolean) |
| GET | `/api/health` | Service status, version, `data_mode`, `data_provider` (requested, active, configured, reason), AI status and the Redis, model and LLM status. No secrets |
| GET | `/healthz` | Liveness. No I/O |
| GET | `/readyz` | Readiness. Returns 503 `not_ready` unless all of the following hold: Redis (reachable when configured; in production it must also be configured), an active railway data provider (`data_provider`: production refuses demo data, which leaves none), the station catalogue, the RailRadar key (in production), the delay model (or `DELAY_HISTORY_ONLY=true`) and at least one navigation station. LLM and knowledge-base problems are listed under `degraded` and never fail readiness |
| GET | `/` | Service name, version and a capability summary |

## Internal endpoints (not public)

These are not in the OpenAPI schema and are not proxied for browsers on purpose: nginx forwards only `/api/*`.

- They answer 404 unless `INTERNAL_OIDC_AUDIENCE` and `INTERNAL_OIDC_SERVICE_ACCOUNT` are set.
- Callers must present a Google ID token for that audience, from that service account. The service checks the
  issuer, audience, expiry, signature, verified email and account.
- Anything else gets 401 or 403. The error never says which check failed.

| Method | Path | Purpose |
|---|---|---|
| POST | `/internal/collect` | The Cloud Scheduler job (`infra/scheduler/collect-observations.yaml`). Samples the live running status of recently viewed trains and appends JSONL to `OBSERVATIONS_URI` |
| POST | `/internal/stations/{station_id}/disruptions` | Add a station closure with a TTL. `simulated: true` is refused in production |
| DELETE | `/internal/stations/{station_id}/disruptions/{disruption_id}` | Remove one closure |
| DELETE | `/internal/stations/{station_id}/disruptions` | Clear the station's closures |

## Error codes

| HTTP | Code | When |
|---|---|---|
| 401 | `invalid_session_token` | Missing, forged or foreign `X-Session-Token` |
| 404 | `session_not_found` | Unknown planner session |
| 410 | `session_expired` | The planner session was idle longer than `SESSION_TTL_MINUTES` |
| 409 | `not_ready` | Search, confirm or handoff before the required steps |
| 409 | `no_recommendations` | Select or reassess without current recommendations |
| 409 | `stale_recommendations` | Constraints changed, the TTL passed, the train departed or it is no longer compliant |
| 409 | `session_cancelled` | An action on a cancelled session (except restart) |
| 409 | `invalid_transition` | An illegal workflow transition |
| 409 | `no_relevant_event` | Reassess found no event affecting the plan |
| 404 | `unknown_event` | Unknown disruption event id |
| 422 | `invalid_option` | The option is not in the current recommendations |
| 422 | `invalid_request` | Schema or value errors (FastAPI validation, details in `details.errors`) |
| 422 | `validation_failed` / `message_too_long` / `meeting_in_past` / `date_out_of_range` | Value checks |
| 404 | `plan_not_found` | Goal plan unknown, expired or owned by another session |
| 404 | `station_not_found` / `unknown_station` / `unknown_node` / `unknown_closure_target` | Navigation and live lookups |
| 404 | `unknown_target` | Internal closure write whose `target_id` is not an edge or node of the station |
| 422 | `unknown_node` | `/api/navigation/localize`: `previous_node_id` or a `route_node_ids` entry is not a node of the station |
| 403 | `simulation_disabled` | `simulate_closures` or a simulated internal disruption where simulation is off |
| 413 | `payload_too_large` | Body over `MAX_BODY_BYTES` |
| 429 | `rate_limited` | Over a rate limit (`Retry-After` says when to retry) |
| 503 | `data_unavailable` | The live data provider failed during reassessment |
| 503 | `routing_unavailable` | Routing requested at an untraced station |
| 503 | `disruptions_unavailable` / `live_unavailable` / `delay_model_unavailable` | A dependency is not set up or not reachable |
| 503 | `session_busy` | Another request holds the session lock, or this turn outlived its lock and a newer request now owns the session; nothing was saved (`Retry-After: 2`) |
| 503 | `storage_unavailable` | Redis (sessions, goal plans, conversations, closures) is unreachable (`Retry-After: 5`). Never a 500 |
| 500 | `internal_error` / `route_integrity_failed` | An unexpected error, or a computed route failed its integrity check (the ids go to the server log only). No stack trace is exposed |

## Planner session lifecycle

```
POST /sessions ─► collecting_details ⇄ needs_clarification
                        │ (all required fields valid)
                        ▼
          presenting_recommendations ⇄ no_feasible_options
                        │ select
                        ▼
              awaiting_confirmation ── confirm ──► confirmed
                        ▲                              │ reassess
                        └───── presenting_recommendations ◄┘
any state ── cancel ──► cancelled ── "start over" ──► collecting_details
```

Planner sessions live in Memorystore Redis when `REDIS_URL` is set, so every replica shares them, and in memory
otherwise (development and tests). They expire after `SESSION_TTL_MINUTES` without activity.
