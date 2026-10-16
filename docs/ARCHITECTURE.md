# Architecture

RailSaathi AI is one FastAPI backend and one React PWA. The backend has six capabilities:

- the conversational planner;
- the goal planner;
- ticketing guidance;
- live station information;
- the delay estimate;
- station navigation, with AR and the virtual tour.

They all share one composition root (`app/container.py`), one provenance model, one error envelope, and Redis for
every piece of state that must outlive a request. The [README](../README.md) has the deployment picture and
[API.md](API.md) has the contract. This page covers how the parts fit together, starting with the planner, which
has the most logic.

## Platform

| Concern | How | Code |
|---|---|---|
| Composition | `build_container(settings)` wires every adapter once at startup (`create_app` factory, nothing built at import) | `app/container.py`, `app/main.py` |
| Shared state | Redis when `REDIS_URL` is set (sessions with `SET NX PX` locks, goal plans, chat history, rate-limit windows, RailRadar quota and cache, station closures, seen trains), every key with a TTL. In-memory twins for tests and single-process development | `sessions/`, `journey/plan_store.py`, `agent/conversation_store.py`, `security/rate_limit.py`, `providers/railradar_shared.py`, `navigation/services/disruption_store.py` |
| Middleware (outermost first) | Observability (request id, trace, JSON access log), then CORS, the rate limit (per IP and per session; LLM tier) and the body-size limit (streaming) | `api/observability.py`, `api/middleware.py` |
| Errors | One `{error:{code,message,details}, request_id}` envelope; no exception text in responses | `api/errors.py` |
| Blocking work | Handlers are async. Redis, SQLite, model inference and LLM calls run in the worker pool via `offload` | `api/deps.py` |
| LLMs | `ChatLLM` (Gemini on Vertex AI, or the rule-based `KeywordChatLLM`) for the ticketing agent; `IntentLLM` (Gemini, or Bedrock) for planner extraction, always backed by the rule-based extractor; `VisionLocalizer` (Gemini) for AR. Turn deadline `LLM_OVERALL_DEADLINE_SECONDS` | `llm/`, `intent/`, `agent/` |
| Provenance | `DataProvenance` + `DataMode` (`live`, `cached`, `stale`, `unavailable`, `demo`, `fallback`) on every data response; demo sources are refused in production | `domain/options.py`, `domain/enums.py` |
| Health | `/healthz` (no I/O), `/readyz` (blocking checks vs `degraded`), `/api/health` | `api/health.py` |
| Frontend | nginx serves the hashed build and proxies `/api/*` with security headers; an app-shell service worker that never caches the API; hash-routed lazy screens; English and Tamil strings | `frontend/nginx/`, `frontend/sw/`, `frontend/src/mobile/` |

## The planner

Think of the planner as a railway enquiry counter with a strict clerk. The
passenger can speak however they like. An interpreter (the LLM or the rule-based
extractor) writes down what they *seem* to want. The clerk (deterministic
code) checks every entry against the rulebook and timetable before anything is
offered, and nothing is final until the passenger signs.

## Request flow

```
Passenger text / voice transcript
        │
        ▼
IntentExtractor ── Gemini or Bedrock (optional) ──► IntentUpdate (raw text values, schema-validated)
        │  └─ on any failure ─► RuleBasedExtractor
        ▼
JourneyMerger ── StationResolver / date & time parsers (deterministic, injected clock)
        │         unresolved or ambiguous values become clarification issues
        ▼
WorkflowEngine ── validator ── missing fields? ─► one focused question
        │
        ▼ (all required fields valid)
Recommender ── JourneyProvider.search ─► evaluate hard constraints ─► score ─► categorise ─► explain
        │
        ▼
Passenger selects → confirms → ConfirmationRecord + handoff payload
        │
DisruptionService (on request) ─► re-rank with event applied ─► passenger must re-confirm
```

## Module boundaries

| Module | Responsibility | Depends on |
|---|---|---|
| `intent/` | Interpret text into `IntentUpdate`; LLM adapter interface (`IntentLLM`) | `stations` (rules only) |
| `validation/` | Parse dates/times/classes; validate a `JourneyDetails` | nothing external |
| `stations/` | Resolve names, aliases and Tamil script to `Place`s; never auto-substitutes | `JourneyProvider` |
| `providers/` | `JourneyProvider`, `DisruptionSource` and `LiveSource` protocols; NTES through the unofficial ntes-client, RailRadar (each with a shared request budget and cache) and demo implementations | — |
| `ranking/` | Hard-constraint evaluation, need verification, scoring, explanations | `JourneyProvider` |
| `disruption/` | Apply events, reassess, describe changes | `ranking`, `DisruptionSource` |
| `harness/` | State machine, clarification, merge, confirmation, handoff, i18n templates | all of the above |
| `sessions/` | `SessionStore` protocol, Redis store (TTL, `SET NX PX` lock) and in-memory store | — |
| `audit/` | Audit events as structured log lines (statuses and field names, no message text) | — |
| `api/` | HTTP schemas, routes, middleware | `harness` |

