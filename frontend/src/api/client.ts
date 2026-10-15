// Centralised typed API client. All backend calls go through here.
import type {
  ClientConfig,
  DelayPrediction,
  DepartureBoard,
  ErrorEnvelope,
  GoalPlanRequest,
  GoalPlanResponse,
  GoalRefineRequest,
  HealthResponse,
  JourneyPatch,
  Language,
  PlannerResponse,
  RakePosition,
  ReferenceData,
  RouteRequestBody,
  RouteResult,
  StationDetails,
  StationInfo,
  StationSummary,
  StationTour,
  TicketingRequest,
  TicketingResponse,
} from './types'

// Same origin by default: in dev the Vite proxy forwards /api to the backend, in production nginx does.
const DEFAULT_BASE = ''
/** Plain reads (health, reference data). */
export const READ_TIMEOUT_MS = 20_000
/**
 * Planner session calls: a turn may wait for the session lock (SESSION_LOCK_WAIT_SECONDS, 10 s), spend the whole
 * LLM budget (LLM_OVERALL_DEADLINE_SECONDS, 20 s; a slow LLM then degrades to rules and still returns 200) and run
 * the journey search. 45 s covers that with margin and stays under the Cloud Run request timeout (60 s in
 * .github/workflows/deploy.yml). backend/tests/test_timeout_budget.py checks these values stay consistent.
 */
export const PLANNER_TIMEOUT_MS = 45_000
const MAX_RETRIES = 2
export const REQUEST_ID_HEADER = 'X-Request-Id'
export const SESSION_TOKEN_HEADER = 'X-Session-Token'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details: Record<string, unknown> = {},
    /** Correlates with backend logs (`request_id`). */
    public readonly requestId: string | null = null,
  ) {
    super(message)
    this.name = 'ApiError'
  }

  get isSessionGone(): boolean {
    return this.code === 'session_not_found' || this.code === 'session_expired'
  }

  get isAborted(): boolean {
    return this.code === 'aborted'
  }
}

/** Turns any response body into an ApiError; understands the backend `{error, request_id}` envelope. */
export function errorFromResponse(status: number, body: unknown, fallbackRequestId: string | null = null): ApiError {
  const envelope = isEnvelope(body) ? body : null
  const e = envelope?.error
  return new ApiError(
    status,
    typeof e?.code === 'string' && e.code ? e.code : 'http_error',
    typeof e?.message === 'string' && e.message ? e.message : `Request failed (${status})`,
    e?.details && typeof e.details === 'object' ? e.details : {},
    envelope?.request_id ?? fallbackRequestId,
  )
}

function isEnvelope(body: unknown): body is ErrorEnvelope {
  return !!body && typeof body === 'object' && 'error' in body && !!(body as ErrorEnvelope).error
    && typeof (body as ErrorEnvelope).error === 'object'
}

export function newRequestId(): string {
  const c = globalThis.crypto
  if (c && typeof c.randomUUID === 'function') return c.randomUUID()
  return Array.from({ length: 16 }, () => Math.floor(Math.random() * 16).toString(16)).join('')
}

type FetchLike = typeof fetch

export interface ApiClientOptions {
  baseUrl?: string
  fetchImpl?: FetchLike
  /** Retries for network failures only (never HTTP errors or timeouts); capped at 2. */
  retries?: number
  retryDelayMs?: number
  /** Overrides both READ_TIMEOUT_MS and PLANNER_TIMEOUT_MS (tests). */
  timeoutMs?: number
  requestId?: () => string
}

export interface RequestOptions {
  /** Cancels the request (and any pending retry). Rejects with ApiError code `aborted`. */
  signal?: AbortSignal
}

interface Call {
  body?: unknown
  /** Only idempotent calls are retried, so a lost response never duplicates a state change. */
  idempotent?: boolean
  signal?: AbortSignal
  /** Planner session call (may include lock wait + LLM turn): uses PLANNER_TIMEOUT_MS. */
  planner?: boolean
}

class NetworkFailure extends Error {}
class TimedOut extends Error {}

