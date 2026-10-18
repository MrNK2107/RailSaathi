# RailSaathi AI

An Indian Railways passenger assistant: a mobile-first progressive web app in English and Tamil, with a FastAPI
backend on Google Cloud Run. It plans journeys from what a passenger says, answers ticketing questions with
citations, shows departure boards and delay estimates, and guides passengers through a station.

**It never books a ticket.** Every railway, station, model or AI answer carries its provenance: `live`,
`cached`, `stale`, `unavailable`, `demo` or `fallback`. Schematic, estimated, demo or cached data is never
presented as verified or live. Demo data exists only for local and development runs (production refuses it), so
the UI does not label it; see [What you see locally](#what-you-see-locally). The capability-by-capability limits are in
[docs/LIMITATIONS.md](docs/LIMITATIONS.md).

## The six capabilities

| # | Capability | What it really does | Code |
|---|---|---|---|
| 1 | **Conversational journey planner** | Free text or speech (English, Tamil, common Tanglish) becomes validated journey details, with one question at a time. Options are ranked against hard and soft constraints and explained from computed values. Disruptions trigger a re-plan that the passenger must confirm. The result is a confirmed handoff payload | `backend/app/{intent,harness,ranking,disruption}/` |
| 2 | **Goal planner** | "Reach my meeting by 11:00": trains that arrive with a buffer, from the same journey data | `backend/app/journey/` |
| 3 | **Ticketing guidance agent** | Gemini (or a rule-based agent) answers from a small knowledge base of official IRCTC and Indian Railways pages and cites them. Tool output is fenced and links are allowlisted. AI guidance, not official | `backend/app/{agent,knowledge,llm}/` |
| 4 | **Live station information** | Departure boards, schedules and running status from NTES through `ntes-client`, an **unofficial** client of the NTES app backend (labelled "NTES (unofficial client)"), or from RailRadar (a third-party service). Neither is official. One shared request budget and cache across replicas. Stale or unavailable states are shown as such | `backend/app/providers/` |
| 5 | **Delay estimate** | A trained gradient-boosting model. Its measured error is shown with every answer: **MAE 40 min** on held-out trains ([model card](docs/DELAY_MODEL.md)) | `backend/app/delay/` |
| 6 | **Station navigation** | Routes over **schematic** layouts at 4 stations (routing at Chennai Central only), current and what-if closures, a 3D virtual tour, and camera (AR) guidance that stays off in production until its evaluation passes | `backend/app/navigation/`, `frontend/src/{navigation,ar,tour}/` |

The mobile UI (dashboard, voice assistant, route cards and station navigation screen) is the design of the team
lead, **PaulShervin**. It was ported onto this repository's API client, provenance badges and Tamil strings. See
[docs/STATION_NAVIGATION.md](docs/STATION_NAVIGATION.md).

## How it runs

```
browser (PWA, HTTPS) ──► frontend: nginx on Cloud Run ── /api/* ──► backend: FastAPI on Cloud Run
                          static app + security headers               │
                                                                      ├─ Memorystore Redis: sessions, plans, chats, rate limits,
                                                                      │  NTES/RailRadar budgets + caches, station closures (all with TTLs)
                                                                      ├─ Vertex AI Gemini: intent extraction, ticketing agent, AR vision
                                                                      ├─ NTES via ntes-client (unofficial) or RailRadar: live train data
                                                                      └─ Cloud Storage: station catalogue, delay model, observations
```

Requests are same-origin, so the browser needs no CORS. The backend exposes no static files. Details:
[ARCHITECTURE](docs/ARCHITECTURE.md), [DEPLOYMENT](docs/DEPLOYMENT.md), [RUNBOOK](docs/RUNBOOK.md) and
[SECURITY](docs/SECURITY.md).

## Quick start (Windows, macOS, Linux)

Prerequisites: Python 3.12, [uv](https://docs.astral.sh/uv/) and Node.js 20+. No cloud account or API key is
needed. `python run.py` uses live NTES train data (through an unofficial client, see below), the rule-based
extractor and the rule-based ticketing agent.

The quickest way is one command from the repository root. It runs `uv sync` (and `npm install` the first time),
then starts the backend on port 8010 and the frontend on port 5173 until Ctrl+C:

```bash
python run.py                                      # https://localhost:5173, also on your Wi-Fi address
python run.py --no-https                           # plain http://localhost:5173
python run.py --skip-install                       # skip uv sync / npm install
python run.py --backend-port 8000 --frontend-port 5174
python run.py --public                             # a public https link for any phone (needs cloudflared)
python run.py --warm-llm                           # load the local Ollama model before the demo
```

- **HTTPS by default.** The frontend is served over HTTPS with a self-signed local test certificate, because phones
  allow the camera, microphone and motion sensors (voice input, AR) only in a secure context.
- **Phones on the same Wi-Fi.** `run.py` prints the Wi-Fi address (for example `https://192.168.1.20:5173`) and a
  QR code in the terminal; it also saves the code as `railsaathi-qr.svg` in the repository root. Scan it with the
  phone's camera.
- **The certificate warning.** The phone (and your desktop browser) warns that the certificate is not trusted, since
  it is a local test certificate: tap *Advanced*, then *Proceed* (or *Visit this website*). Nothing loads on the
  phone? Allow Node.js through Windows Firewall on Private networks, set the Wi-Fi to a Private network, and avoid
  guest networks that isolate devices.
- **`--no-https`** serves plain HTTP. Everything works on the computer, but phones then block the camera,
  microphone and motion sensors.
- **`--skip-install`** skips `uv sync` and `npm install`, for a faster restart when the dependencies have not
  changed.
- **`--public`** builds the frontend once (`npx vite build`; `--skip-build` reuses `frontend/dist`), serves it with
  `vite preview` and opens a free Cloudflare quick tunnel, then prints a public `https://...trycloudflare.com` link
  and a QR code for it. Phones need no certificate warning, and camera, microphone and AR work. Install
  [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) first
  (`winget install Cloudflare.cloudflared` on Windows, `brew install cloudflared` on macOS). Anyone with the link can
  use the app while it runs, and the link changes every run. It implies `--no-https` (the tunnel supplies HTTPS),
  runs the backend without `--reload`, and sets `PUBLIC_TUNNEL=1` so rate limits count each visitor separately.
  Why `vite preview` and not the dev server: the production build is minified and split into chunks, so the first
  load over a mobile connection is much smaller, and a tunnel makes the dev server's many small module requests
  slow. (Chosen by design; the first load was not timed on Fast 3G, and the tunnel itself and phone behaviour have
  not been measured: cloudflared was not available when this was verified, so this is to be measured.)
- **`--warm-llm`** sends Ollama an empty prompt so the local model (`OLLAMA_MODEL`, default `gemma4:latest`) is
  loaded before the first visitor, and prints how long that took. It needs Ollama as `LLM_PROVIDER` or
  `LLM_FALLBACK`. With Ollama in use, `run.py` also warns when under 10 GB of RAM is free (try
  `OLLAMA_MODEL=llama3.2:3b`) or when more than one model is loaded. Measured 2026-10-18 on a 16 GB RAM, RTX 5060
  Laptop 8 GB machine with about 2.4 GB RAM free: loading gemma4 drove free RAM to about 0 GB (VRAM 1.5 to 4.7 GB), so
  close other apps first. Answer latency with gemma4 is not measured; see
  [STATION_NAVIGATION.md](docs/STATION_NAVIGATION.md).
- **Live NTES data.** `run.py` sets `RAILWAY_DATA_MODE=ntes` unless you set it yourself (see below).

Or start the two servers yourself:

```bash
# 1. Backend: http://localhost:8000, OpenAPI docs at /docs
cd backend
uv sync
cp .env.example .env          # optional; the defaults work without it
uv run python -m uvicorn app.main:create_app --factory --reload --port 8000

# 2. Frontend: http://localhost:5173, in a second terminal
cd frontend
npm install
npm run dev                   # proxies /api to BACKEND_URL (default http://127.0.0.1:8000)
```

Open http://localhost:5173 and try *"I need to reach Chennai before 9 AM tomorrow."* Camera, microphone and
motion sensors need a secure context: `localhost` works. For another device on your network, run
`VITE_HTTPS=1 npm run dev` (what `run.py` does; the dev server already listens on every network interface).

### What you see locally

- **Live NTES data through an unofficial client.** `python run.py` starts the backend with
  `RAILWAY_DATA_MODE=ntes` (unless you set the variable yourself, in the environment or `backend/.env`). Journeys,
  departure boards, schedules and running status then come from NTES through
  [`ntes-client`](https://pypi.org/project/ntes-client/), an unofficial client of the NTES app backend: not an
  authorised integration, and NTES can block it at any time. Every option and board is labelled LIVE (or CACHED,
  STALE) with the source "NTES (unofficial client)". NTES gives no fares, so options say "Fare: check on IRCTC".
  If NTES does not answer, you see "Data unavailable" with the reason, never invented trains. Details:
  [DATA_PROVIDERS.md](docs/DATA_PROVIDERS.md#ntes-specifics-the-unofficial-client).
- **Demo data, unlabelled in the UI.** With `RAILWAY_DATA_MODE=demo` (the backend's own default when started
  without `run.py`, and what the tests and Playwright use), trains, timings, fares, boards and disruptions come from
  the bundled demo dataset. The UI does not mark it as demo: there is no DEMO pill or "demo data" line. The API
  still reports `data_mode: demo`, and production refuses demo data (the backend serves no journeys and `/readyz`
  fails without a live provider), so this never reaches passengers.
- **Rule-based answers without Gemini.** With no Gemini configured, the planner uses the rule-based extractor and
  the ticketing assistant uses the rule-based agent. Profile says which one is active.
- **AR is visible but switched off.** Camera (AR) guidance needs the Gemini vision service (Gemini configured as
  below) and `AR_GUIDANCE_ENABLED` (unset means every AR station outside production). Without Gemini, Station
  Navigation shows the AR tab disabled at Chennai Central, with the reason: no Gemini vision service, or (in
  production) `AR_GUIDANCE_ENABLED` not naming the station. The 3D tour and the station
  blueprint work without it.
- **RailRadar is the alternative.** Set `RAILWAY_DATA_MODE=railradar` and `RAILRADAR_API_KEY` to use RailRadar
  instead of NTES.

Optional services, each off by default:

| Service | Setting | Guide |
|---|---|---|
| Gemini on Vertex AI | `LLM_PROVIDER=gemini` and `GOOGLE_CLOUD_PROJECT` | [DEPLOYMENT.md](docs/DEPLOYMENT.md) |
| Live trains from NTES (unofficial client) | `RAILWAY_DATA_MODE=ntes` (`run.py` sets it) | [DATA_PROVIDERS.md](docs/DATA_PROVIDERS.md#ntes-specifics-the-unofficial-client) |
| Live trains from RailRadar | `RAILWAY_DATA_MODE=railradar` and `RAILRADAR_API_KEY` | [RAILRADAR_SETUP.md](docs/RAILRADAR_SETUP.md) |
| Claude on Bedrock, intent extraction only | `LLM_PROVIDER=bedrock` | [BEDROCK_SETUP.md](docs/BEDROCK_SETUP.md) |
| Shared state | `REDIS_URL` (Redis 7 or later) | |

## Tests and gates

```bash
cd backend  && uv run ruff check . && uv run pytest --cov=app   # unit, API, docs-vs-code and infra-file checks
cd frontend && npm run lint && npm run typecheck
cd frontend && npm test                     # Vitest with v8 coverage (fails below 70 % of lines)
cd frontend && npm run build                # fails over a gzip bundle budget (scripts/check-budget.mjs)
cd frontend && npm run e2e                  # Playwright + axe on every mobile screen; starts both servers
cd frontend && npm run e2e:dist             # production build behind the nginx headers: CSP, service worker
k6 run -e BASE_URL=http://127.0.0.1:8000 loadtest/k6/smoke.js   # smoke; load.js is the 50-VU load test
```

CI (`.github/workflows/ci.yml`) runs all of the above except k6, plus three dependency gates:

- `pip-audit`;
- `npm audit --omit=dev --audit-level=high`;
- `scripts/audit-gate.mjs`.

`backend/tests/test_api_docs.py` fails when [docs/API.md](docs/API.md) and the served routes disagree.

## Documentation

| Page | What it covers |
|---|---|
| [API](docs/API.md) | Every endpoint, provenance, tokens, errors and limits ([requests.http](docs/requests.http)) |
| [Architecture](docs/ARCHITECTURE.md) | Modules, the planner state machine and ranking model, platform adapters |
| [Station navigation](docs/STATION_NAVIGATION.md) | The navigation screen as wired, stations, closures, tour, authoring |
| [AR guidance](docs/AR_GUIDANCE.md) | The AR model card and the production gate |
| [Delay model](docs/DELAY_MODEL.md) | The delay model card: MAE, data provenance, limits |
| [Data providers](docs/DATA_PROVIDERS.md) | Every data source and the interface to replace it |
| [Integration](docs/INTEGRATION.md) | Embedding the planner and consuming the handoff payload |
| [Limitations](docs/LIMITATIONS.md) | Capability status, honesty limits and future work |
| [Deployment](docs/DEPLOYMENT.md) | Google Cloud setup and the CI/CD workflow |
| [Runbook](docs/RUNBOOK.md) | Operations, alerts, load test, capacity, owner to-dos |
| [Security](docs/SECURITY.md) | Threat-model checklist, dependency audits, known risks |
| [RailRadar](docs/RAILRADAR_SETUP.md), [Bedrock](docs/BEDROCK_SETUP.md) | Provider setup |
| [Demo scenarios](docs/DEMO_SCENARIOS.md) | Scripted planner walkthroughs on demo data (development only) |

## Project layout

```
backend/
  app/
    api/          FastAPI routers, schemas, error envelope, middleware (rate limit, body size, observability)
    agent/        ticketing agent controller, tool fencing, output URL allowlist, conversation store
    audit/        audit events as structured logs (no message text)
    delay/        delay model loader/inference, features, observation collector
    disruption/   planner reassessment
    domain/       enums (incl. provenance modes), journey/option/state models, transitions
    harness/      planner workflow engine, merge, i18n, handoff
    intent/       IntentUpdate schema, rule-based extractor, Gemini and Bedrock adapters
    journey/      goal planner, plan store
    knowledge/    read-only SQLite knowledge base (built from seed_data.py at image build)
    llm/          ChatLLM adapter (Gemini, mock), Gemini vision localiser
    navigation/   station models, catalogue loader, routing engine, disruption store, coach position
    providers/    JourneyProvider / LiveSource, RailRadar client with shared quota and cache, demo data
    ranking/      constraint evaluation, scoring, explanations
    security/     signed session tokens, rate limiters
    sessions/     SessionStore protocol, Redis and in-memory stores
    stations/     place resolver for the planner
  data/           stations (schematic), delay CSV + model artifact, venues, national helplines
  scripts/        stations.py, train_delay_model.py, eval_localize.py, check_railradar.py, smoke.sh
frontend/
  src/mobile/     the mobile app: screens, strings (en + ta), router, planner context
  src/navigation/ route map and station-navigation hook
  src/ar/         camera guidance;  src/tour/ 3D tour;  src/api/ typed client
  nginx/          site config and security headers;  sw/ app-shell service worker
infra/            Cloud Scheduler job, Cloud Monitoring alert policies and log metric
loadtest/k6/      smoke and load scripts
docs/
```
