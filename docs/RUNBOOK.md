# Runbook

How to operate RailSaathi AI on Google Cloud Run. One-time setup is in [DEPLOYMENT.md](DEPLOYMENT.md). Commands
assume these shell variables:

```bash
PROJECT_ID=...  REGION=asia-south1  BACKEND=railsaathi-backend  FRONTEND=railsaathi-frontend
BACKEND_URL="$(gcloud run services describe $BACKEND --region $REGION --format 'value(status.url)')"
```

## The system at a glance

| Part | Where | Notes |
|---|---|---|
| Frontend | Cloud Run `railsaathi-frontend` (nginx) | Static PWA plus the `/api/*` proxy and the security headers. The public entry point |
| Backend | Cloud Run `railsaathi-backend` (FastAPI, one uvicorn worker per instance) | All APIs. Min 2 and max 10 instances, concurrency 40 |
| Shared state | Memorystore Redis `railsaathi` (**Redis 7.x required**) | Sessions, plans, chats, rate limits, NTES/RailRadar request budgets and caches, station closures. Every key has a TTL |
| LLM | Vertex AI Gemini (`GEMINI_MODEL`, `GOOGLE_CLOUD_LOCATION`) | Runtime service account, no API key |
| Live data | NTES through the unofficial `ntes-client` (`RAILWAY_DATA_MODE=ntes`, the default; no key), or RailRadar (secret `RAILRADAR_API_KEY`) | NTES: unofficial, can break or be blocked; 20 requests/minute (our own budget) shared. RailRadar: third party, 10 requests/minute shared |
| Files | Cloud Storage | Station catalogue (`STATIONS_URI`), delay model (`DELAY_MODEL_URI`), observations (`OBSERVATIONS_URI`) |
| Scheduled job | Cloud Scheduler `railsaathi-collect-observations` | `POST /internal/collect` with an OIDC token |
| Alerts | Cloud Monitoring (`infra/monitoring/`) | 5xx rate, p95 latency, Redis memory, RailRadar quota |

## Production configuration checklist

Check each item before calling a deployment production-ready. Each one is set in the deploy workflow's
repository variables or secrets.

- [ ] **A live data mode.** `RAILWAY_DATA_MODE=ntes` (the workflow default) needs no key, only the `ntes-client`
      package in the image (it is a locked dependency); remember it is an unofficial client that NTES can block.
      `RAILWAY_DATA_MODE=railradar` needs the `RAILRADAR_API_KEY` secret with a real key version. Production
      refuses demo data. Without a working mode, `/readyz` is 503, the candidate revision fails its smoke test and
      keeps no traffic.
- [ ] **`SESSION_SIGNING_KEY` secret.** The app refuses to start in production without it. Every replica must share
      it.
- [ ] **`REDIS_URL` pointing at Memorystore Redis 7 or later.** Station closures use `EXPIRE … NX`/`GT`, which Redis
      6 rejects. Without `REDIS_URL`, production `/readyz` is 503.
- [ ] **`STATIONS_URI=gs://<bucket>/stations`**, published with `scripts/stations.py publish`. When it is unset,
      production serves the station data baked into the image, which changes only on rebuild.
- [ ] **`INTERNAL_OIDC_AUDIENCE` and `INTERNAL_OIDC_SERVICE_ACCOUNT`, plus `OBSERVATIONS_URI`.** Without them,
      `/internal/*` answers 404: no observation collection and no stored closures.
  - Set up the Cloud Scheduler job from `infra/scheduler/collect-observations.yaml`.
  - Then **verify one real run end to end**. The ID-token check has only been tested with mocked Google keys. A
    401 means the audience differs from the job's `oidcToken.audience`. A 403 means the caller's service account
    differs.
- [ ] **`MAPS_BROWSER_KEY_SECRET` (optional).** Name the Secret Manager secret holding a referrer-restricted Maps
      JavaScript key. Without it, the tour links out to Google Maps.
- [ ] **`AR_GUIDANCE_ENABLED` stays unset in production** until `backend/scripts/eval_localize.py` passes the gate
      in [AR_GUIDANCE.md](AR_GUIDANCE.md). That needs at least 30 photos taken on site by the owner.