export function createApiClient(options: ApiClientOptions = {}) {
  const baseUrl = (options.baseUrl ?? import.meta.env.VITE_API_BASE_URL ?? DEFAULT_BASE).replace(/\/$/, '')
  const fetchImpl = options.fetchImpl ?? fetch.bind(globalThis)
  const retries = Math.max(0, Math.min(options.retries ?? MAX_RETRIES, MAX_RETRIES))
  const retryDelayMs = options.retryDelayMs ?? 400
  const makeRequestId = options.requestId ?? newRequestId
  // Signed token issued by session creation; sent on every call so session routes and rate limits can verify it.
  let sessionToken: string | null = null

  async function request<T>(method: string, path: string, call: Call = {}): Promise<T> {
    const idempotent = call.idempotent ?? method === 'GET'
    const maxAttempts = idempotent ? retries + 1 : 1
    const requestId = makeRequestId() // one id per logical call, kept across retries
    for (let attempt = 1; ; attempt += 1) {
      try {
        return await once<T>(method, path, call, requestId)
      } catch (err) {
        if (err instanceof ApiError) throw err // HTTP errors are never retried
        if (call.signal?.aborted) throw aborted(requestId)
        if (err instanceof TimedOut) {
          throw new ApiError(0, 'timeout', 'The planner service took too long to respond.', {}, requestId)
        }
        if (!(err instanceof NetworkFailure) || attempt >= maxAttempts) throw networkError(requestId)
        await sleep(retryDelayMs * 2 ** (attempt - 1), call.signal).catch(() => {
          throw aborted(requestId)
        })
      }
    }
  }

  async function once<T>(method: string, path: string, call: Call, requestId: string): Promise<T> {
    const controller = new AbortController()
    let timedOut = false
    const timeoutMs = options.timeoutMs ?? (call.planner ? PLANNER_TIMEOUT_MS : READ_TIMEOUT_MS)
    const timer = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, timeoutMs)
    const onAbort = () => controller.abort()
    if (call.signal?.aborted) controller.abort()
    call.signal?.addEventListener('abort', onAbort)
    try {
      let res: Response
      try {
        res = await fetchImpl(`${baseUrl}${path}`, {
        method,
          headers: {
            [REQUEST_ID_HEADER]: requestId,
            ...(call.body === undefined ? {} : { 'Content-Type': 'application/json' }),
            ...(sessionToken ? { [SESSION_TOKEN_HEADER]: sessionToken } : {}),
          },
          body: call.body === undefined ? undefined : JSON.stringify(call.body),
          signal: controller.signal,
        })
      } catch {
        if (timedOut) throw new TimedOut()
        throw new NetworkFailure() // fetch rejects (TypeError) only when no HTTP response arrived
      }
      // The timeout and the caller's signal stay armed while the body is read, so a stalled body cannot hang.
      const data: unknown = await res.json().catch(() => null)
      if (controller.signal.aborted) {
        if (timedOut) throw new TimedOut()
        throw new NetworkFailure() // caller abort: request() reports it as `aborted`
      }
      if (!res.ok) throw errorFromResponse(res.status, data, res.headers.get(REQUEST_ID_HEADER) ?? requestId)
      return data as T
    } finally {
      clearTimeout(timer)
      call.signal?.removeEventListener('abort', onAbort)
    }
  }

  const s = (id: string) => `/api/planner/sessions/${encodeURIComponent(id)}`
  type O = RequestOptions | undefined

  return {
    baseUrl,
    setSessionToken: (token: string | null) => {
      sessionToken = token
    },
    health: (o?: O) => request<HealthResponse>('GET', '/api/health', { signal: o?.signal }),
    reference: (o?: O) => request<ReferenceData>('GET', '/api/planner/reference', { signal: o?.signal }),
    createSession: async (language: Language, o?: O) => {
      const res = await request<PlannerResponse>('POST', '/api/planner/sessions',
        { body: { language }, idempotent: true, signal: o?.signal, planner: true })
      sessionToken = res.session_token ?? null
      return res
    },
    getSession: (id: string, o?: O) => request<PlannerResponse>('GET', s(id), { signal: o?.signal, planner: true }),
    sendMessage: (id: string, message: string, language: Language, o?: O) =>
      request<PlannerResponse>('POST', `${s(id)}/messages`, { body: { message, language }, signal: o?.signal, planner: true }),
    patchJourney: (id: string, patch: JourneyPatch, o?: O) =>
      request<PlannerResponse>('PATCH', `${s(id)}/journey`, { body: patch, signal: o?.signal, planner: true }),
    recommendations: (id: string, o?: O) =>
      request<PlannerResponse>('POST', `${s(id)}/recommendations`, { idempotent: true, signal: o?.signal, planner: true }),
    select: (id: string, optionId: string, o?: O) =>
      request<PlannerResponse>('POST', `${s(id)}/select`, { body: { option_id: optionId }, idempotent: true, signal: o?.signal, planner: true }),
    confirm: (id: string, optionId: string | null, o?: O) =>
      request<PlannerResponse>('POST', `${s(id)}/confirm`, { body: { option_id: optionId }, idempotent: true, signal: o?.signal, planner: true }),
    reassess: (id: string, eventId: string | null, o?: O) =>
      request<PlannerResponse>('POST', `${s(id)}/reassess`, { body: { event_id: eventId }, signal: o?.signal, planner: true }),
    cancel: (id: string, o?: O) =>
      request<PlannerResponse>('POST', `${s(id)}/cancel`, { idempotent: true, signal: o?.signal, planner: true }),
    // Goal planner: needs the session token from createSession(); plan ids are bound to that session.
    planGoal: (body: GoalPlanRequest, o?: O) =>
      request<GoalPlanResponse>('POST', '/api/journey/plan', { body, signal: o?.signal, planner: true }),
    refineGoal: (body: GoalRefineRequest, o?: O) =>
      request<GoalPlanResponse>('POST', '/api/journey/refine', { body, signal: o?.signal, planner: true }),
    // Ticketing guidance chat (LLM turn, so the planner timeout applies). Not retried: a turn is not idempotent.
    ticketing: (body: TicketingRequest, o?: O) =>
      request<TicketingResponse>('POST', '/api/chat', { body, signal: o?.signal, planner: true }),
    // Live departure board for a catalogue station; `provenance.mode` may be `unavailable` (with `reason`).
    departures: (stationCode: string, o?: O) =>
      request<DepartureBoard>('GET', `/api/live/stations/${encodeURIComponent(stationCode)}/departures`, { signal: o?.signal }),
    predictDelay: (trainNumber: string, stationCode: string, o?: O) =>
      request<DelayPrediction>('GET',
        `/api/predict/delay?train_number=${encodeURIComponent(trainNumber)}&destination=${encodeURIComponent(stationCode)}`,
        { signal: o?.signal }),
    // Station navigation (read-only). `route` rejects with ApiError code `routing_unavailable` for untraced stations.
    stations: (o?: O) => request<StationSummary[]>('GET', '/api/stations', { signal: o?.signal }),
    station: (id: string, o?: O) =>
      request<StationDetails>('GET', `/api/stations/${encodeURIComponent(id)}`, { signal: o?.signal }),
    stationInfo: (id: string, o?: O) =>
      request<StationInfo>('GET', `/api/stations/${encodeURIComponent(id)}/info`, { signal: o?.signal }),
    /** Everything the virtual tour draws: levels, traced areas, the graph in metres and panoramas. */
    stationTour: (id: string, o?: O) =>
      request<StationTour>('GET', `/api/stations/${encodeURIComponent(id)}/tour`, { signal: o?.signal }),
    /** Start-up config: the public Maps browser key (or null) and per-station feature flags. */
    clientConfig: (o?: O) => request<ClientConfig>('GET', '/api/client-config', { signal: o?.signal }),
    stationRoute: (body: RouteRequestBody, o?: O) =>
      request<RouteResult>('POST', '/api/navigation/route', { body, idempotent: true, signal: o?.signal }),
    rakePosition: (composition: string, targetCoach: string, o?: O) =>
      request<RakePosition>('GET',
        `/api/trains/rake-position?coach_composition=${encodeURIComponent(composition)}&target_coach=${encodeURIComponent(targetCoach)}`,
        { signal: o?.signal }),
    goalPlan: (planId: string, o?: O) =>
      request<GoalPlanResponse>('GET', `/api/journey/options/${encodeURIComponent(planId)}`, { signal: o?.signal, planner: true }),
  }
}

function aborted(requestId: string): ApiError {
  return new ApiError(0, 'aborted', 'The request was cancelled.', {}, requestId)
}

function networkError(requestId: string): ApiError {
  return new ApiError(0, 'network_error', 'Cannot reach the planner service. Check that the backend is running.', {}, requestId)
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new Error('aborted'))
    const onAbort = () => {
      clearTimeout(timer)
      reject(new Error('aborted'))
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

export type ApiClient = ReturnType<typeof createApiClient>
export const api = createApiClient()
