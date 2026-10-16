# Security: threat-model checklist

Scope: the release-1 deployment (the frontend nginx and backend FastAPI services on Cloud Run, Memorystore Redis,
Vertex AI, RailRadar and Cloud Storage), used by anonymous public passengers with no accounts.

This is an engineering checklist, not a formal audit or a compliance claim. Each item names the code or config
that implements it. Open risks are listed at the end, with what would close them.

## Assets and trust boundaries

| Asset | Where | Why it matters |
|---|---|---|
| Secrets: `SESSION_SIGNING_KEY`, `RAILRADAR_API_KEY`, `REDIS_URL` (with the AUTH string), the Maps browser key | Secret Manager, mounted as env vars on the backend | Token forgery, quota theft, data access |
| Session state, plans, chat history | Redis, keyed by session id, with TTLs | Another user's journey details |
| RailRadar quota (10 requests/minute) and Gemini spend | shared across replicas | Denial of service for everyone; cost |
| Station closures | Redis, written only by internal endpoints | False closures would misroute passengers |
| Camera frames (AR) | memory only; sent to Vertex AI | Passenger privacy |
| Station data, delay model artifact | image or Cloud Storage | A tampered pickle is code execution; tampered layouts misroute passengers |

The trust boundaries are:

1. Browser to the frontend: public internet, HTTPS only.
2. Frontend to the backend: Cloud Run to Cloud Run over HTTPS.
3. Backend to Redis: private VPC.
4. Backend to Vertex AI, RailRadar and Cloud Storage: Google APIs and a third party.
5. Cloud Scheduler to `/internal/*`: an OIDC token.

## Checklist

### Spoofing and session integrity

- [x] Session tokens are HMAC-signed session ids (`security/tokens.py`). Every planner route checks that the token
      was issued for that `session_id` (`api/deps.py verify_session_token`). A forged or foreign token gets 401.
- [x] Goal plan ids are server-issued and bound to the token's session. A foreign plan id behaves like an unknown
      one (`journey/plan_store.py load_owned`).
- [x] Chat history is keyed by (verified session, conversation id). A conversation id is useless without its
      token.
- [x] `SESSION_SIGNING_KEY` is required in production (startup fails without it) and shared by all replicas.
- [x] `/internal/*` verifies a Google ID token: signature, expiry, issuer, audience, verified email and the exact
      service account (`api/internal_auth.py`). Without configuration it is disabled (404). Errors never say which
      check failed.
- [ ] The real Cloud Scheduler token has not been tested end to end; tests mock Google's keys. RUNBOOK checklist.

### Tampering

- [x] The navigation API is read-only. Station data is published only by `scripts/stations.py` with Cloud Storage
      IAM. Station closures are written only through the OIDC endpoints. Simulated closures are refused in
      production. What-if `simulate_closures` is per request, never stored, and refused in production.
- [x] Strict request schemas (`extra="forbid"`), path and query patterns for codes interpolated into upstream URLs
      (`^[A-Za-z0-9]{1,8}$`), and enum-constrained model output for AR (node ids only).
- [x] The delay artifact is a pickle. It is loaded only from the image or `DELAY_MODEL_URI`, the artifact version
      and scikit-learn version are checked, and the docs say to load only your own pipeline's files. Keep write
      access to that bucket narrow.
- [x] The knowledge base is SQLite, built at image-build time and opened read-only (`mode=ro`).

### Repudiation and auditing

- [x] Every request carries an `X-Request-Id` (accepted only if `^[A-Za-z0-9._:-]{1,64}$`, otherwise generated).
      Request ids and the Cloud Trace context are logged on every line (`api/observability.py`).
- [x] Audit events record statuses and field names, never message text. Internal writes log the caller's service
      account.
- [x] Passenger message text is never logged unless `LOG_MESSAGE_CONTENT=true`.

### Information disclosure

- [x] One error envelope for every router. Exception text and stack traces never reach a response
      (`api/errors.py`); unhandled errors are logged server-side with the request id.
- [x] No static mount of the data directory. The only station assets are the allowlisted map and info routes, and
      the smoke test checks that `/data/...` is 404.
- [x] Secrets are `SecretStr` and are never logged. The RailRadar key goes only in the `Authorization` header from
      the backend. The cache keys use a fingerprint of the key, not the key. `/api/health` shows configuration
      state, never values.
