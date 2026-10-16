# RailSaathi AI

An Indian Railways passenger assistant: a mobile-first progressive web app in English and Tamil, with a FastAPI
backend on Google Cloud Run. It plans journeys from what a passenger says, answers ticketing questions with
citations, shows departure boards and delay estimates, and guides passengers through a station.

**It never books a ticket.** Every railway, station, model or AI answer is labelled with its provenance: `live`,
`cached`, `stale`, `unavailable`, `demo` or `fallback`. Schematic, estimated, demo or cached data is never
presented as verified or live. The capability-by-capability limits are in
[docs/LIMITATIONS.md](docs/LIMITATIONS.md).

## The six capabilities

| # | Capability | What it really does | Code |
|---|---|---|---|
| 1 | **Conversational journey planner** | Free text or speech (English, Tamil, common Tanglish) becomes validated journey details, with one question at a time. Options are ranked against hard and soft constraints and explained from computed values. Disruptions trigger a re-plan that the passenger must confirm. The result is a confirmed handoff payload | `backend/app/{intent,harness,ranking,disruption}/` |
| 2 | **Goal planner** | "Reach my meeting by 11:00": trains that arrive with a buffer, from the same journey data | `backend/app/journey/` |
| 3 | **Ticketing guidance agent** | Gemini (or a rule-based agent) answers from a small knowledge base of official IRCTC and Indian Railways pages and cites them. Tool output is fenced and links are allowlisted. AI guidance, not official | `backend/app/{agent,knowledge,llm}/` |
| 4 | **Live station information** | Departure boards, schedules and running status from RailRadar (a third-party service, not official). One shared quota and cache across replicas. Stale or unavailable states are shown as such | `backend/app/providers/` |
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
                                                                      │  RailRadar quota + cache, station closures (all with TTLs)
                                                                      ├─ Vertex AI Gemini: intent extraction, ticketing agent, AR vision
                                                                      ├─ RailRadar API: live train data (third party)
                                                                      └─ Cloud Storage: station catalogue, delay model, observations
```

Requests are same-origin, so the browser needs no CORS. The backend exposes no static files. Details:
[ARCHITECTURE](docs/ARCHITECTURE.md), [DEPLOYMENT](docs/DEPLOYMENT.md), [RUNBOOK](docs/RUNBOOK.md) and
[SECURITY](docs/SECURITY.md).

## Quick start (Windows, macOS, Linux)

Prerequisites: Python 3.12, [uv](https://docs.astral.sh/uv/) and Node.js 20+. No cloud account or API key is
needed. Locally the app runs on labelled demo data, the rule-based extractor and the rule-based ticketing agent.

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
`VITE_HTTPS=1 npm run dev`.

Optional services, each off by default:

| Service | Setting | Guide |
|---|---|---|
| Gemini on Vertex AI | `LLM_PROVIDER=gemini` and `GOOGLE_CLOUD_PROJECT` | [DEPLOYMENT.md](docs/DEPLOYMENT.md) |
| Live trains | `RAILWAY_DATA_MODE=railradar` and `RAILRADAR_API_KEY` | [RAILRADAR_SETUP.md](docs/RAILRADAR_SETUP.md) |
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
