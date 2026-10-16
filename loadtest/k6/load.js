// Load test: 50 virtual users on a weighted mix of the app's journeys, against a STAGING revision.
//   k6 run -e BASE_URL=https://<staging-url> loadtest/k6/load.js
//   k6 run -e BASE_URL=... -e LLM=0 loadtest/k6/load.js        # skip planner/ticketing turns (no Gemini spend)
//   k6 run -e BASE_URL=... -e VUS=10 -e HOLD=1m loadtest/k6/load.js
// Docker (no local k6): docker run --rm -i -v "$PWD/loadtest/k6:/scripts" grafana/k6 run -e BASE_URL=... /scripts/load.js
//
// Before running (docs/RUNBOOK.md, "Load test"): every VU shares the load generator's IP, so deploy the staging
// revision with RATE_LIMIT_PER_MINUTE and RATE_LIMIT_LLM_PER_MINUTE raised (e.g. 100000), or the run measures the
// rate limiter instead of the service. Never point this at production. In live mode the departure board spends the
// shared RailRadar quota (10 requests/minute); once it is spent boards are served stale or labelled unavailable,
// counted in `live_board_unavailable`, which is expected and not a failure.
import { sleep } from 'k6'
import { appStart, delayEstimate, departures, plannerTurn, stationRoute, ticketingTurn } from './lib.js'

const VUS = Number(__ENV.VUS || 50)
const HOLD = __ENV.HOLD || '5m'
const LLM = __ENV.LLM !== '0'

export const options = {
  scenarios: {
    passengers: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '1m', target: VUS },
        { duration: HOLD, target: VUS },
        { duration: '30s', target: 0 },
      ],
      gracefulRampDown: '30s',
    },
  },
  thresholds: {
    // Release criteria for the staging run; they mirror the production alert policies in infra/monitoring/.
    server_errors: ['rate<0.01'],
    rate_limited: ['rate<0.01'],
    checks: ['rate>0.99'],
    'http_req_duration{kind:std}': ['p(95)<1500'],
    'http_req_duration{kind:llm}': ['p(95)<15000'],
  },
}

// Weighted journey mix (percent). LLM=0 moves the LLM share onto station navigation.
const MIX = [
  [25, appStart],
  [LLM ? 30 : 45, stationRoute],
  [20, delayEstimate],
  [5, departures],
  [LLM ? 15 : 0, plannerTurn],
  [LLM ? 5 : 0, ticketingTurn],
]
const TOTAL = MIX.reduce((sum, [weight]) => sum + weight, 0)

export default function () {
  let pick = Math.random() * TOTAL
  for (const [weight, journey] of MIX) {
    pick -= weight
    if (pick < 0) {
      journey(__ITER)
      break
    }
  }
  sleep(1 + Math.random() * 2) // think time between screens
}