- [x] The browser gets only the public, referrer-restricted Maps key (`/api/client-config`), and only when one is
      configured.
- [x] AR frames are sniffed by magic bytes, kept in memory only, sent to Vertex AI, and never stored or logged.
      Only the node id, confidence, latency and status are logged.
- [x] The app collects no names, phone numbers or other personal details. The handoff payload holds none.
- [ ] `/docs` and `/openapi.json` are public in production. Low risk, since the API is documented anyway (open
      risk R5).

### Denial of service and cost

- [x] Redis sliding-window rate limits per client IP and per session token: 60/min standard, 20/min on LLM routes.
      Health routes are exempt. The limiter fails open after 1 s, so a Redis outage does not take the API down.
- [x] AR has its own budget: 20 fixes per session and 120 per IP per 10 minutes.
- [x] Body limits are enforced while streaming: 16 KiB by default, and the 1.5 MB frame only on `/localize`. nginx
      allows 64 KiB on `/api/*` and 2 MiB on `/api/navigation/localize`. Messages are capped at 1,000 characters.
- [x] LLM work per turn is capped by `LLM_OVERALL_DEADLINE_SECONDS` (20 s), retries and agent budgets
      (`MAX_AGENT_ROUNDS`, `MAX_TOOL_CALLS`). The session lock TTL outlives the deadline.
- [x] One RailRadar quota is shared by all replicas. It fails closed when Redis is down, so the key is never
      overrun. Refusals are logged and alerted on (`infra/monitoring/`).
- [x] Cloud Run max instances bound the spend.

### Elevation of privilege and injection

- [x] **Prompt injection in the ticketing agent** (`agent/fencing.py`):
  - every tool result is wrapped in an escaped, length-capped untrusted block;
  - tool errors are mapped to short typed codes;
  - the system prompt says to ignore instructions inside tool output;
  - a code-enforced output link allowlist keeps only `https://` links on irctc.co.in, indianrail.gov.in and
    indianrailways.gov.in;
  - agent rounds and tool calls are budgeted.

  An injection corpus and property tests run in CI.
- [x] The LLM never touches validation, ranking, fares or confirmation. It only proposes raw values that
      deterministic code resolves.
- [x] The backend container runs as a non-root user (`backend/Dockerfile`). Images are built in CI and deployed
      through Workload Identity Federation, with no long-lived keys.
- [ ] The frontend nginx image runs as nginx's default user setup: the master process is root and the workers are
      unprivileged (open risk R9).
- [ ] The runtime service account is the project's default compute service account
      ([DEPLOYMENT.md](DEPLOYMENT.md)). In many projects it has the broad Editor role (open risk R8).

### Browser

