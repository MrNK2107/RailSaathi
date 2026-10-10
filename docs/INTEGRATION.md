# Integration handoff: main RailSaathi AI app ↔ Smart Passenger Planner

The planner is self-contained. It does **not** book tickets, take payments,
track PNRs or navigate stations. Those belong to other modules. The main app
talks to it only through the HTTP API.

## Embedding flow

1. **Open the planner**: `POST /api/planner/sessions {"language": "ta"}`.
2. **Pass an initial request** (optional): `POST /api/planner/sessions/{id}/messages {"message": "<what the passenger said>"}`.
3. **Show the planner UI** (this frontend, or your own UI using the same endpoints) until `status == "confirmed"`.
4. **Receive the result**: the confirm response contains `handoff`, which you can also fetch from `GET /api/planner/sessions/{id}/handoff`.
5. **Watch for changes**: after a reassessment, a new confirmation sets `replaces_confirmation_id`. Treat the newest confirmation as current.

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
    "legs": [{"train_no": "D103", "train_name": "Demo Nilgiri Night Express", "from_code": "CBE", "to_code": "MAS",
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

- `confirmed_by_passenger` lists what the passenger approved. Everything under `verification.unverified`, and anything where `fare_and_schedule_verified` is false, **must be re-verified** by the booking module against an authoritative source before it is shown as bookable.
- When `data_provenance.mode` is `demo`, the option IDs and trains are fictional. Do not send them to a real booking system.
- The payload contains no names, phone numbers or other personal details; the planner never collects them.
- A TypeScript type for the payload can be generated from `GET /openapi.json`, or copied from `frontend/src/api/types.ts`.

## CORS and deployment

Add the main app's origin to `CORS_ORIGINS`. To deploy behind the main app's
gateway, expose the planner under `/api/planner/*` and put rate limiting at the
gateway, because the built-in limiter is per process. Swap
`InMemorySessionStore` for a shared store (the `SessionStore` protocol) when
running more than one worker.
