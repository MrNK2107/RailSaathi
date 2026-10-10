# Planner API contract (v0.1.0)

Base URL: `http://localhost:8000`. Interactive OpenAPI docs: `/docs`; schema: `/openapi.json`.
Reproducible requests: [requests.http](requests.http) (VS Code REST Client / JetBrains HTTP client).

All planner responses share the `PlannerResponse` envelope:

```jsonc
{
  "session_id": "uuid",
  "assistant_message": "Where will you be travelling from?",
  "status": "collecting_details",            // workflow status
  "state": { /* full SessionState, authoritative */ },
  "missing_fields": ["origin", "passenger_count"],
  "validation_errors": [{ "field": "destination", "code": "ambiguous_station", "message": "...", "candidates": ["..."] }],
  "recommendations_ready": false,
  "confirmation_required": false,
  "data_mode": "demo",
  "data_notice": "DEMO DATA: ...",
  "extraction": { "source": "rules", "fallback_reason": "llm_disabled" },   // message endpoint only
  "handoff": null                                                          // set once confirmed
}
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Service status, version, data mode, data provider (`demo`/`railradar` and fallback reason), AI status (no secrets) |
| GET | `/api/planner/reference` | Places, classes, needs and demo events for edit forms |
| GET | `/api/planner/disruption-events` | List simulated disruption events |
| POST | `/api/planner/sessions` | Start a session `{ "language": "en" \| "ta" }` → 201 |
| GET | `/api/planner/sessions/{id}` | Current state |
| POST | `/api/planner/sessions/{id}/messages` | Process a passenger message `{ "message", "language"? }` |
| PATCH | `/api/planner/sessions/{id}/journey` | Manual field corrections (only sent fields change; `null` clears) |
| POST | `/api/planner/sessions/{id}/recommendations` | (Re)compute recommendations; requires valid details |
| POST | `/api/planner/sessions/{id}/select` | Select an option `{ "option_id" }` → `awaiting_confirmation` |
| POST | `/api/planner/sessions/{id}/confirm` | Confirm for handoff `{ "option_id"? }`. **Does not book.** |
| POST | `/api/planner/sessions/{id}/reassess` | Apply a disruption `{ "event_id"? }` (auto-pick if omitted) |
| POST | `/api/planner/sessions/{id}/cancel` | Cancel the workflow |
| GET | `/api/planner/sessions/{id}/handoff` | Confirmed handoff payload (409 if not confirmed) |
| GET | `/api/planner/sessions/{id}/audit` | Audit events (statuses and field names only) |

The message endpoint also handles corrections ("change the date to Sunday"),
selection ("option 2", "choose the cheapest"), confirmation ("confirm"),
cancellation ("cancel") and restart ("start over") in English or Tamil.

## Examples

### Start and send a message

```http
POST /api/planner/sessions
{"language": "en"}

POST /api/planner/sessions/{id}/messages
{"message": "I need to reach Chennai before 9 AM tomorrow"}
```

Response excerpt:

```json
{
  "assistant_message": "Where will you be travelling from?",
  "status": "collecting_details",
  "missing_fields": ["origin", "passenger_count"],
  "state": { "journey": {
      "destination": {"id": "chennai", "label": "Chennai (any station)", "kind": "city", "station_codes": ["MAS", "MS"]},
      "journey_date": "2026-10-11", "date_anchor": "arrival",
      "arrival_deadline": "09:00", "deadline_strict": true } }
}
```

### Recommendations (excerpt of `state.recommendations`)

```json
{
  "constraints_hash": "3f1c…",
  "considered_count": 6, "eligible_count": 3,
  "recommendations": [{
    "labels": ["best_overall", "lowest_cost"],
    "option": {"option_id": "CBE-MAS-D103@2026-10-10", "departure": "2026-10-10T22:30:00+05:30",
               "arrival": "2026-10-11T06:45:00+05:30", "duration_minutes": 495, "transfers": 0,
               "provenance": {"mode": "demo", "source": "RailSaathi demo dataset (simulated)"}},
    "selected_class": "SL", "fare_per_passenger": 295, "total_fare": 590, "fully_compliant": true,
    "hard_constraints": [{"name": "arrival_deadline", "status": "met", "detail": "Arrives 06:45 on 11 Oct, before the 09:00 deadline."}],
    "explanation": "Recommended because it is the strongest overall match for your priorities and it has the lowest listed demo fare among eligible options (₹590 for 2). It arrives at 06:45, 11 Oct, before your 09:00 deadline.",
    "unverified": []
  }],
  "excluded": [{"option_id": "CBE-MS-D105@2026-10-10", "summary": "D105 Demo Cheran Late Passenger: …", "reasons": ["Arrives 09:40 on 11 Oct, after the 09:00 deadline."]}],
  "notes": ["Cheaper option excluded — D105 …: Arrives 09:40 on 11 Oct, after the 09:00 deadline."],
  "relax_suggestions": [],
  "limitations": ["Demo data: trains, timings and fares are illustrative, not real Indian Railways data.", "Seat availability is not checked and no ticket is booked."]
}
```

### Reassess

```http
POST /api/planner/sessions/{id}/reassess
{"event_id": "SIM-DELAY-D103"}
```

`state.reassessment` then contains: `event_label`, `simulated: true`,
`affected_option_ids`, `selected_option_affected`, `original_still_valid`,
`changes` (for example "D103 delayed 150 min (simulated): arrival moves from 06:45 11 Oct to 09:15 11 Oct."),
`previous_selection` and `requires_confirmation: true`. The previous
`confirmation` is kept until the passenger confirms a replacement.

## Errors

```json
{"error": {"code": "not_ready", "message": "Required journey details are missing or invalid.", "details": {"missing_fields": ["origin"]}}}
```

| HTTP | code | When |
|---|---|---|
| 404 | `session_not_found` | Unknown session ID |
| 410 | `session_expired` | Idle longer than `SESSION_TTL_MINUTES` |
| 409 | `not_ready` | Search or confirm before required steps |
| 409 | `no_recommendations` | Select or reassess without current recommendations |
| 409 | `stale_recommendations` | Constraints changed, TTL passed, train departed or no longer compliant |
| 409 | `session_cancelled` | Action on a cancelled session (except restart) |
| 409 | `invalid_transition` | Illegal workflow transition |
| 409 | `no_relevant_event` | Auto reassess found no event affecting the plan (or no live delays reported) |
| 503 | `data_unavailable` | Live data provider failed during reassessment |
| 404 | `unknown_event` | Unknown disruption event ID |
| 422 | `invalid_option` | Option not in the current recommendations |
| 422 | `invalid_request` / `validation_failed` | Schema or value errors |
| 413 | `payload_too_large` | Body over `MAX_BODY_BYTES` |
| 429 | `rate_limited` | Over `RATE_LIMIT_PER_MINUTE` per client IP |
| 500 | `internal_error` | Unexpected error (no stack trace exposed) |

In the **message** endpoint, user-level problems (for example "confirm" with
nothing selected) come back as a normal 200 with an explanatory
`assistant_message` rather than an HTTP error.

## Session lifecycle

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

Sessions live in memory and expire after `SESSION_TTL_MINUTES` without activity.
Restarting the backend clears all sessions.