- [x] nginx (`frontend/nginx/security-headers.conf`) sends the security headers on every location:
  - a Content-Security-Policy with `default-src 'self'`, `frame-ancestors 'none'`, `object-src 'none'`,
    `base-uri 'self'` and `form-action 'self'`;
  - HSTS, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` and a strict Referrer-Policy;
  - a Permissions-Policy that limits camera, microphone and sensors to the app itself.

  The CSP is tested in a real browser against the production build (`npm run e2e:dist`).
- [x] Same-origin API through the proxy: there is no CORS wildcard, and CORS is off unless `CORS_ORIGINS` is set.
- [x] The service worker caches only the app shell, never `/api` responses, and never puts responses other than
      the shell under the shell key.
- [x] Model output is rendered as plain text through an allowlisted renderer. No HTML from the model reaches the
      DOM.
- [x] Camera and microphone are used only in secure contexts. Speech transcripts are never sent automatically.

### Supply chain

- [x] **Backend:** `pip-audit` in CI over every locked package, hashes required. It fails on any known
      vulnerability. Locally on 2026-10-16 it found pytest 8.4.2 (CVE-2025-71176, a local `/tmp` directory issue
      in the test runner). Fixed by upgrading to pytest 9.1.1. pip-audit now reports no known vulnerabilities.
- [x] **Frontend, shipped dependencies:** `npm audit --omit=dev --audit-level=high` in CI with no exceptions. It
      reports 0 vulnerabilities.
- [x] **Frontend, whole tree:** `node scripts/audit-gate.mjs` in CI. It fails on any high or critical advisory that
      is not accepted in `frontend/audit-allowlist.json`, where each entry needs a reason and a review-by date,
      and it fails again once an entry expires.
  - The local audit on 2026-10-16 found 16 advisories, all in dev tooling: 3 critical, 8 high and 5 moderate.
  - Fixed by upgrading vite 5 → 6.4.4, vitest 2 → 4.1.12 and @playwright/test 1.49 → 1.56.1, and by running
    `npm audit fix`.
  - Remaining: one high advisory (GHSA-vfj7-8cjw-p6xm, braces) and one moderate (GHSA-rj75-hqrm-r3gf,
    postcss-selector-parser).
    - Both come only from Tailwind CSS 3, at build time, over our own fixed content globs.
    - braces 3.0.3 is the latest release, so no fix exists. The high one is allowlisted until 2027-01-16.
    - Removing both means migrating to Tailwind CSS 4.
- [x] Pinned GitHub Actions major versions, `uv sync --frozen` and `npm ci` from lockfiles.

## Open risks

| # | Risk | Impact | What would close it |
|---|---|---|---|
| R1 | **The backend's own Cloud Run URL is public** (`--allow-unauthenticated`), and `TRUSTED_PROXY_HOPS=2` is right only for traffic that comes through the frontend nginx. A client calling the backend URL directly can put its own value into `X-Forwarded-For` and choose its per-IP rate-limit bucket, and it can omit the session token. | Per-IP rate limits can be bypassed on direct calls; LLM spend is bounded only by max instances and the per-turn deadline | Make the backend reachable only through the frontend. Either set `--ingress internal` with the frontend on Direct VPC egress (all traffic), or require IAM auth (`--no-allow-unauthenticated`) and have nginx send an ID token. Then direct calls are rejected |
| R2 | Session tokens are bearer tokens with no expiry of their own. The session state behind them expires after 120 min idle | A leaked token gives access to that session's journey until it expires | Accounts or short-lived tokens, out of scope for release 1 |
| R3 | The CSP `script-src` (`frontend/nginx/security-headers.conf`) is broad for Maps JavaScript and Street View: `'self' https://maps.googleapis.com https://*.googleapis.com https://*.gstatic.com https://*.google.com https://*.ggpht.com https://*.googleusercontent.com blob:`. The largest exposures are **`https://*.googleusercontent.com`**, which serves user-uploaded content and is a well-known CSP bypass host, and **`blob:`**, which runs any script the page can turn into a blob URL. The other wildcards also cover any script-hosting path on those Google domains | If an attacker can inject markup (no such sink is known: model output is rendered as plain text), the CSP would not stop a script loaded from an attacker's googleusercontent.com upload or a blob URL, so it is weaker defence in depth than `'self'` alone suggests | Not changed in this release. Options: (a) per-response nonces plus `'strict-dynamic'`, so only scripts loaded by our own bundles run and the host list stops mattering; (b) narrow to the specific Maps JavaScript hosts and drop `*.googleusercontent.com` and `blob:` once Street View is tested with a key and the hosts it needs are known; (c) deploy the tightened policy as `Content-Security-Policy-Report-Only` first, collect violation reports, then enforce |
| R4 | Gemini (intent extraction, ticketing, AR) can still be manipulated by crafted input within the fences | Misleading guidance text, still without non-allowlisted links and without touching validation or booking | Ongoing red-team corpus; the "AI guidance, not official" label stays |
| R5 | `/docs` and `/openapi.json` are public | Easier reconnaissance (the API is public and documented anyway) | `FastAPI(docs_url=None, openapi_url=None)` in production if wanted |
| R6 | Rate limits per IP penalise many users behind one NAT, such as station Wi-Fi | Shared 429s at busy stations | Per-session limits with tokens; raise the IP tier after measuring |
| R7 | The dev-tooling advisories accepted in `audit-allowlist.json` | None in production (build time only) | The Tailwind CSS 4 migration |
| R8 | Both services run as the default compute service account, which often holds `roles/editor` | A code-execution bug in either service would get project-wide write access | A dedicated runtime service account per service with only `secretmanager.secretAccessor` on its secrets, `aiplatform.user` and the bucket roles, passed as `--service-account` in `deploy.yml` |
| R9 | The nginx master process runs as root inside the frontend container | Defence in depth only (Cloud Run sandboxes the container) | `nginxinc/nginx-unprivileged` as the base image |

## Reporting

Report vulnerabilities privately to the repository owner rather than in public issues. Do not test against
production. Use a local or staging deployment ([RUNBOOK.md](RUNBOOK.md)).
