// Shared request helpers for the k6 scripts (smoke.js, load.js). Every request is tagged with `kind`:
//   std  ordinary API routes (rate-limit tier RATE_LIMIT_PER_MINUTE)
//   llm  routes that can reach an LLM (tier RATE_LIMIT_LLM_PER_MINUTE): planner messages and ticketing chat
// and with `name`, so latency can be read per endpoint without one series per URL.
import http from 'k6/http'
import { check } from 'k6'
import { Counter, Rate } from 'k6/metrics'

export const BASE_URL = (__ENV.BASE_URL || 'http://127.0.0.1:8010').replace(/\/+$/, '')

// 5xx answers. The backend never answers 5xx on purpose except 503 readiness/unavailable states, so this is the
// release signal (the alert policy on 5xx rate watches the same thing in production).
export const serverErrors = new Rate('server_errors')
// 429 answers. Every VU shares the load generator's IP, so a staging revision has to run with raised
// RATE_LIMIT_PER_MINUTE / RATE_LIMIT_LLM_PER_MINUTE (docs/RUNBOOK.md); a high rate here means it was not.
export const rateLimited = new Rate('rate_limited')
export const quotaUnavailable = new Counter('live_board_unavailable')

// k6's http_req_failed counts transport failures and any status outside 200-399; 5xx and 429 are also split out
// by the rates above, because they mean different things (a server fault vs. an unraised staging rate limit).
http.setResponseCallback(http.expectedStatuses({ min: 200, max: 399 }))

const JSON_HEADERS = { 'Content-Type': 'application/json', Accept: 'application/json' }

function record(res) {
  serverErrors.add(res.status >= 500)
  rateLimited.add(res.status === 429)
  return res
}

function params(name, kind, token) {
  const headers = { ...JSON_HEADERS }
  if (token) headers['X-Session-Token'] = token
  return { headers, tags: { name, kind }, timeout: kind === 'llm' ? '60s' : '20s' }
}

export function get(path, name, kind = 'std', token) {
  return record(http.get(`${BASE_URL}${path}`, params(name, kind, token)))
}

export function post(path, body, name, kind = 'std', token) {
  return record(http.post(`${BASE_URL}${path}`, JSON.stringify(body), params(name, kind, token)))
}

function json(res) {
  try {
    return res.json()
  } catch (_) {
    return null
  }
}

export const ROUTE_STATION = __ENV.ROUTE_STATION || 'chennai_central'
const ROUTES = [
  ['ent_wall_tax', 'platform_9'],
  ['ent_suburban', 'ticketing'],
  ['ent_parking', 'toilet_east'],
  ['platform_12', 'info_desk'],
]
const TRAINS = ['12623', '12671', '12007', '16127', '12639']

// ---- journeys a user makes ---------------------------------------------------------------------------------------

/** App start: health, client config and the station list, as the mobile app does on load. */
export function appStart() {
  const res = [get('/api/health', 'GET /api/health'), get('/api/client-config', 'GET /api/client-config'),
    get('/api/stations', 'GET /api/stations')]
  check(res[0], { 'health 200': (r) => r.status === 200 })
  check(res[1], { 'client-config has features': (r) => r.status === 200 && !!(json(r) || {}).features })
  check(res[2], { 'station list non-empty': (r) => r.status === 200 && (json(r) || []).length > 0 })
}

/** Station navigation: details, info and one route at the traced station. */
export function stationRoute(iteration) {
  const [source, destination] = ROUTES[iteration % ROUTES.length]
  check(get(`/api/stations/${ROUTE_STATION}`, 'GET /api/stations/{id}'), { 'station 200': (r) => r.status === 200 })
  check(get(`/api/stations/${ROUTE_STATION}/info`, 'GET /api/stations/{id}/info'), { 'info 200': (r) => r.status === 200 })
  check(get(`/api/disruptions/${ROUTE_STATION}`, 'GET /api/disruptions/{id}'),
    { 'disruptions 200 or 503': (r) => r.status === 200 || r.status === 503 })
  const route = post('/api/navigation/route', { station_id: ROUTE_STATION, source, destination },
    'POST /api/navigation/route')
  check(route, { 'route ok': (r) => r.status === 200 && (json(r) || {}).status === 'ok' })
}

/** Delay estimate (CPU-bound model inference in the worker pool). */
export function delayEstimate(iteration) {
  const train = TRAINS[iteration % TRAINS.length]
  const res = get(`/api/predict/delay?train_number=${train}&destination=MAS`, 'GET /api/predict/delay')
  check(res, { 'delay estimate has provenance': (r) => r.status === 200 && !!(json(r) || {}).provenance })
}

/** Departure board. Spends the shared RailRadar quota in live mode; an exhausted quota is a labelled
 * `unavailable`/`stale` board, never a 5xx. */
export function departures() {
  const res = get('/api/live/stations/MAS/departures?hours=2', 'GET /api/live/stations/{code}/departures')
  const body = json(res) || {}
  if (body.provenance && body.provenance.mode === 'unavailable') quotaUnavailable.add(1)
  check(res, { 'board answered with provenance': (r) => r.status === 200 && !!body.provenance })
}

/** Conversational planner: create a session and send one message (rule-based or Gemini extraction). */
export function plannerTurn() {
  const created = post('/api/planner/sessions', { language: 'en' }, 'POST /api/planner/sessions')
  const session = json(created) || {}
  if (!check(created, { 'session created': (r) => r.status === 201 && !!session.session_token })) return
  const reply = post(`/api/planner/sessions/${session.session_id}/messages`,
    { message: 'I need to reach Chennai before 9 AM tomorrow from Coimbatore, 2 passengers', language: 'en' },
    'POST /api/planner/sessions/{id}/messages', 'llm', session.session_token)
  check(reply, { 'planner replied': (r) => r.status === 200 && !!(json(r) || {}).assistant_message })
}

/** Ticketing guidance: one chat turn (Gemini when configured, otherwise the rule-based agent). */
export function ticketingTurn() {
  const res = post('/api/chat', { message: 'What is the Tatkal booking window for AC classes?' }, 'POST /api/chat', 'llm')
  check(res, { 'chat answered with provenance': (r) => r.status === 200 && !!(json(r) || {}).provenance })
}
