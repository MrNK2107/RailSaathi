// Centralised typed API client. All backend calls go through here.
import type {
  HealthResponse,
  JourneyPatch,
  Language,
  PlannerResponse,
  ReferenceData,
} from './types'

// Same origin by default: in dev the Vite proxy forwards /api to the backend, in production nginx does.
const DEFAULT_BASE = ''
const TIMEOUT_MS = 20_000
const RETRY_STATUSES = new Set([502, 503, 504])

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details: Record<string, unknown> = {},
  ) {
    super(message)
    this.name = 'ApiError'
  }

  get isSessionGone(): boolean {
    return this.code === 'session_not_found' || this.code === 'session_expired'
  }
}

type FetchLike = typeof fetch

export interface ApiClientOptions {
  baseUrl?: string
  fetchImpl?: FetchLike
  retries?: number
  retryDelayMs?: number
}

export function createApiClient(options: ApiClientOptions = {}) {
  const baseUrl = (options.baseUrl ?? import.meta.env.VITE_API_BASE_URL ?? DEFAULT_BASE).replace(/\/$/, '')
  const fetchImpl = options.fetchImpl ?? fetch.bind(globalThis)
  const retries = options.retries ?? 2
  const retryDelayMs = options.retryDelayMs ?? 400

  async function request<T>(method: string, path: string, body?: unknown, idempotent = method === 'GET'): Promise<T> {
    let attempt = 0
    // Only idempotent calls are retried automatically to avoid duplicate state changes.
    const maxAttempts = idempotent ? retries + 1 : 1
    for (;;) {
      attempt += 1
      try {
        return await once<T>(method, path, body)
      } catch (err) {
        const transient = err instanceof ApiError ? RETRY_STATUSES.has(err.status) : err instanceof TypeError
        if (!transient || attempt >= maxAttempts) throw normalise(err)
        await new Promise((r) => setTimeout(r, retryDelayMs * attempt))
      }
    }
  }

  async function once<T>(method: string, path: string, body?: unknown): Promise<T> {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)
    try {
      const res = await fetchImpl(`${baseUrl}${path}`, {
        method,
        headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      })
      const data = await res.json().catch(() => null)
      if (!res.ok) {
        const e = data?.error ?? {}
        throw new ApiError(res.status, e.code ?? 'http_error', e.message ?? `Request failed (${res.status})`, e.details ?? {})
      }
      return data as T
    } finally {
      clearTimeout(timer)
    }
  }

  const s = (id: string) => `/api/planner/sessions/${encodeURIComponent(id)}`

  return {
    baseUrl,
    health: () => request<HealthResponse>('GET', '/api/health'),
    reference: () => request<ReferenceData>('GET', '/api/planner/reference'),
    createSession: (language: Language) => request<PlannerResponse>('POST', '/api/planner/sessions', { language }, true),
    getSession: (id: string) => request<PlannerResponse>('GET', s(id)),
    sendMessage: (id: string, message: string, language: Language) =>
      request<PlannerResponse>('POST', `${s(id)}/messages`, { message, language }),
    patchJourney: (id: string, patch: JourneyPatch) => request<PlannerResponse>('PATCH', `${s(id)}/journey`, patch),
    recommendations: (id: string) => request<PlannerResponse>('POST', `${s(id)}/recommendations`, undefined, true),
    select: (id: string, optionId: string) =>
      request<PlannerResponse>('POST', `${s(id)}/select`, { option_id: optionId }, true),
    confirm: (id: string, optionId: string | null) =>
      request<PlannerResponse>('POST', `${s(id)}/confirm`, { option_id: optionId }, true),
    reassess: (id: string, eventId: string | null) =>
      request<PlannerResponse>('POST', `${s(id)}/reassess`, { event_id: eventId }),
    cancel: (id: string) => request<PlannerResponse>('POST', `${s(id)}/cancel`, undefined, true),
  }
}

function normalise(err: unknown): ApiError {
  if (err instanceof ApiError) return err
  if (err instanceof DOMException && err.name === 'AbortError') {
    return new ApiError(0, 'timeout', 'The planner service took too long to respond.')
  }
  return new ApiError(0, 'network_error', 'Cannot reach the planner service. Check that the backend is running.')
}

export type ApiClient = ReturnType<typeof createApiClient>
export const api = createApiClient()
