# Deployment (Google Cloud Run)

Two containers, both on Cloud Run:

| Service | Image | What it does |
|---|---|---|
| `railsaathi-backend` | `backend/Dockerfile` | FastAPI app, one uvicorn worker, port from `PORT` |
| `railsaathi-frontend` | `frontend/Dockerfile` | nginx serving the Vite build and reverse-proxying `/api/*` to the backend, so the browser talks to one origin |

`.github/workflows/deploy.yml` runs only after the CI workflow has **passed** for a push to `main` (`workflow_run`,
conclusion `success`), or when started by hand (`workflow_dispatch`); it never runs in parallel with CI. It builds
and pushes both images, then for each service:

1. deploys a new revision with `--no-traffic --tag candidate`, so users keep the previous revision;
2. smoke-tests the candidate's tag URL (`backend/scripts/smoke.sh`: `/readyz` must say `ready`, one planner turn,
   no `/data` exposure; for the frontend, the proxy check);
3. only then moves all traffic to it (`gcloud run services update-traffic --to-latest`).

A failed smoke test therefore leaves traffic on the old revision. The very first deploy of a service cannot use
`--no-traffic` (Cloud Run rejects it on create), so it goes live directly; there is nothing to protect yet. The
workflow is skipped until the `GCP_PROJECT_ID` repository variable exists.

## Runtime topology

- Planner sessions, rate-limit counters and the RailRadar quota and cache live in **Memorystore for Redis**
  (`REDIS_URL`), so the backend runs on several instances (default **min 2, max 10**; override with the
  `BACKEND_MIN_INSTANCES` / `BACKEND_MAX_INSTANCES` repository variables). Cloud Run reaches the private
  Memorystore IP through **Direct VPC egress** (`--network/--subnet`, `--vpc-egress private-ranges-only`);
  a Serverless VPC Access connector (`--vpc-connector`) works too if you already have one.
- Every replica signs and verifies session tokens with the same `SESSION_SIGNING_KEY` (required in production;
  the app refuses to start without it).
