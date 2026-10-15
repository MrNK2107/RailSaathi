# Deployment (Google Cloud Run)

Two containers, both on Cloud Run:

| Service | Image | What it does |
|---|---|---|
| `railsaathi-backend` | `backend/Dockerfile` | FastAPI app, one uvicorn worker, port from `PORT` |
| `railsaathi-frontend` | `frontend/Dockerfile` | nginx serving the Vite build and reverse-proxying `/api/*` to the backend, so the browser talks to one origin |

`.github/workflows/deploy.yml` builds, pushes and deploys both on every push to `main`, then runs
`backend/scripts/smoke.sh` and a frontend proxy check. The workflow is skipped until the
`GCP_PROJECT_ID` repository variable exists.

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
    `provenance.mode: "unavailable"`. Rule-based answers carry `provenance.mode: "fallback"`, Gemini answers `live`.
  - agent conversations live in Redis (`rs:conv:<session>:<conversation_id>`, TTL `SESSION_TTL_MINUTES`, at most
    `MAX_HISTORY_MESSAGES` messages) and are bound to the caller's signed `X-Session-Token`.
  `LLM_OVERALL_DEADLINE_SECONDS` (default 20) bounds the LLM work of a planner or agent turn (calls, retries and
  backoff); the session lock TTL (`SESSION_LOCK_TTL_MS`, default 45 s) is validated to outlive it. Other work in a
  turn (RailRadar searches) has its own timeouts. The browser's planner timeout (45 s) and the Cloud Run request
  timeout (60 s) sit above that budget; `backend/tests/test_timeout_budget.py` keeps them consistent.
- Demo data mode (`RAILWAY_DATA_MODE=demo`) is the default. Set the `RAILWAY_DATA_MODE=railradar` repository
  variable and the `RAILRADAR_API_KEY` secret for live train data.
- The ticketing knowledge base (`data/knowledge/railsaathi.db`) is not committed: the Dockerfile builds it from
  `app/knowledge/seed_data.py` (`python -m app.knowledge.ingest`) and the service opens it read-only. Outside
  production a missing or stale file is rebuilt at startup.
- The backend data directory is **not** served. The only station assets exposed are
  `GET /api/stations/{id}/map` and `GET /api/stations/{id}/info`.

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

# Secrets referenced by the backend service (RAILRADAR_API_KEY may be empty so the deploy does not fail)
printf '' | gcloud secrets create RAILRADAR_API_KEY --data-file=-
# later: printf 'real-key' | gcloud secrets versions add RAILRADAR_API_KEY --data-file=-
printf 'redis://:%s@%s:%s/0' "$REDIS_AUTH" "$REDIS_HOST" "$REDIS_PORT" | gcloud secrets create REDIS_URL --data-file=-
openssl rand -base64 48 | tr -d '\n' | gcloud secrets create SESSION_SIGNING_KEY --data-file=-

# Deploy service account used by GitHub Actions (networkUser lets it attach the service to the VPC subnet)
gcloud iam service-accounts create github-deployer --display-name "GitHub Actions deployer"
SA="github-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
for ROLE in roles/run.admin roles/artifactregistry.writer roles/iam.serviceAccountUser roles/compute.networkUser; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$SA" --role "$ROLE"
done

# Cloud Run runtime service account: read the secrets and call Gemini on Vertex AI
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format 'value(projectNumber)')"
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
for SECRET in RAILRADAR_API_KEY REDIS_URL SESSION_SIGNING_KEY; do
  gcloud secrets add-iam-policy-binding "$SECRET" \
    --member "serviceAccount:${RUNTIME_SA}" --role roles/secretmanager.secretAccessor
done
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member "serviceAccount:${RUNTIME_SA}" --role roles/aiplatform.user

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
| `RAILWAY_DATA_MODE` | `demo` (default) or `railradar` |
| `FRONTEND_ORIGIN` | optional; leave empty, the nginx proxy makes API calls same-origin |
| `LLM_PROVIDER` | `gemini` (default), `bedrock` (intent extraction only) or `none` |
| `GOOGLE_CLOUD_LOCATION` | Vertex AI region for Gemini, default `us-central1` |
| `VPC_NETWORK` / `VPC_SUBNET` | network and subnet (in `GCP_REGION`) used for Direct VPC egress to Memorystore; default `default` / `default` |
| `BACKEND_MIN_INSTANCES` / `BACKEND_MAX_INSTANCES` | backend scaling bounds, default `2` / `10` |

Push to `main` or run the workflow manually. The job prints both service URLs at the end.

## Local verification of the images

```bash
docker build -t railsaathi-backend ./backend
docker run --rm -d -p 8081:8080 --name rs-backend railsaathi-backend
sh backend/scripts/smoke.sh http://127.0.0.1:8081

docker build -t railsaathi-frontend ./frontend
docker run --rm -d -p 8082:8080 -e BACKEND_URL=http://host.docker.internal:8081 --name rs-frontend railsaathi-frontend
curl -fsS http://127.0.0.1:8082/api/health
```

## Operations notes

- Logs: Cloud Logging, filter `resource.labels.service_name="railsaathi-backend"`. Access lines are
  JSON with `request_id`; pass `X-Request-Id` from a client to correlate.
- Rollback: `gcloud run services update-traffic railsaathi-backend --to-revisions <rev>=100 --region $REGION`.
- Health: `GET /api/health` on the backend, `GET /healthz` on the frontend container.
