import { ApiError, PLANNER_TIMEOUT_MS, READ_TIMEOUT_MS, createApiClient, errorFromResponse } from '../api/client'

const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } }))

const headersOf = (fetchImpl: ReturnType<typeof vi.fn>, call = 0) =>
  (fetchImpl.mock.calls[call] as unknown as [string, RequestInit])[1].headers as Record<string, string>

const networkDown = () => Promise.reject(new TypeError('Failed to fetch'))

describe('api client', () => {
  it('parses the error envelope into a typed ApiError', async () => {
    const fetchImpl = vi.fn(() => json(409, {
      error: { code: 'not_ready', message: 'Missing details', details: { missing_fields: ['origin'] } },
      request_id: 'req-123',
    }))
    const api = createApiClient({ baseUrl: 'http://api', fetchImpl })
    const err = await api.confirm('s1', null).catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({
      status: 409, code: 'not_ready', message: 'Missing details', details: { missing_fields: ['origin'] }, requestId: 'req-123',
    })
  })

  it('falls back to a generic error when the body is not an envelope', () => {
    const err = errorFromResponse(502, '<html>bad gateway</html>', 'rid')
    expect(err).toMatchObject({ status: 502, code: 'http_error', message: 'Request failed (502)', details: {}, requestId: 'rid' })
    expect(errorFromResponse(500, { error: 'boom' }).code).toBe('http_error')
  })

  it('sends a request id and reuses it across retries', async () => {
    const fetchImpl = vi.fn()
      .mockImplementationOnce(networkDown)
      .mockImplementationOnce(() => json(200, { status: 'ok' }))
    const api = createApiClient({ baseUrl: 'http://api', fetchImpl, retryDelayMs: 0, requestId: () => 'fixed-id' })
    await api.health()
    expect(headersOf(fetchImpl, 0)['X-Request-Id']).toBe('fixed-id')
    expect(headersOf(fetchImpl, 1)['X-Request-Id']).toBe('fixed-id')
  })

  it('generates a fresh request id per call by default', async () => {
    const fetchImpl = vi.fn(() => json(200, {}))
    const api = createApiClient({ baseUrl: 'http://api', fetchImpl })
    await api.health()
    await api.health()
    const [a, b] = [headersOf(fetchImpl, 0)['X-Request-Id'], headersOf(fetchImpl, 1)['X-Request-Id']]
    expect(a).toBeTruthy()
    expect(a).not.toBe(b)
  })

  it('retries network errors with backoff, at most twice', async () => {
    const fetchImpl = vi.fn(networkDown)
    const api = createApiClient({ baseUrl: 'http://api', fetchImpl, retryDelayMs: 0, retries: 5 })
    await expect(api.health()).rejects.toMatchObject({ code: 'network_error', status: 0 })
    expect(fetchImpl).toHaveBeenCalledTimes(3)
  })

  it('recovers when a retry succeeds', async () => {
    const fetchImpl = vi.fn()
      .mockImplementationOnce(networkDown)
      .mockImplementationOnce(networkDown)
      .mockImplementationOnce(() => json(200, { status: 'ok' }))
    const api = createApiClient({ baseUrl: 'http://api', fetchImpl, retryDelayMs: 0 })
    await expect(api.health()).resolves.toMatchObject({ status: 'ok' })
    expect(fetchImpl).toHaveBeenCalledTimes(3)
  })

  it('never retries HTTP errors, including 5xx', async () => {
    const fetchImpl = vi.fn(() => json(503, { error: { code: 'service_unavailable', message: 'busy', details: {} } }))
    const api = createApiClient({ baseUrl: 'http://api', fetchImpl, retryDelayMs: 0 })
    await expect(api.health()).rejects.toMatchObject({ status: 503, code: 'service_unavailable' })
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })

  it('does not retry non-idempotent message posts even on network errors', async () => {
    const fetchImpl = vi.fn(networkDown)
    const api = createApiClient({ baseUrl: 'http://api', fetchImpl, retryDelayMs: 0 })
    await expect(api.sendMessage('s1', 'hi', 'en')).rejects.toMatchObject({ code: 'network_error' })
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })

  it('passes the caller AbortSignal through and reports aborts without retrying', async () => {
    const fetchImpl = vi.fn((_url: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    }))
    const api = createApiClient({ baseUrl: 'http://api', fetchImpl, retryDelayMs: 0 })
    const controller = new AbortController()
    const pending = api.health({ signal: controller.signal })
    controller.abort()
    await expect(pending).rejects.toMatchObject({ code: 'aborted', isAborted: true })
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })

  it('does not call fetch when the signal is already aborted', async () => {
    const fetchImpl = vi.fn((_url: RequestInfo | URL, init?: RequestInit) =>
      init?.signal?.aborted ? Promise.reject(new DOMException('Aborted', 'AbortError')) : json(200, {}))
    const api = createApiClient({ baseUrl: 'http://api', fetchImpl })
    const controller = new AbortController()
    controller.abort()
    await expect(api.getSession('s1', { signal: controller.signal })).rejects.toMatchObject({ code: 'aborted' })
  })

  it('aborting during the retry backoff stops further attempts', async () => {
    const fetchImpl = vi.fn(networkDown)
    const api = createApiClient({ baseUrl: 'http://api', fetchImpl, retryDelayMs: 10_000 })
    const controller = new AbortController()
    const pending = api.health({ signal: controller.signal })
    await new Promise((r) => setTimeout(r, 0))
    controller.abort()
    await expect(pending).rejects.toMatchObject({ code: 'aborted' })
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })

  it('reports timeouts without retrying', async () => {
    const fetchImpl = vi.fn((_url: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    }))
    const api = createApiClient({ baseUrl: 'http://api', fetchImpl, timeoutMs: 5, retryDelayMs: 0 })
    await expect(api.health()).rejects.toMatchObject({ code: 'timeout' })
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })

  it('keeps the timeout armed while the response body is read', async () => {
    const fetchImpl = vi.fn((_url: RequestInfo | URL, init?: RequestInit) => Promise.resolve({
      ok: true,
      status: 200,
      headers: new Headers(),
      json: () => new Promise((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
      }),
    } as unknown as Response))
    const api = createApiClient({ baseUrl: 'http://api', fetchImpl, timeoutMs: 5 })
    await expect(api.health()).rejects.toMatchObject({ code: 'timeout' })
  })

  it('a caller abort during the body read is reported as aborted', async () => {
    const controller = new AbortController()
    const fetchImpl = vi.fn((_url: RequestInfo | URL, init?: RequestInit) => Promise.resolve({
      ok: true,
      status: 200,
      headers: new Headers(),
      json: () => new Promise((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
        setTimeout(() => controller.abort(), 0)
      }),
    } as unknown as Response))
    const api = createApiClient({ baseUrl: 'http://api', fetchImpl })
    await expect(api.getSession('s1', { signal: controller.signal })).rejects.toMatchObject({ code: 'aborted' })
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })

  it('planner calls get a timeout above the backend lock wait + LLM deadline budget', async () => {
    // Backend defaults: SESSION_LOCK_WAIT_SECONDS=10, LLM_OVERALL_DEADLINE_SECONDS=20 (+ journey search);
    // Cloud Run request timeout is 60 s (deploy.yml). backend/tests/test_timeout_budget.py checks the same numbers.
    expect(PLANNER_TIMEOUT_MS).toBeGreaterThanOrEqual((10 + 20 + 10) * 1000)
    expect(PLANNER_TIMEOUT_MS).toBeLessThan(60_000)
    expect(READ_TIMEOUT_MS).toBeLessThanOrEqual(PLANNER_TIMEOUT_MS)
    vi.useFakeTimers()
    try {
      const fetchImpl = vi.fn((_url: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
      }))
      const api = createApiClient({ baseUrl: 'http://api', fetchImpl })
      const settled = vi.fn()
      const pending = api.sendMessage('s1', 'hi', 'en').catch((e: ApiError) => { settled(e.code); return e })
      await vi.advanceTimersByTimeAsync(READ_TIMEOUT_MS + 1)
      expect(settled).not.toHaveBeenCalled() // a slow LLM turn is still within budget
      await vi.advanceTimersByTimeAsync(PLANNER_TIMEOUT_MS)
      await pending
      expect(settled).toHaveBeenCalledWith('timeout')
    } finally {
      vi.useRealTimers()
    }
  })

  it('stores the session token from createSession and sends it on later calls', async () => {
    const fetchImpl = vi.fn()
      .mockImplementationOnce(() => json(201, { session_id: 's1', session_token: 's1.sig' }))
      .mockImplementationOnce(() => json(200, {}))
    const api = createApiClient({ baseUrl: 'http://api', fetchImpl })
    await api.createSession('en')
    await api.getSession('s1')
    expect(headersOf(fetchImpl, 1)['X-Session-Token']).toBe('s1.sig')
  })

  it('flags expired sessions', () => {
    expect(new ApiError(410, 'session_expired', 'x').isSessionGone).toBe(true)
  })

  it('sends JSON to the configured base URL', async () => {
    const fetchImpl = vi.fn(() => json(200, {}))
    const api = createApiClient({ baseUrl: 'http://api/', fetchImpl })
    await api.sendMessage('abc', 'to Chennai', 'ta')
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('http://api/api/planner/sessions/abc/messages')
    expect(JSON.parse(String(init.body))).toEqual({ message: 'to Chennai', language: 'ta' })
  })
})