- Gemini runs on **Vertex AI** with the Cloud Run runtime service account (`LLM_PROVIDER=gemini`,
  `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`); no API key. LLM problems never produce a 500:
  - planner intent extraction falls back to the rule-based extractor on any LLM failure or timeout;
  - the ticketing agent uses the rule-based agent only when Gemini is **not configured**; if a configured Gemini
    fails or times out mid-turn (or the turn deadline passes), `/api/chat` returns 200 with
    `status: "unavailable"`, `message: "guidance unavailable"`, official IRCTC / Indian Railways `links` and
    `provenance.mode: "unavailable"`. Rule-based answers carry `provenance.mode: "fallback"`; Gemini answers carry
    `cached` (they are generated over the curated knowledge base, so `as_of` is the oldest cited source's date).
  - agent conversations live in Redis (`rs:conv:<session>:<conversation_id>`, TTL `SESSION_TTL_MINUTES`, at most
    `MAX_HISTORY_MESSAGES` messages) and are bound to the caller's signed `X-Session-Token`.
  `LLM_OVERALL_DEADLINE_SECONDS` (default 20) bounds the LLM work of a planner or agent turn (calls, retries and
  backoff), and `RAILRADAR_CALL_BUDGET_SECONDS` (default 15) bounds each batch of RailRadar calls a turn makes (a
  search, or the live-status lookup on reassessment). The session lock TTL (`SESSION_LOCK_TTL_MS`, default 45 s)
  is validated at startup to cover the worst turn (LLM deadline plus one search, or two RailRadar batches) plus a
  10 s margin. If a turn still outlives its lock, its save is refused (fenced on the lock token, 503
  `session_busy`), so it can never overwrite a newer turn's state. The browser's planner timeout (45 s) and the
  Cloud Run request timeout (60 s) sit above that budget; `backend/tests/test_timeout_budget.py` keeps them
  consistent.
- **Production needs a live data mode.** The workflow deploys with `APP_ENV=production`, and production refuses
  demo data. `RAILWAY_DATA_MODE` defaults to `ntes`: NTES through `ntes-client`, an unofficial client of the NTES
  app backend (the owner's choice; it needs no key, and it can break or be blocked, see SECURITY.md R10). Set the
  repository variable to `railradar` to use RailRadar instead; then the `RAILRADAR_API_KEY` secret must hold a real
  key (it is mounted only in that mode). Otherwise live searches and boards answer `unavailable`, `/readyz` is 503
  (`railradar_key` in RailRadar mode, or `data_provider` when demo mode was refused or the NTES package is
  missing) and the candidate's smoke test fails, so it never gets traffic. Demo data is for development and
  staging (`APP_ENV` other than `production`).
- **Production needs Redis.** `/readyz` is 503 (`redis`) in production when `REDIS_URL` is unset or Memorystore is
  unreachable: sessions, rate limits and the RailRadar quota must be shared by every replica.
- **Memorystore must run Redis 7 or later.** The station-closure store uses `EXPIRE … NX`/`GT`, which Redis 6
  rejects. The setup below creates `redis_7_2`.
- The ticketing knowledge base (`data/knowledge/railsaathi.db`) is not committed: the Dockerfile builds it from
  `app/knowledge/seed_data.py` (`python -m app.knowledge.ingest`) and the service opens it read-only. Outside
  production a missing or stale file is rebuilt at startup.
- The backend data directory is **not** served. Station assets are exposed only through the allowlisted routes
  `GET /api/stations/{id}`, `/map`, `/info` and `/tour`.
- **Station catalogue:** set the `STATIONS_URI` repository variable to `gs://<bucket>/stations`, published with
  `scripts/stations.py publish` (grant the runtime service account `roles/storage.objectViewer` on the bucket).
  When it is unset, the service reads the stations baked into the image. Navigation details:
  [STATION_NAVIGATION.md](STATION_NAVIGATION.md).
- **AR guidance** is off in production while `AR_GUIDANCE_ENABLED` is unset. Set that repository variable only
  after the evaluation gate in [AR_GUIDANCE.md](AR_GUIDANCE.md) passes.

## Delay model and observation collection

- The delay estimate (`GET /api/predict/delay`) is served by a scikit-learn `HistGradientBoostingRegressor`
  artifact. `backend/data/ml/model/model.joblib` (about 0.4 MB) and its `metrics.json` are committed and baked into
  the image; `DELAY_MODEL_URI` can instead point at `gs://bucket/path/model.joblib` (read once at startup with the
  runtime service account, needs `roles/storage.objectViewer`). Artifacts are pickles: only load files your own
  pipeline wrote. Produce a new one manually with `cd backend && uv run python scripts/train_delay_model.py`
  (optionally `--observations <dir of collected JSONL>`), review `metrics.json`, then commit it or upload it and set
  `DELAY_MODEL_URI`. Retraining is never automatic.
- If the artifact is missing or unreadable the service keeps running in `history_only` mode (recorded historical
  averages, no probability, no accuracy claim) and `/readyz` reports not ready, so the candidate revision fails its
  smoke test and never receives traffic. Set `DELAY_HISTORY_ONLY=true` to run in that mode on purpose; `/readyz` then passes and
  reports `delay_model.mode`.
- `POST /internal/collect` samples the live running status of trains users looked at in the last day
  (`OBSERVATION_SEEN_TTL_SECONDS`, at most `OBSERVATION_MAX_TRAINS` per run, through the shared RailRadar quota)
  and writes one JSONL object per run to `OBSERVATIONS_URI` (`gs://bucket/prefix`; a local directory in
  development). Only fresh `live` answers that state a delay are written. It is disabled (404) unless
  `INTERNAL_OIDC_AUDIENCE` and `INTERNAL_OIDC_SERVICE_ACCOUNT` are set; callers must present a Google ID token for
  that audience from that service account (issuer, audience, expiry, signature and email are verified), otherwise
  401 or 403. The Cloud Scheduler job is defined in `infra/scheduler/collect-observations.yaml` (grant its service
  account `roles/run.invoker`, the backend's runtime account `roles/storage.objectCreator` on the bucket, and
  create the backend service with authentication required for the Scheduler call, or keep it public: the endpoint
  rejects unauthenticated callers itself).

## One-time project setup

Run once, as a project owner, with `gcloud` installed locally. Replace the placeholders.

```bash
export PROJECT_ID=your-project-id
export REGION=asia-south1              # Mumbai; pick the region closest to your users
export GITHUB_REPO=MrNK2107/gdg-devfest

gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  iamcredentials.googleapis.com secretmanager.googleapis.com \
  redis.googleapis.com compute.googleapis.com aiplatform.googleapis.com

# Image repository
gcloud artifacts repositories create railsaathi --repository-format=docker --location="$REGION"

# Memorystore for Redis on the VPC the backend egresses to (here the "default" network; its regional
# subnet "default" must be in $REGION). AUTH is on; traffic stays on the private VPC.
gcloud redis instances create railsaathi --region="$REGION" --tier=standard --size=1 \
  --redis-version=redis_7_2 --network=default --enable-auth
REDIS_HOST="$(gcloud redis instances describe railsaathi --region="$REGION" --format 'value(host)')"
REDIS_PORT="$(gcloud redis instances describe railsaathi --region="$REGION" --format 'value(port)')"
REDIS_AUTH="$(gcloud redis instances get-auth-string railsaathi --region="$REGION" --format 'value(authString)')"

# Secrets referenced by the backend service. RAILRADAR_API_KEY is needed only for RAILWAY_DATA_MODE=railradar (the
# default, ntes, needs no key; skip these four lines then). It is created without a version (Secret Manager rejects
# an empty payload); add the real key as its first version BEFORE the first RailRadar deploy, because the deploy
# then mounts RAILRADAR_API_KEY:latest and fails while the secret has no version.
gcloud secrets create RAILRADAR_API_KEY --replication-policy=automatic
read -rsp 'RailRadar API key: ' RAILRADAR_KEY; echo   # typed, not echoed or kept in shell history
printf '%s' "$RAILRADAR_KEY" | gcloud secrets versions add RAILRADAR_API_KEY --data-file=-
unset RAILRADAR_KEY
printf 'redis://:%s@%s:%s/0' "$REDIS_AUTH" "$REDIS_HOST" "$REDIS_PORT" | gcloud secrets create REDIS_URL --data-file=-
openssl rand -base64 48 | tr -d '\n' | gcloud secrets create SESSION_SIGNING_KEY --data-file=-

# Deploy service account used by GitHub Actions (networkUser lets it attach the service to the VPC subnet)
gcloud iam service-accounts create github-deployer --display-name "GitHub Actions deployer"
SA="github-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
for ROLE in roles/run.admin roles/artifactregistry.writer roles/iam.serviceAccountUser roles/compute.networkUser; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$SA" --role "$ROLE"
done

# Cloud Run runtime service account: read the secrets and call Gemini on Vertex AI. This uses the project's default
# compute service account, which often holds roles/editor. Before a public launch, create a dedicated runtime
# service account per service with only these roles and pass it as --service-account in deploy.yml (SECURITY.md R8).
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format 'value(projectNumber)')"
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
for SECRET in REDIS_URL SESSION_SIGNING_KEY; do   # add RAILRADAR_API_KEY in RailRadar mode
  gcloud secrets add-iam-policy-binding "$SECRET" \
    --member "serviceAccount:${RUNTIME_SA}" --role roles/secretmanager.secretAccessor
done
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member "serviceAccount:${RUNTIME_SA}" --role roles/aiplatform.user

# Optional: the public Maps JavaScript key for the virtual tour's Street View, restricted to the frontend's HTTP
# referrer and to the Maps JavaScript API (GET /api/client-config sends it to browsers). Skip this and the tour
# links out to Google Maps; deploys work either way. After creating it, set the MAPS_BROWSER_KEY_SECRET repository
# variable to GOOGLE_MAPS_BROWSER_KEY so the deploy mounts it.
printf 'browser-key' | gcloud secrets create GOOGLE_MAPS_BROWSER_KEY --data-file=-
gcloud secrets add-iam-policy-binding GOOGLE_MAPS_BROWSER_KEY \
  --member "serviceAccount:${RUNTIME_SA}" --role roles/secretmanager.secretAccessor

# Workload Identity Federation (keyless auth from GitHub Actions)
gcloud iam workload-identity-pools create github --location global --display-name "GitHub"
gcloud iam workload-identity-pools providers create-oidc github \
  --location global --workload-identity-pool github \
  --issuer-uri "https://token.actions.githubusercontent.com" \
  --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition "assertion.repository == '${GITHUB_REPO}'"
gcloud iam service-accounts add-iam-policy-binding "$SA" \
  --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/attribute.repository/${GITHUB_REPO}"

echo "GCP_WIF_PROVIDER=projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/providers/github"
echo "GCP_SERVICE_ACCOUNT=$SA"
```

Then add these **repository variables** in GitHub (Settings, Secrets and variables, Actions, Variables):

| Variable | Value |
|---|---|
| `GCP_PROJECT_ID` | your project id |
| `GCP_REGION` | e.g. `asia-south1` |
| `GCP_WIF_PROVIDER` | printed by the script above |
| `GCP_SERVICE_ACCOUNT` | printed by the script above |
| `RAILWAY_DATA_MODE` | `ntes` (default: NTES through the unofficial ntes-client, no key) or `railradar` (needs the `RAILRADAR_API_KEY` secret); production refuses `demo` |
| `FRONTEND_ORIGIN` | optional; leave empty, the nginx proxy makes API calls same-origin |
| `LLM_PROVIDER` | `gemini` (default), `bedrock` (intent extraction only) or `none` |
| `GOOGLE_CLOUD_LOCATION` | Vertex AI region for Gemini, default `us-central1` |
| `VPC_NETWORK` / `VPC_SUBNET` | network and subnet (in `GCP_REGION`) used for Direct VPC egress to Memorystore; default `default` / `default` |
| `BACKEND_MIN_INSTANCES` / `BACKEND_MAX_INSTANCES` | backend scaling bounds, default `2` / `10` |
| `MAPS_BROWSER_KEY_SECRET` | optional; name of the Secret Manager secret holding the Maps browser key (e.g. `GOOGLE_MAPS_BROWSER_KEY`). Unset: no key is mounted and the tour links out to Google Maps |
| `STATIONS_URI` | `gs://<bucket>/stations` for production; unset uses the stations in the image |
| `DELAY_MODEL_URI` | optional `gs://<bucket>/<path>/model.joblib`; unset uses the committed artifact in the image |
| `OBSERVATIONS_URI`, `INTERNAL_OIDC_AUDIENCE`, `INTERNAL_OIDC_SERVICE_ACCOUNT` | the observation collector and the internal closure endpoints (see above); unset means `/internal/*` answers 404 |
| `AR_GUIDANCE_ENABLED` | leave unset (AR off) until the AR evaluation gate passes; then a station id or a comma-separated list, e.g. `chennai_central` (the workflow passes env vars with gcloud's `^@^` delimiter, so commas survive) |

Optional variables are passed to the service only when they are set, so an empty variable never overrides an
application default.

Push to `main` (the deploy starts once CI passes) or run the workflow manually. The job prints both service URLs
at the end.

## Local verification of the images

```bash
docker build -t railsaathi-backend ./backend
docker run --rm -d -p 8081:8080 --name rs-backend railsaathi-backend
sh backend/scripts/smoke.sh http://127.0.0.1:8081

docker build -t railsaathi-frontend ./frontend
docker run --rm -d -p 8082:8080 -e BACKEND_URL=http://host.docker.internal:8081 --name rs-frontend railsaathi-frontend
curl -fsS http://127.0.0.1:8082/api/health
```

## Operations

Day-two operations are in [RUNBOOK.md](RUNBOOK.md): the production checklist, health and logs, the Cloud
Monitoring alerts (`infra/monitoring/`), rollback, the staging load test (`loadtest/k6/`), capacity tuning and
routine tasks. The threat-model checklist and its open risks are in [SECURITY.md](SECURITY.md).
