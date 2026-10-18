# Capability status and limitations

What each capability really does in this release, and what it does not do. Rule of thumb: anything that is
schematic, estimated or cached says so in its `provenance` and in the UI. If you find a place where it does
not, that is a bug. Demo data is the one exception in the UI: it is used only for local and development runs
(production refuses it), so the UI does not label it, while the API still reports `data_mode: demo`.

## Capability status

| Capability | Status | Main limits |
|---|---|---|
| 1. Conversational journey planner (EN, Tamil, common Tanglish; typed or spoken) | Working. The rule-based extractor always works; Gemini on Vertex AI is used when configured, with automatic fallback | Direct trains only with live data; no fares from NTES or RailRadar; facility data unknown; ranking weights are heuristics, not evaluated with passengers |
| 2. Goal planner ("reach my meeting") | Working on the same journey data and provenance | Same data limits; the buffer excludes the unknown walk from the station to the venue |
| 3. Ticketing guidance agent | Working. Gemini when configured, a rule-based agent otherwise | AI guidance, not official; a small, dated knowledge base (5 official sources, as of 2026-10-14); it must not state fares, charges or time limits the knowledge base does not hold |
| 4. Live station information | Working with NTES through the unofficial ntes-client (no key; the local and deploy default), or with a RailRadar key. Demo boards only outside production | NTES access is unofficial and can break or be blocked at any time; RailSaathi's own budget (20 requests/minute) means answers are sometimes `cached` or `stale`; boards list only stations in the catalogue |
| 5. Delay estimate | Working: trained model, MAE 40 min on held-out trains ([DELAY_MODEL.md](DELAY_MODEL.md)) | Large error; no date or time features; the source data's origin and age are undocumented; not live |
| 6. Station navigation, AR guidance, virtual tour | 4 stations; routing at Chennai Central only; AR off in production; tour working ([STATION_NAVIGATION.md](STATION_NAVIGATION.md)) | Schematic layouts, not surveyed; step-free status unknown everywhere; no Street View panoramas authored |