describe('localize (multipart camera frame)', () => {
  const ok = (token = 'loc-token') => json(200, {
    status: 'fix', station_id: 'chennai_central', fix: null, candidates: [], confidence_threshold: 0.6, latency_ms: 1,
    message: null, session_token: token, provenance: { mode: 'live', source: 'gemini-vision', as_of: '2026-10-16T00:00:00Z', note: 'Approximate.' },
  })
  const image = () => new Blob([new Uint8Array([0xff, 0xd8, 0xff])], { type: 'image/jpeg' })
  const init = (f: ReturnType<typeof vi.fn>, call = 0) => (f.mock.calls[call] as unknown as [string, RequestInit])[1]

  it('posts form fields (route node ids comma-separated) without a JSON content type', async () => {
    const fetchImpl = vi.fn(() => ok())
    const api = createApiClient({ baseUrl: 'http://api', fetchImpl })
    await api.localize({ station_id: 'chennai_central', image: image(), previous_node_id: 'cj_north', route_node_ids: ['a', 'b', 'c'] })
    const [url, req] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('http://api/api/navigation/localize')
    expect(req.method).toBe('POST')
    const form = req.body as FormData
    expect(form).toBeInstanceOf(FormData)
    expect(form.get('station_id')).toBe('chennai_central')
    expect(form.get('previous_node_id')).toBe('cj_north')
    expect(form.get('route_node_ids')).toBe('a,b,c')
    expect((form.get('image') as File).type).toBe('image/jpeg')
    expect((req.headers as Record<string, string>)['Content-Type']).toBeUndefined() // the browser sets the boundary
  })

  it('omits empty priors, resends the issued session token and is never retried', async () => {
    const fetchImpl = vi.fn(() => ok('issued')).mockImplementationOnce(() => ok('issued'))
    const api = createApiClient({ baseUrl: 'http://api', fetchImpl })
    await api.localize({ station_id: 's', image: image() })
    const form = init(fetchImpl).body as FormData
    expect(form.has('previous_node_id')).toBe(false)
    expect(form.has('route_node_ids')).toBe(false)
    expect((init(fetchImpl).headers as Record<string, string>)['X-Session-Token']).toBeUndefined()
    await api.localize({ station_id: 's', image: image() })
    expect((init(fetchImpl, 1).headers as Record<string, string>)['X-Session-Token']).toBe('issued')

    const down = vi.fn(networkDown)
    const api2 = createApiClient({ baseUrl: 'http://api', fetchImpl: down, retryDelayMs: 0 })
    await expect(api2.localize({ station_id: 's', image: image() })).rejects.toMatchObject({ code: 'network_error' })
    expect(down).toHaveBeenCalledTimes(1)
  })

  it('uses the planner token when there is one; freshSession sends none and keeps the newly issued token', async () => {
    const fetchImpl = vi.fn()
      .mockImplementationOnce(() => json(201, { session_token: 'planner' }))
      .mockImplementationOnce(() => ok('planner'))
      .mockImplementationOnce(() => ok('fresh'))
      .mockImplementationOnce(() => ok('fresh'))
    const api = createApiClient({ baseUrl: 'http://api', fetchImpl })
    await api.createSession('en')
    await api.localize({ station_id: 's', image: image() })
    expect((init(fetchImpl, 1).headers as Record<string, string>)['X-Session-Token']).toBe('planner')
    await api.localize({ station_id: 's', image: image() }, { freshSession: true })
    expect((init(fetchImpl, 2).headers as Record<string, string>)['X-Session-Token']).toBeUndefined()
    await api.localize({ station_id: 's', image: image() })
    expect((init(fetchImpl, 3).headers as Record<string, string>)['X-Session-Token']).toBe('fresh')
  })

  it('a 429 carries Retry-After seconds', async () => {
    const fetchImpl = vi.fn(() => json(429, { error: { code: 'rate_limited', message: 'Too many camera fixes.', details: {} } }, { 'Retry-After': '37' }))
    const api = createApiClient({ baseUrl: 'http://api', fetchImpl })
    await expect(api.localize({ station_id: 's', image: image() })).rejects.toMatchObject({ status: 429, code: 'rate_limited', retryAfterS: 37 })
    expect(errorFromResponse(429, {}, null, 'soon').retryAfterS).toBeNull()
  })
})
