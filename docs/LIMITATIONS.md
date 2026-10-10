# Capability status, limitations and future work

## Capability status

| Capability | Status |
|---|---|
| Conversational planning (EN, Tamil script, common Tanglish), clarification, corrections, cancel/restart | **Functional** (rule-based) |
| Deterministic validation (dates in Asia/Kolkata, stations, counts, budget, times, contradictions) | **Functional** |
| Multi-objective ranking, hard/soft constraints, explanations, relax suggestions | **Functional** on demo data |
| Passenger needs with verified, not-supported and unknown statuses | **Functional**; facility data is **simulated** |
| Disruption reassessment | **Functional**; events are **simulated** |
| Confirmation and handoff payload | **Functional**; no booking |
| Claude via AWS Bedrock (Converse, forced tool output) | **Functional — verified live on 2026-10-10** in us-west-2 with `us.anthropic.claude-haiku-4-5-20251001-v1:0` (all demo scenarios pass). Automated tests stay mocked. Needs valid AWS credentials; temporary workshop credentials expire. |
| Voice input | Works where the browser supports Web Speech (Chrome/Edge). Tamil (`ta-IN`) accuracy, including mixed Tamil-English, is **not verified**. |
| Read-aloud | Browser `speechSynthesis`; voice availability (especially Tamil) varies by OS. |
| Live train data via RailRadar (trains between stations, live running status) | **Implemented and mock-tested**; needs your RailRadar API key (`RAILWAY_DATA_MODE=railradar`). **Verified live on 2026-10-10** (real trains mapped 12/12; live status works). Limits: 10 requests/minute, no fares or classes from this endpoint, direct trains only — see [RAILRADAR_SETUP.md](RAILRADAR_SETUP.md). Third-party, not official IR. |
| Official IRCTC/NTES data, seat availability, booking, payment, PNR | **Not available** in this module |

## Known limitations

- **Demo data by default.** Without a RailRadar key, trains, timings, fares, station facilities and disruptions are fictional. With RailRadar, timings are live but fares may be missing, station facilities are always unknown, only direct trains are searched, and only stations in `station_catalogue.json` can be named. Fares are illustrative per-passenger amounts with no concessions, quotas or dynamic pricing.
- **The rule-based extractor covers common phrasings,** not all of English or Tamil. Unusual wording may be missed. The assistant then asks again, and the edit form is always available. Bedrock improves coverage.
- **Some assistant text is English-only:** recommendation notes, constraint details and need-status details are English even in Tamil mode. Cards and the main assistant messages are bilingual.
- **"Arrive by" with a departure date** is interpreted as "arrive by that time on the departure day, or the next morning if the time has already passed at departure". For "reach before 9 AM tomorrow" the date counts as the arrival date.
- **LLM output varies between calls** even at temperature 0 (e.g. a Tanglish time phrase caught in one run and missed in the next). The rule-based backfill and deterministic validation limit the impact, but extraction is not perfectly repeatable.
- **Ranking weights are heuristics** and have not been evaluated with real passengers.
- **Sessions are in memory:** they are lost on restart and not shared across worker processes. Rate limiting is per process.
- **Speech:** recording continues until the user presses Stop (the browser session is restarted automatically after pauses). Words appear live in the text box; the transcript is never auto-submitted, and Send is disabled while recording. Unsupported browsers show a text-only notice.
- **Time zones:** the backend computes in Asia/Kolkata. The UI formats times in Asia/Kolkata regardless of the device time zone.
- **No authentication:** session IDs are random UUIDs, and anyone with the ID can act on the session. Put the planner behind the main app's auth for real use.
- Not a production security review, and no regulatory compliance is claimed.

## Remaining work for live data

1. Obtain authorised access to timetable, fare and availability data, and to a trusted disruption feed. Respect each source's terms; do not scrape.
2. Implement `JourneyProvider` and `DisruptionSource` (see [DATA_PROVIDERS.md](DATA_PROVIDERS.md)), including timeouts, caching and freshness (`DataMode.STALE`).
3. Source verified station accessibility and assistance data, and keep `unknown` as the default.
4. Replace the in-memory session store with Redis or Postgres; add authentication and gateway rate limiting.
5. Configure Bedrock (see [BEDROCK_SETUP.md](BEDROCK_SETUP.md)) and evaluate extraction quality on real Tamil and Tanglish samples.
6. Evaluate ranking weights with user testing; consider per-passenger weight profiles.
7. Hand the confirmed plan to the booking module, which must re-verify fares and availability.
