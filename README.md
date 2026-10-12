# RailSaathi AI — Smart Passenger Planner

A standalone, runnable module that turns a passenger's natural-language request
(English, Tamil or Tanglish, typed or spoken) into a validated journey plan, ranks
options against what the passenger actually needs, explains each choice,
re-plans on (simulated) disruptions, and hands a confirmed plan to the main
RailSaathi AI application.

> **Prototype using DEMO data.** All trains (numbered `D###`), timings, fares,
> station facilities and disruptions are simulated. There is **no** live Indian
> Railways / NTES integration, and **no ticket is ever booked**.

## The five innovations, and where they live

| Innovation | What it does | Code |
|---|---|---|
| 1. Intent-to-Journey Compiler | Free text → structured constraints; asks one focused question at a time; handles corrections | `backend/app/intent/`, `backend/app/harness/` |
| 2. Multi-Objective Planner | Hard constraints filter, weighted utility ranks, explanations come from computed values | `backend/app/ranking/` |
| 3. Passenger-Need-Aware Planning | Assistance, wheelchair, children, elderly, etc., each verified, not supported or unknown | `backend/app/ranking/evaluate.py` |
| 4. Disruption Reassessment | Simulated delay/cancellation → re-rank → passenger must confirm a replacement | `backend/app/disruption/` |
| 5. Voice and Conversation | Tamil/English UI, browser speech input (transcript reviewed before sending), read-aloud | `frontend/src/` |

## Quick start (Windows, macOS, Linux)

Prerequisites: Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js 20+.

```bash
# 1. Backend (http://localhost:8000, docs at /docs)
cd backend
uv sync
cp .env.example .env          # optional; defaults work without it
uv run python -m uvicorn app.main:create_app --factory --reload --port 8000

# 2. Frontend (http://localhost:5173), in a second terminal
cd frontend
npm install
cp .env.example .env          # optional; API calls are same-origin via the Vite proxy
npm run dev
```

Open http://localhost:5173 and try: *"I need to reach Chennai before 9 AM tomorrow."*

No AWS account, API key or railway API is needed. Without Bedrock the app uses
its deterministic rule-based extractor.

## Tests

```bash
cd backend  && uv run pytest --cov=app        # unit + API tests (Bedrock mocked)
cd frontend && npm test                       # Vitest component and client tests
cd frontend && npm run typecheck && npm run build
cd frontend && npm run e2e                    # Playwright with local Chrome; starts both servers if needed
```

## Optional: live train data (RailRadar)

Set `RAILWAY_DATA_MODE=railradar` and `RAILRADAR_API_KEY` in `backend/.env`, then run
`uv run python scripts/check_railradar.py`. See [docs/RAILRADAR_SETUP.md](docs/RAILRADAR_SETUP.md).
`RAILWAY_DATA_MODE=demo` (default) uses labelled demo data; live mode never falls back to demo journeys.

## Optional: Claude on AWS Bedrock

See [docs/BEDROCK_SETUP.md](docs/BEDROCK_SETUP.md). In short: configure AWS
credentials (`aws configure` or `aws configure sso`), set `LLM_PROVIDER=bedrock`,
`AWS_REGION` and `BEDROCK_MODEL_ID` in `backend/.env`, then run
`uv run python scripts/check_bedrock.py`. If Bedrock fails, the planner falls
back to the rule-based extractor automatically.

## Documentation

- [Architecture](docs/ARCHITECTURE.md): modules, workflow state machine, ranking model
- [API contract](docs/API.md): endpoints, examples, error codes, session lifecycle ([requests.http](docs/requests.http))
- [Bedrock setup](docs/BEDROCK_SETUP.md): credentials, model ID, verification, troubleshooting
- [RailRadar live data](docs/RAILRADAR_SETUP.md): key setup, mapping check, failure handling
- [Data-provider guide](docs/DATA_PROVIDERS.md): connecting an authorised railway data source
- [Integration handoff](docs/INTEGRATION.md): how the main app embeds this module and consumes the result
- [Demo scenarios](docs/DEMO_SCENARIOS.md): scripted walkthroughs A–G
- [Limitations and future work](docs/LIMITATIONS.md)
- [Deployment to Google Cloud Run](docs/DEPLOYMENT.md): containers, one-time project setup, CI/CD workflow

## Project layout

```
backend/
  app/
    api/          FastAPI routes, request/response schemas, middleware
    audit/        audit event log (no message text)
    disruption/   reassessment service
    domain/       enums, journey/options/state models, transition table
    harness/      workflow engine, planner service, merge, i18n, handoff
    intent/       IntentUpdate schema, rule-based extractor, LLM interface, Bedrock adapter
    providers/    JourneyProvider/DisruptionSource interfaces + demo JSON data
    ranking/      constraint evaluation, scoring, explanations, recommender
    sessions/     session store interface + in-memory TTL store
    stations/     station/city resolver
    validation/   deterministic parsing and validation
    config.py  clock.py  container.py  main.py
  scripts/check_bedrock.py
  tests/
frontend/
  src/api/        typed client + types
  src/components/ UI panels
  src/hooks/      usePlanner, speech hooks
  src/i18n/       English and Tamil strings
  src/test/       Vitest tests
  e2e/            Playwright tests
docs/
```
