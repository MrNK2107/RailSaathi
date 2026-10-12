# Deployment (Google Cloud Run)

Two containers, both on Cloud Run:

| Service | Image | What it does |
|---|---|---|
| `railsaathi-backend` | `backend/Dockerfile` | FastAPI app, one uvicorn worker, port from `PORT` |
| `railsaathi-frontend` | `frontend/Dockerfile` | nginx serving the Vite build and reverse-proxying `/api/*` (and the legacy `/stations`, `/trains`, `/plan`, `/predict` aliases) to the backend, so the browser talks to one origin |

`.github/workflows/deploy.yml` builds, pushes and deploys both on every push to `main`, then runs
`backend/scripts/smoke.sh` and a frontend proxy check. The workflow is skipped until the
`GCP_PROJECT_ID` repository variable exists.

## Phase 1 constraints

- Planner sessions are still held in process, so the backend runs with **max instances 1**.
  Phase 2 moves sessions, rate limits and the RailRadar quota to Redis and lifts this cap.
- Demo data mode (`RAILWAY_DATA_MODE=demo`) and no LLM (`LLM_PROVIDER=none`) are the defaults.
  Set the `RAILWAY_DATA_MODE=railradar` repository variable and the `RAILRADAR_API_KEY` secret
  for live train data.
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
  iamcredentials.googleapis.com secretmanager.googleapis.com

# Image repository
gcloud artifacts repositories create railsaathi --repository-format=docker --location="$REGION"

# Secrets referenced by the backend service (create even if empty so the deploy does not fail)
printf '' | gcloud secrets create RAILRADAR_API_KEY --data-file=-
# later: printf 'real-key' | gcloud secrets versions add RAILRADAR_API_KEY --data-file=-

# Deploy service account used by GitHub Actions
gcloud iam service-accounts create github-deployer --display-name "GitHub Actions deployer"
SA="github-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
for ROLE in roles/run.admin roles/artifactregistry.writer roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$SA" --role "$ROLE"
done

# Let the Cloud Run runtime service account read the secret
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format 'value(projectNumber)')"
gcloud secrets add-iam-policy-binding RAILRADAR_API_KEY \
  --member "serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role roles/secretmanager.secretAccessor

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
