import { ApiError, createApiClient } from '../api/client'

const json = (status: number, body: unknown) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))

describe('api client', () => {
  it('parses structured backend errors', async () => {
    const fetchImpl = vi.fn(() => json(409, { error: { code: 'not_ready', message: 'Missing details', details: { missing_fields: ['origin'] } } }))
    const api = createApiClient({ baseUrl: 'http://api', fetchImpl })
    await expect(api.confirm('s1', null)).rejects.toMatchObject({ status: 409, code: 'not_ready', message: 'Missing details' })
  })

  it('retries idempotent GET requests on transient failures', async () => {
    const fetchImpl = vi.fn()
      .mockImplementationOnce(() => json(503, {}))
      .mockImplementationOnce(() => json(200, { status: 'ok' }))
    const api = createApiClient({ baseUrl: 'http://api', fetchImpl, retryDelayMs: 0 })
    await expect(api.health()).resolves.toMatchObject({ status: 'ok' })
    expect(fetchImpl).toHaveBeenCalledTimes(2)
  })

  it('does not retry non-idempotent message posts', async () => {
    const fetchImpl = vi.fn(() => json(503, {}))
    const api = createApiClient({ baseUrl: 'http://api', fetchImpl, retryDelayMs: 0 })
    await expect(api.sendMessage('s1', 'hi', 'en')).rejects.toBeInstanceOf(ApiError)
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })

  it('normalises network failures', async () => {
    const fetchImpl = vi.fn(() => Promise.reject(new TypeError('Failed to fetch')))
    const api = createApiClient({ baseUrl: 'http://api', fetchImpl, retries: 0 })
    await expect(api.health()).rejects.toMatchObject({ code: 'network_error' })
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
