import { ApiError, createApiClient, errorFromResponse } from '../api/client'

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