- [ ] The alert policies and the log-based metric are created, with a notification channel (see "Alerts").
- [ ] A staging load test has passed (see "Load test").
- [ ] **Must do before public launch: R1 closed or explicitly acknowledged.** Restrict the backend's ingress or IAM
      so only the frontend (GFE/nginx) path reaches it (`--ingress internal` with the frontend on Direct VPC
      egress, or `--no-allow-unauthenticated` with nginx sending an ID token). Until then a direct caller can spoof
      `X-Forwarded-For`, pick its rate-limit bucket and run up Gemini spend ([SECURITY.md](SECURITY.md), R1). If it
      stays open, record who accepted the risk and until when.
- [ ] **Must do before public launch: a billing budget alert and a Vertex AI quota cap.** Create a Cloud Billing
      budget with alert thresholds on the project, and lower the Vertex AI Gemini request quota (per minute, per
      region) to what max instances need, so a burst or abuse cannot run up an unbounded bill.
- [ ] **Recommended before public launch: a dedicated runtime service account per service** (only the secret,
      Vertex AI and bucket roles it needs), passed as `--service-account`, instead of the default compute account
      ([SECURITY.md](SECURITY.md), R8).

## Deploy and roll back

- **Deploy:** push to `main` (the deploy workflow starts only after CI passes for that push), or run the "Deploy
  to Cloud Run" workflow by hand. It:
  1. builds both images;
  2. deploys the backend with `--no-traffic --tag candidate`;
  3. runs `backend/scripts/smoke.sh` against the candidate's tag URL (health, `/readyz` ready, one planner turn, no
     `/data` exposure);
  4. moves backend traffic to the candidate (`update-traffic --to-latest`);
  5. does the same for the frontend: candidate deploy, proxy check on its tag URL, then traffic.

  A failed smoke test stops the workflow before traffic moves, so users stay on the previous revision. Delete or
  ignore the failed candidate revision; there is nothing to roll back. (The first deploy of a new service goes live
  directly: Cloud Run rejects `--no-traffic` on create.)
- **Roll back** the backend (or the frontend) to a previous revision:

  ```bash
  gcloud run revisions list --service $BACKEND --region $REGION
  gcloud run services update-traffic $BACKEND --region $REGION --to-revisions <revision>=100
  ```
- **Station data, delay model or Maps key changes** take effect on the next instance start. Deploy again, or force
  new instances with `gcloud run services update $BACKEND --region $REGION --update-labels restart=$(date +%s)`.

## Health

| Probe | Meaning |
|---|---|
| `GET /healthz` | Liveness, with no I/O. If it fails, the process is wedged |
| `GET /readyz` | 503 lists the failing `checks`: `redis` (unreachable, or unset in production), `data_provider` (production refused demo data, or the `ntes-client` package is missing in NTES mode), `station_catalogue`, `railradar_key` (production in RailRadar mode only), `delay_model` or `navigation_stations`. `degraded` lists non-blocking problems: `llm`, `knowledge`, `railradar`, `ntes` or `navigation_stations` (some stations failed validation) |
| `GET /api/health` | The full status: data provider (requested, active, reason), LLM and vision status, Redis ping, model mode. No secrets |

## Logs

Logs are JSON lines in Cloud Logging. Every request writes one `request` line with `method`, `path`, `status`,
`latency_ms` and `request_id`. Passenger message text is never logged; there is no setting that enables it.

```
resource.labels.service_name="railsaathi-backend" AND jsonPayload.request_id="<id from X-Request-Id>"
resource.labels.service_name="railsaathi-backend" AND jsonPayload.status>=500
resource.labels.service_name="railsaathi-backend" AND severity>=ERROR
jsonPayload.event="railradar_quota_exhausted"
resource.labels.service_name="railsaathi-backend" AND jsonPayload.message="localize"   # AR fixes: status, node, confidence, latency
```

## Alerts

Create them once per project. Create the log-based metric first, because the quota alert reads it:

```bash
gcloud logging metrics create railradar_quota_exhausted \
  --config-from-file=infra/monitoring/log-metric-railradar-quota-exhausted.yaml
CHANNEL="$(gcloud beta monitoring channels create --display-name='RailSaathi on-call' --type=email \
  --channel-labels=email_address=<you@example.org> --format='value(name)')"
for f in infra/monitoring/alert-*.yaml; do
  gcloud alpha monitoring policies create --policy-from-file="$f" --notification-channels="$CHANNEL"
done
```

