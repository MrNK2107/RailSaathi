// Centralised typed API client. All backend calls go through here.
import type {
  ErrorEnvelope,
  HealthResponse,
  JourneyPatch,
  Language,
  PlannerResponse,
  ReferenceData,
} from './types'

// Same origin by default: in dev the Vite proxy forwards /api to the backend, in production nginx does.
const DEFAULT_BASE = ''
const TIMEOUT_MS = 20_000
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
}

class NetworkFailure extends Error {}
class TimedOut extends Error {}

export function createApiClient(options: ApiClientOptions = {}) {
  const baseUrl = (options.baseUrl ?? import.meta.env.VITE_API_BASE_URL ?? DEFAULT_BASE).replace(/\/$/, '')
  const fetchImpl = options.fetchImpl ?? fetch.bind(globalThis)
  const retries = Math.max(0, Math.min(options.retries ?? MAX_RETRIES, MAX_RETRIES))
  const retryDelayMs = options.retryDelayMs ?? 400
  const timeoutMs = options.timeoutMs ?? TIMEOUT_MS
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
    const timer = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, timeoutMs)
    const onAbort = () => controller.abort()
    if (call.signal?.aborted) controller.abort()
    call.signal?.addEventListener('abort', onAbort)
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
    } finally {
      clearTimeout(timer)
      call.signal?.removeEventListener('abort', onAbort)
    }
    const data: unknown = await res.json().catch(() => null)
    if (!res.ok) throw errorFromResponse(res.status, data, res.headers.get(REQUEST_ID_HEADER) ?? requestId)
    return data as T
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
        { body: { language }, idempotent: true, signal: o?.signal })
      sessionToken = res.session_token ?? null
      return res
    },
    getSession: (id: string, o?: O) => request<PlannerResponse>('GET', s(id), { signal: o?.signal }),
    sendMessage: (id: string, message: string, language: Language, o?: O) =>
      request<PlannerResponse>('POST', `${s(id)}/messages`, { body: { message, language }, signal: o?.signal }),
    patchJourney: (id: string, patch: JourneyPatch, o?: O) =>
      request<PlannerResponse>('PATCH', `${s(id)}/journey`, { body: patch, signal: o?.signal }),
    recommendations: (id: string, o?: O) =>
      request<PlannerResponse>('POST', `${s(id)}/recommendations`, { idempotent: true, signal: o?.signal }),
    select: (id: string, optionId: string, o?: O) =>
      request<PlannerResponse>('POST', `${s(id)}/select`, { body: { option_id: optionId }, idempotent: true, signal: o?.signal }),
    confirm: (id: string, optionId: string | null, o?: O) =>
      request<PlannerResponse>('POST', `${s(id)}/confirm`, { body: { option_id: optionId }, idempotent: true, signal: o?.signal }),
    reassess: (id: string, eventId: string | null, o?: O) =>
      request<PlannerResponse>('POST', `${s(id)}/reassess`, { body: { event_id: eventId }, signal: o?.signal }),
    cancel: (id: string, o?: O) =>
      request<PlannerResponse>('POST', `${s(id)}/cancel`, { idempotent: true, signal: o?.signal }),
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
