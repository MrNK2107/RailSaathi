# Architecture

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
IntentExtractor ── Bedrock (optional) ──► IntentUpdate (raw text values, schema-validated)
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
| `providers/` | `JourneyProvider` and `DisruptionSource` protocols + demo implementation | — |
| `ranking/` | Hard-constraint evaluation, need verification, scoring, explanations | `JourneyProvider` |
| `disruption/` | Apply events, reassess, describe changes | `ranking`, `DisruptionSource` |
| `harness/` | State machine, clarification, merge, confirmation, handoff, i18n templates | all of the above |
| `sessions/` | `SessionStore` protocol + in-memory TTL store with per-session locks | — |
| `audit/` | Append-only event log separate from state | — |
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

## LLM provider (`intent/`)

`IntentLLM` is a one-method protocol. `BedrockIntentProvider` calls the Bedrock
Runtime **Converse API** with a forced tool (`toolChoice: {tool: record_journey_intent}`)
whose input schema is the Pydantic `IntentUpdate` schema with `$refs` inlined.
The tool input is then validated by Pydantic. On failure, `IntentExtractor`
falls back to the rule-based extractor.

When Claude succeeds, the rule-based result is still computed and used two ways:

- **Backfill:** core fields Claude left empty (places, date, deadline, passenger count) are filled from the rules. Claude's values are never overridden.
- **Rule-owned policy fields:** fields such as `date_anchor` (a stated arrival deadline means the date is the arrival day) always come from the rules.

The `extraction.source` value is then `bedrock+rules`. This was added after live testing showed Claude sometimes writing "9 AM tomorrow" into the time field and leaving the date empty. Persistent failures (credentials,
access denied, not configured) pause Bedrock for 5 minutes. Transient ones
(throttling, timeout, model error) do not. To swap vendors, implement
`extract_intent(message, context) -> IntentUpdate` and wire it in
`container.build_llm`.

## Security posture (prototype level)

- Secrets come only from backend environment / the AWS credential chain; the frontend bundle holds only the API base URL.
- CORS allow-list, body-size limit, per-IP rate limit, strict request schemas (`extra=forbid`), message length cap, Bedrock timeouts and retries.
- Structured errors without stack traces. Access logs record method, path, status and latency only; audit records contain field names, never message text.
- This is **not** a production security review or regulatory compliance claim.
