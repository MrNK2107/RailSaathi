# Integration: embedding the planner and consuming its result

RailSaathi AI is one app with six capabilities ([README](../README.md)). This page is for a host application that
wants only the **conversational journey planner** and its confirmed result, for example a booking module.

The planner does **not** book tickets, take payments or track PNRs. The host talks to it only through the HTTP API
in [API.md](API.md), and every planner route needs the signed session token.

## Embedding flow

1. **Open a session:** `POST /api/planner/sessions {"language": "ta"}`. Keep `session_id` and `session_token`.
   Send the token as `X-Session-Token` on every later call for that session.
2. **Pass an initial request** (optional): `POST /api/planner/sessions/{session_id}/messages {"message": "<what the passenger said>"}`.
3. **Show a planner UI** until `status == "confirmed"`. Use RailSaathi's mobile app, or your own UI on the same
   endpoints.
4. **Receive the result:** the confirm response contains `handoff`. You can also fetch it from
   `GET /api/planner/sessions/{session_id}/handoff`. Before confirmation that route answers 409 `not_ready`.
5. **Watch for changes:** after a reassessment, a new confirmation sets `replaces_confirmation_id`. Treat the
   newest confirmation as current.

Sessions expire after `SESSION_TTL_MINUTES` (120) without activity. Expect 410 `session_expired` or 404
`session_not_found` after that, and start a new session.

## Handoff payload (schema_version 1.0)

```jsonc
{
  "module": "smart_passenger_planner",
  "schema_version": "1.0",
  "session_id": "uuid",
  "status": "confirmed",
  "confirmation_id": "RSP-1A2B3C4D5E",
  "confirmed_at": "2026-10-10T10:00:00+05:30",
  "replaces_confirmation_id": null,
  "journey": {
    "origin": {"id": "coimbatore", "label": "Coimbatore", "kind": "city", "station_codes": ["CBE"]},
    "destination": {"id": "chennai", "label": "Chennai (any station)", "kind": "city", "station_codes": ["MAS", "MS"]},
    "journey_date": "2026-10-11",
    "date_refers_to": "arrival",
    "passenger_count": 2
  },
  "selected_option": {
    "option_id": "CBE-MAS-D103@2026-10-10",
    "legs": [{"train_no": "D103", "train_name": "Nilgiri Night Express", "from_code": "CBE", "to_code": "MAS",
              "departure": "2026-10-10T22:30:00+05:30", "arrival": "2026-10-11T06:45:00+05:30", "...": "..."}],
    "departure": "...", "arrival": "...", "duration_minutes": 495, "transfers": 0,
    "travel_class": "SL", "listed_fare_per_passenger": 295, "listed_total_fare": 590, "currency": "INR",
    "simulated_change": null
  },
  "constraints": {            // mandatory requirements the passenger stated
    "arrival_deadline": "09:00", "max_budget_total": null, "travel_class": null,
    "direct_only": false, "assistance_mandatory": false
  },
  "preferences": {            // soft preferences used for ranking
    "budget_priority": "minimize_cost", "preferred_arrival_by": null, "budget_target_total": null,
    "class_preference": null, "departure_window": null, "transfer_preference": null,
    "passenger_needs": ["assistance_requested"]
  },
  "verification": {
    "confirmed_by_passenger": ["origin", "destination", "journey_date", "passenger_count", "selected_option"],
    "hard_constraints": [{"name": "arrival_deadline", "status": "met", "detail": "..."}],
    "passenger_needs": [{"need": "assistance_requested", "status": "verified_supported", "detail": "..."}],
    "unverified": [],
    "fare_and_schedule_verified": false,   // always false: demo or third-party data
    "fare_available": true,
    "seat_availability_checked": false
  },
  "data_provenance": {"mode": "demo", "source": "RailSaathi demo dataset (simulated)", "as_of": "...", "note": "..."},
  "disclaimers": [
    "No ticket has been booked and no seat has been reserved.",
    "Assistance has not been booked or guaranteed; facility status reflects the data source only.",
    "Demo data: trains, timings and fares are illustrative."
  ]
}
```

### Rules for consumers

- `confirmed_by_passenger` lists what the passenger approved. Anything under `verification.unverified`, and
  anything where `fare_and_schedule_verified` is false, **must be re-verified** against an authoritative source by
  the booking module before it is shown as bookable. `fare_and_schedule_verified` is always false: the data is
  demo or third-party.
- Check `data_provenance.mode`:
  - `demo` means the trains and option ids are fictional. Never send them to a real booking system. Demo data is
    served only outside production.
  - `live`, `cached` and `stale` mean the trains came from RailRadar (third party, not official).
    - `stale` is an older cached answer.
    - RailRadar supplies no fares, so `fare_available` is usually false.
    - It has no station facility data, so passenger-need statuses are `unknown`.
- The payload holds no names, phone numbers or other personal details. The planner never collects them.
- A TypeScript type for the payload can be generated from `GET /openapi.json`, or copied from
  `frontend/src/api/types.ts`.

## Deployment notes for a host

- **Same origin:** the simplest setup proxies `/api/*` from the host's origin to the backend, as RailSaathi's own
  nginx does. Then the browser needs no CORS.
- **Cross origin:** otherwise add the host's origin to `CORS_ORIGINS`. The backend exposes `X-Request-Id` to
  browsers.
- **Rate limiting** is shared across replicas through Redis (`REDIS_URL`). It is keyed per client IP, taken from
  `X-Forwarded-For` with `TRUSTED_PROXY_HOPS` trusted proxies, and per session token. A host proxy must
  **overwrite** `X-Forwarded-For` with the real client IP, never append to it, and `TRUSTED_PROXY_HOPS` must match
  the proxy chain. Otherwise clients can choose their own rate-limit bucket. See [SECURITY.md](SECURITY.md).
- **Sessions** live in Redis when `REDIS_URL` is set, so any number of backend replicas can serve one session.
