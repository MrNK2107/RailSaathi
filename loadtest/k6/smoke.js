// Smoke test: one virtual user walks every main journey a few times. Run after a deploy or before load.js.
//   k6 run -e BASE_URL=https://<staging-backend-or-frontend-url> loadtest/k6/smoke.js
// Docker (no local k6): docker run --rm -i -v "$PWD/loadtest/k6:/scripts" grafana/k6 run -e BASE_URL=... /scripts/smoke.js
// Fails (exit 99) when any threshold below is crossed.
import { check, group } from 'k6'
import { appStart, delayEstimate, departures, get, plannerTurn, stationRoute, ticketingTurn } from './lib.js'

export const options = {
  vus: 1,
  iterations: 3,
  thresholds: {
    checks: ['rate==1'],
    server_errors: ['rate==0'],
    rate_limited: ['rate==0'],
    'http_req_duration{kind:std}': ['p(95)<2000'],
    'http_req_duration{kind:llm}': ['p(95)<20000'],
  },
}

export default function () {
  group('probes', () => {
    check(get('/healthz', 'GET /healthz'), { 'healthz 200': (r) => r.status === 200 })
    check(get('/readyz', 'GET /readyz'), { 'readyz 200': (r) => r.status === 200 })
  })
  group('app start', appStart)
  group('station navigation', () => stationRoute(__ITER))
  group('delay estimate', () => delayEstimate(__ITER))
  group('departure board', departures)
  group('planner turn', plannerTurn)
  group('ticketing turn', ticketingTurn)
}