`backend/tests/test_infra_monitoring.py` checks the files' schema in CI. If you rename the backend service, update
the service name in the filters.

### Alert: 5xx rate

The backend answers 5xx on purpose only with 503 for documented unavailable states. Any other 5xx is a fault.

1. Run the 5xx log query above, then group by `path`.
2. A burst right after a deploy means you should roll back (see above).
3. 503 `session_busy` means one session is getting concurrent requests (a client retry loop), or a turn outlived
   its session lock and its save was refused. 503 `storage_unavailable` (from planner sessions, goal plans, chats
   or the internal closure routes) means Redis is unreachable: check `/readyz` and the Memorystore instance. Rate
   limiting fails open while Redis is down; sessions do not.
4. 500 `internal_error`: find the matching `exception` field through the request id.

### Alert: p95 latency

1. Find which paths are slow: `jsonPayload.latency_ms > 3000`.
2. Planner `/messages`, `/api/chat` and `/api/journey/*` are LLM-bound. Check `/api/health` `llm`, and Vertex AI
   quotas and errors. Each turn is capped at `LLM_OVERALL_DEADLINE_SECONDS` (20 s), after which the planner falls
   back to rules and ticketing answers `unavailable`.
3. Slow routes everywhere mean CPU saturation or Redis latency. Check instance count against max instances, and
   CPU utilisation. Raise `BACKEND_MAX_INSTANCES` or lower concurrency (see "Capacity").

### Alert: Redis memory

Every key has a TTL, so steady growth means more traffic or a TTL regression.

1. Sample key prefixes from a VM on the VPC: `redis-cli -h <host> -a <auth> --scan --pattern 'rs:*' | cut -d: -f2 | sort | uniq -c`.
2. Scale up with `gcloud redis instances update railsaathi --region $REGION --size=<GB>`.
3. Lower `SESSION_TTL_MINUTES` or `RAILRADAR_STALE_SECONDS` if one prefix dominates.

### NTES stops answering