The LLM never touches validation, ranking, fares, timetables or confirmation.
It only proposes raw values such as `"tomorrow"` or `"Kovai"`, which application
code resolves.

## Workflow state machine

Statuses: `collecting_details`, `needs_clarification`, `validating_request`,
`searching_options`, `presenting_recommendations`, `awaiting_confirmation`,
`confirmed`, `no_feasible_options`, `cancelled`, `error`.

Legal transitions live in `app/domain/transitions.py`. Every transition is
checked by `ensure_transition` and recorded in the audit log. Highlights:

- `searching_options → presenting_recommendations | no_feasible_options`
- `presenting_recommendations → awaiting_confirmation` (option selected)
- `awaiting_confirmation → confirmed` (only via confirm, with freshness checks)
- `confirmed → presenting_recommendations` (reassessment; the old confirmation stays until a new one replaces it)
- `cancelled → collecting_details` (restart only)

### Session state (authoritative snapshot)

See `app/domain/state.py`. Key fields: `status`, `language`, `journey`
(`JourneyDetails`), `missing_fields`, `validation_errors`, `pending_question`,
`pending_candidates`, `selected_option_id`, `recommendations`
(`RecommendationSet`, including `constraints_hash`), `reassessment`,
`confirmation`, `data_mode`, `extraction_source` and `version`.

`JourneyDetails.field_sources` records whether each value was `explicit`,
`inferred` (for example "5 Jan" rolled to next year) or `edited` in the form.

### Staleness and duplicate protection

- Each `RecommendationSet` stores a `constraints_hash` of the journey it was computed for. Any change to a constraint invalidates recommendations, and the planner recomputes when the request is valid.
- Confirmation is rejected if the hash differs, the set is older than `RECOMMENDATION_TTL_MINUTES`, the train has departed, or validation fails.
- Confirm is idempotent: a repeated call returns the same confirmation ID.
- Requests for the same session are serialised by a per-session lock.

## Ranking model (`ranking/scoring.py`)

1. **Hard constraints** (`evaluate.py`) reject options that violate any of these:
   - departs in the future
   - feasible connection (≥ `MIN_TRANSFER_MINUTES`, or 60 with "longer connection")
   - mandatory arrival deadline
   - strict budget
   - strict class
   - direct-only
   - mandatory assistance not supported

   If mandatory assistance is only *unknown*, the option stays eligible but is marked not fully compliant. Category picks prefer fully compliant options.
2. **Normalised components** in [0, 1]: cost (min-max on total fare), time (min-max on duration), departure-window fit (1 inside the window, linear decay over 6 h), transfers `1/(1+n)`, and preferences (preferred class, soft deadline, soft budget, assistance verified=1 / unknown=0.5 / unsupported=0).
3. **Weights**: base `cost .30, time .30, departure .15, transfers .10, preference .15`. The priority objective (cheapest or fastest) is raised to 0.80. Departure weight is 0 when no window is set. Transfers rise to 0.25 for direct-only preferences or for travel with children or elderly passengers. Weights are then renormalised to sum to 1.
4. **Categories**: Best overall (top score), Lowest cost, Fastest. When several categories pick the same option, it gets one card with multiple labels.

The weights are prototype heuristics. **They have not been tuned or evaluated**
against real passenger outcomes.

## LLM providers for intent extraction (`intent/`)

`IntentLLM` is a one-method protocol (`extract_intent(message, context) -> IntentUpdate`), and `build_llm()` in
`container.py` picks the provider from `LLM_PROVIDER`:

- **`gemini`** (production default): `GeminiIntentProvider` on Vertex AI with structured output.
- **`bedrock`** (optional): `BedrockIntentProvider`, Claude through the Converse API with a forced tool
  (`record_journey_intent`). See [BEDROCK_SETUP.md](BEDROCK_SETUP.md).
- **`none`**: the deterministic rule-based extractor only.

Every LLM output is validated by Pydantic. On any failure or timeout, `IntentExtractor` falls back to the
rule-based extractor.

When the LLM succeeds, the rule-based result is still computed and used in two ways:

- **Backfill:** core fields the LLM left empty (places, date, deadline, passenger count) are filled from the rules.
  The LLM's values are never overridden.
- **Rule-owned policy fields:** fields such as `date_anchor` always come from the rules. For example, a stated
  arrival deadline means the date is the arrival day.

`extraction.source` is then `<provider>`, or `<provider>+rules` when the rules filled something in, or `rules`
on fallback. Persistent failures (credentials, access denied, not configured)
pause the provider for 5 minutes. Transient ones (throttling, timeout, model error) do not.

## Security

Threat model, controls and open risks: [SECURITY.md](SECURITY.md).