Not available at all: booking, payment, PNR, seat availability, fares from live data, official IRCTC data, and
an authorised NTES feed. NTES data comes only through `ntes-client`, an unofficial client of the NTES app backend
(the owner's decision); its PNR and captcha features are never used. Out of scope too: accounts, push, SMS or WhatsApp alerts, GPS
or beacon positioning, and languages other than English and Tamil.

## Data and honesty limits

- **Demo data** (fictional `D###` trains, simulated facilities and disruptions) exists only outside production.
  In production the service refuses it. Without a RailRadar key, searches and boards answer `unavailable` with a
  reason, and `/readyz` reports not ready.
- **NTES through the unofficial client** (`RAILWAY_DATA_MODE=ntes`):
  - it is not an official or authorised integration. NTES can change its app backend or block the client at any
    time; then every journey, board and status answers `unavailable` with a reason (never invented data);
  - it gives no fares, so options say "Fare: check on IRCTC" and a strict budget becomes *unverified*;
  - no station facility data, so assistance and wheelchair needs are always `unknown`;
  - direct trains only, between catalogue stations (NTES answers for station groups; trains from other stations of
    a group are left out);
  - "days of run" are read as the days the train leaves the boarding station;
  - NTES identifies a run by the date it left its origin. Running status and live disruptions use the date you
    ask for (the boarding date for a plan) as that date, so for a train boarded after midnight on its second day
    the status can belong to the previous day's run;
  - a full cancellation is claimed only for an unambiguous NTES alert or position text ("Train … is Cancelled");
    any other mention (partial, short-terminated, diverted, "cancellation details not available", a stretch of the
    route) is shown as "status unclear, check NTES or the station" and never triggers a re-plan. These patterns are
    not yet verified against a real cancelled run.
- **RailRadar** (alternative mode) is a third-party service, not an official Indian Railways source:
  - it returns no fares or classes, so a strict budget or class becomes *unverified* (not passed, and not
    excluded);
  - it has no station facility data, so assistance and wheelchair needs are always `unknown`;
  - it searches direct trains only;
  - only stations in `providers/data/station_catalogue.json` (about 36) can be named.

  Passengers are told to verify on official Indian Railways channels before travel.
- **The shared budgets** are 20 NTES requests per minute (RailSaathi's own politeness limit) or 10 RailRadar
  requests per minute (the key's limit), across every replica. When a budget is spent, answers are served from the
  cache as `stale`, or are `unavailable`.
- **Station layouts are schematic.** They are not surveyed and not to scale. Distances and times are estimates
  from the plan scale.
  - Only Chennai Central is traced from a plan image, and that plan shows platforms 7 to 12. Routes and AR cues
    elsewhere are unavailable or derived.
  - Nothing is marked step-free verified, because no pathway has been checked on site.
  - Helplines are national numbers only.
- **The delay model** is a statistical estimate from unverified historical averages ([DELAY_MODEL.md](DELAY_MODEL.md)).
  It is labelled `fallback`, never `live`. Live observations are collected, but none are used yet: RailRadar's
  live status has no station field.
- **Coach position** comes only from a coach composition the passenger enters. There is no live rake data.
- **Mobile UI images** on the home and route cards (route photos, the hero train) are decorative AI-generated
  illustrations from the team lead's design. They are not photographs of the named places.

## AR guidance

- **Not measured yet.** AR stays **off in production** (`AR_GUIDANCE_ENABLED` unset) until
  `backend/scripts/eval_localize.py` passes the gate in [AR_GUIDANCE.md](AR_GUIDANCE.md). The gate needs:
  - at least 80 % accuracy on accepted fixes, at the production threshold;
  - p95 latency under 4 s;
  - at least 30 photos taken on site, with at least 20 accepted fixes and 50 % coverage.

  The owner collects those photos.
- AR is always labelled approximate.
- It covers Chennai Central only, and its cues cover the platforms and concourse shown on the plan.
- WebXR floor anchoring is an Android enhancement. Elsewhere the arrow is gyroscope-relative between camera fixes.

## Language, speech and accessibility

- Every UI string has a Tamil translation. **A native speaker has not reviewed the Tamil yet**, including the
  station-name spellings.
- A few backend-generated details are English-only even in Tamil mode: recommendation notes, constraint details,
  need-status details and some envelope messages.
- The rule-based extractor covers common phrasings, not all of English or Tamil. Gemini improves coverage, but
  its output varies between calls.
- **Voice input** uses the browser's Web Speech API (Chrome or Edge, secure context only).
  - Tamil (`ta-IN`) and mixed Tamil-English accuracy is not verified.
  - The transcript is never sent automatically.
  - Read-aloud depends on the voices installed on the device.
- **Axe:** every screen passes axe with zero violations in the Playwright suite (the legacy `#/classic` desktop
  view has been removed; an old link opens home). Some states are also not axe-checked: goal results, ticketing answers and the Street View dialog.
- Street View under the production Content-Security-Policy has not been tested, because no Maps key or panoramas exist
  yet.

## Platform limits

- **No accounts.** The signed session tokens are bearer tokens: anyone holding a token can act on its session.
  Sessions expire after 120 minutes idle.
- **Rate limits** work per client IP and per session (60/min standard, 20/min for LLM routes). Many users behind
  one NAT share a bucket.
- Gemini runs on Vertex AI. When it is slow or down, the planner falls back to rules, and ticketing answers
  `unavailable` with official links. No LLM outage produces a 500.
- **Local model memory (2026-10-18, 16 GB RAM, RTX 5060 Laptop 8 GB).** With about 3.7 GB RAM free (2.4 GB when
  the load started), loading gemma4 through Ollama pushed the free-RAM counter to 0.0 GB at its lowest (it excludes
  standby cache, so this may overstate real pressure; VRAM 1.5 to 4.7 GB), so gemma4 answer latency and the
  "gemma4 (local)" provenance string were not measured. With Ollama as the only LLM and unreachable, ticketing chat answers `unavailable` with official links
  (no error) rather than rule-based guidance; the planner falls back to rules.
- **Public demo link not verified end to end.** `python run.py --public` was unit-tested only: cloudflared was
  not installed, so the tunnel, certificate behaviour, phone frame rate and mobile first-load time are
  to be measured (checklist in [STATION_NAVIGATION.md](STATION_NAVIGATION.md)).
- **Load-tested locally only so far.** `loadtest/k6/load.js` passed at 50 virtual users against a local backend
  in demo mode. The Cloud Run concurrency and instance settings are reasoned starting values. They have not yet
  been confirmed by a staging run ([RUNBOOK.md](RUNBOOK.md), "Load test").
- This is not a formal security audit and claims no regulatory compliance. The threat-model checklist is
  [SECURITY.md](SECURITY.md).

## Future work

1. On-site AR evaluation (at least 30 photos), then enable AR per station.
2. Trace or survey the Egmore, Bengaluru and Hyderabad layouts. Verify step-free pathways on site.
3. Station-level live observations (or another dated source) so the delay model can learn time effects.
4. A native Tamil review.
5. A staging load test and a 24-hour soak, then tag `v1.0.0`.
6. An authorised source for fares, availability and official disruptions, replacing the unofficial NTES client.