NTES is reached through an unofficial client, so it can stop working without notice (a changed app backend, a
block, or an outage). Symptoms: every board, schedule and journey is `unavailable` ("The live data provider could
not be reached" or "...returned data in a format RailSaathi does not understand"), and log lines
`NTES call failed (unavailable|bad_response|timeout, ...)`.

1. Run `cd backend && uv run python scripts/ntes_smoke.py` from a workstation. If it fails there too, NTES is down
   or blocks the client; if the record keys it prints changed, update `providers/ntes_mapper.py`.
2. Check for a newer `ntes-client` release; pin it with `uv add ntes-client==<version>` after `pip-audit` passes.
3. To switch source, set the `RAILWAY_DATA_MODE` repository variable to `railradar` (with the `RAILRADAR_API_KEY`
   secret) and redeploy. Never switch production to `demo`: it is refused.

Refused calls log `jsonPayload.event="ntes_quota_exhausted"`. A sustained count means RailSaathi's own budget
(`NTES_REQUESTS_PER_MINUTE`, 20) is too small for the traffic; raise it with care (NTES publishes no limit, so stay
polite) or lengthen `NTES_CACHE_SECONDS`.

### Alert: RailRadar quota exhausted

A few refusals at peaks are normal: boards and searches fall back to `stale` (labelled) or `unavailable`.

1. A sustained count means users mostly get stale or unavailable live data.
2. Check `served_stale` in the log lines. Mostly `false` means requests for uncached routes.
3. Options, in order:
   - raise the key's RailRadar plan (then set `RAILRADAR_REQUESTS_PER_MINUTE`);
   - lengthen `RAILRADAR_CACHE_SECONDS`;
   - lower `LIVE_BOARD_NEIGHBOURS` and `LIVE_BOARD_STATUS_LIMIT` (fewer calls per board).

## Load test

Never load-test production. Production shares the RailRadar quota and Gemini spend with real users.

1. **Deploy a staging backend** (a separate service on demo data, with its own Redis database, raised rate limits
   and no RailRadar or Gemini spend). Every k6 virtual user shares the load generator's IP, so without raised
   limits the run measures the rate limiter.

   ```bash
   IMAGE="$(gcloud run services describe $BACKEND --region $REGION --format 'value(spec.template.spec.containers[0].image)')"
   gcloud run deploy railsaathi-backend-staging --image "$IMAGE" --region $REGION --allow-unauthenticated \
     --cpu 1 --memory 512Mi --min-instances 2 --max-instances 10 --concurrency 40 --timeout 60 \
     --network default --subnet default --vpc-egress private-ranges-only \
     --set-env-vars "APP_ENV=staging,RAILWAY_DATA_MODE=demo,LLM_PROVIDER=none,RATE_LIMIT_PER_MINUTE=100000,RATE_LIMIT_LLM_PER_MINUTE=100000,REDIS_KEY_PREFIX=rs-staging" \
     --set-secrets "REDIS_URL=REDIS_URL:latest,SESSION_SIGNING_KEY=SESSION_SIGNING_KEY:latest"
   ```

   Staging with more than one instance needs the shared `SESSION_SIGNING_KEY` secret (mounted above): without it
   every instance signs with its own random key, so a token issued by one instance is rejected (401) by the next.
   `REDIS_KEY_PREFIX` keeps staging keys apart from production keys on the shared instance. A separate Memorystore
   instance or database is cleaner if you have one. Use `LLM_PROVIDER=gemini` with `GOOGLE_CLOUD_PROJECT` to
   include Gemini latency, which costs Vertex AI usage.
2. **Smoke, then load:**

   ```bash
   STAGING="$(gcloud run services describe railsaathi-backend-staging --region $REGION --format 'value(status.url)')"
   k6 run -e BASE_URL="$STAGING" loadtest/k6/smoke.js
   k6 run -e BASE_URL="$STAGING" loadtest/k6/load.js        # 50 VUs: 1 min ramp, 5 min hold, 30 s down
   # no local k6:  docker run --rm -i -v "$PWD/loadtest/k6:/scripts" grafana/k6:1.3.0 run -e BASE_URL="$STAGING" /scripts/load.js
   ```

   `load.js` fails (exit 99) when any threshold breaks:
   - 5xx rate of 1 % or more;
   - 429 rate of 1 % or more;
   - checks below 99 %;
   - p95 of 1.5 s or more on ordinary routes;
   - p95 of 15 s or more on LLM routes.

   Use `-e LLM=0` to skip planner and ticketing turns, and `-e VUS=` / `-e HOLD=` to change the shape.
3. **Watch** the staging service's Cloud Run metrics during the hold: instance count, CPU, request latency and
   container concurrency.
4. **Delete** staging afterwards: `gcloud run services delete railsaathi-backend-staging --region $REGION`.

**What has run so far:**

- Both scripts ran in `grafana/k6:1.3.0` against a **local** backend (demo data, rule-based extractor, raised
  limits):
  - smoke: 42/42 checks;
  - load: 50 VUs for 2.5 min, 6,721 requests, 0 % 5xx, 0 % 429, p95 4.8 ms.
- That validates the scripts and the code paths, not Cloud Run capacity. The staging run and the 24-hour soak in
  the plan are still to do.

## Capacity

The current settings are in `.github/workflows/deploy.yml`. The rationale sits next to the flags.

- **Backend: concurrency 40, 1 vCPU, 512 MiB, min 2, max 10.**
  - Handlers are async. Blocking work (Redis, SQLite, model inference, LLM calls) runs in anyio's worker pool,
    which has 40 threads, so 40 concurrent requests per instance never queue for a thread.
  - Most requests take milliseconds. A planner or ticketing turn can hold a thread for up to 20 s, so a burst of
    LLM turns is what fills an instance.
  - Min 2 keeps a warm spare (startup loads the delay model and the station catalogue) and survives the loss of
    one instance.
  - Max 10 bounds Redis connections and Gemini spend.
- **Frontend: concurrency 80, 256 MiB, min 0, max 3.** nginx only serves static files and proxies.
- **Shared IPs (CGNAT):** per-IP limits (60/min, 20/min on LLM routes, 120 AR fixes per 10 min) apply to the
  client IP nginx sees. Mobile carriers in India put many users behind one carrier-grade NAT address, and offices or
  campuses share one too, so a busy shared IP can hit the per-IP limit while each user is well under it. Watch 429s
  by IP after launch and raise the limits (`RATE_LIMIT_PER_MINUTE`, `RATE_LIMIT_LLM_PER_MINUTE`,
  `LOCALIZE_IP_RATE_LIMIT`) rather than assuming abuse; the per-session limits still bound each session.
- **Tuning after a staging run:**
  - If p95 on ordinary routes rises with concurrency while CPU stays below 60 %, requests are waiting on threads
    or Redis. Lower concurrency to 20 to 30, or raise the thread limit (`anyio.to_thread` default limiter).
  - If CPU stays above 80 % with p95 rising, raise max instances.
  - If cold starts show up as latency spikes after idle periods, raise min instances.

## Routine tasks

- **Rotate `SESSION_SIGNING_KEY`:** add a new secret version, then deploy. Every existing session and chat token
  becomes invalid (users start over). No other data is affected.
- **Rotate the RailRadar key:** add a secret version, then deploy. The cache is keyed by a fingerprint of the key,
  so it starts cold.
- **Publish station data:**

  ```bash
  uv run python scripts/stations.py validate
  uv run python scripts/stations.py publish <station> --dest gs://<bucket>/stations
  ```

  Rebuild the catalogue with `uv run python scripts/stations.py catalogue` if needed. Then restart the instances.
  A station that fails validation is skipped and shows as `degraded: navigation_stations`.
- **Add or clear a station closure.** Use the internal endpoints with an ID token from the configured service
  account:

  ```bash
  TOKEN="$(gcloud auth print-identity-token --impersonate-service-account=<INTERNAL_OIDC_SERVICE_ACCOUNT> \
    --audiences="<INTERNAL_OIDC_AUDIENCE>" --include-email)"
  curl -fsS -X POST "$BACKEND_URL/internal/stations/chennai_central/disruptions" -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Type: application/json' \
    -d '{"target_type":"edge","target_id":"edge_001","reason":"Escalator under repair","source":"station control room","ttl_seconds":7200}'
  curl -fsS -X DELETE "$BACKEND_URL/internal/stations/chennai_central/disruptions" -H "Authorization: Bearer $TOKEN"
  ```
- **Retrain the delay model:** run `uv run python scripts/train_delay_model.py`, review `metrics.json`, then commit
  the artifact or upload it and set `DELAY_MODEL_URI`. Update [DELAY_MODEL.md](DELAY_MODEL.md).
- **Enable AR at a station:**
  1. Collect at least 30 photos on site.
  2. Run `uv run python scripts/eval_localize.py --manifest <labelled photos manifest>`, with Gemini configured
     (see [AR_GUIDANCE.md](AR_GUIDANCE.md) for the manifest format).
  3. Only if the gate passes, set `AR_GUIDANCE_ENABLED=chennai_central` and deploy.
- **Street View panoramas:** run `GOOGLE_MAPS_API_KEY=<server key> uv run python scripts/stations.py panoramas chennai_central`
  and add the reviewed pano ids to the station data. Then test the tour under the production CSP with the browser
  key mounted.

## Owner to-dos (not done in code)

- [ ] Native Tamil review of `frontend/src/mobile/strings.ts`, including the station-name spellings.
- [ ] AR photo collection and evaluation (gate above).
- [ ] Street View panoramas, and a Street View check under the CSP.
- [ ] Trace or survey the Egmore, Bengaluru and Hyderabad layouts. Verify step-free pathways on site.
- [ ] Verify the Cloud Scheduler OIDC collector end to end.
- [ ] Staging load test, 24-hour soak with no alerts, then tag `v1.0.0`.
- [x] Legacy `#/classic` view removed (an old link opens home).
- [ ] Consider licensed or real photos instead of the decorative AI-generated route images.
- [ ] Restrict direct access to the backend URL ([SECURITY.md](SECURITY.md), open risk R1).
- [ ] Give each service a dedicated, least-privilege runtime service account (SECURITY.md, open risk R8).
