// The planner keeps its session id, signed token and the UI language in sessionStorage, resumes the session with
// getSession after a reload, and falls back to a fresh session when it cannot.
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import { ApiError, type ApiClient } from '../api/client'
import type { PlannerResponse } from '../api/types'
import { loadState, saveState } from '../mobile/persist'
import { MOBILE_STRINGS } from '../mobile/strings'
import { response } from './fixtures'

const KEY = 'railsaathi.session.v1'

const fresh = (id: string, token: string, message = 'Hello'): PlannerResponse => ({
  ...response({ session_id: id }, message), session_token: token,
})

function fakeClient(over: Partial<ApiClient> = {}): ApiClient {
  return {
    baseUrl: 'http://test',
    health: vi.fn().mockResolvedValue({ status: 'ok', api_version: '1', data_mode: 'demo', data_provider: { requested: 'demo', active: 'demo', reason: null }, ai: {} }),
    reference: vi.fn().mockResolvedValue({ places: [], classes: [], passenger_needs: [], budget_priorities: [], transfer_preferences: [], disruption_events: [], data_notice: '' }),
    createSession: vi.fn().mockResolvedValue(fresh('new-session', 'new-token')),
    getSession: vi.fn(),
    setSessionToken: vi.fn(),
    sendMessage: vi.fn().mockResolvedValue(response({ session_id: 'new-session' }, 'Reply')),
    ...over,
  } as unknown as ApiClient
}

describe('planner session persistence', () => {
  beforeEach(() => { window.location.hash = '/plan' })

  it('stores the new session id, token and language when it starts a session', async () => {
    const client = fakeClient()
    render(<App client={client} />)
    await waitFor(() => expect(loadState().session).toEqual({ sessionId: 'new-session', token: 'new-token' }))
    expect(client.getSession).not.toHaveBeenCalled()
    expect(JSON.parse(sessionStorage.getItem(KEY) ?? '{}')).toMatchObject({ language: 'en' })
  })

  it('resumes the stored session with getSession instead of creating a new one', async () => {
    saveState({ language: 'ta', session: { sessionId: 'old-session', token: 'old-token' } })
    const client = fakeClient({ getSession: vi.fn().mockResolvedValue(response({ session_id: 'old-session', status: 'presenting_recommendations' }, 'Welcome back')) })
    render(<App client={client} />)
    expect(await screen.findByText('Welcome back')).toBeInTheDocument()
    expect(client.setSessionToken).toHaveBeenCalledWith('old-token')
    expect(client.getSession).toHaveBeenCalledWith('old-session')
    expect(client.createSession).not.toHaveBeenCalled()
    expect(document.documentElement.lang).toBe('ta')
    expect(screen.getAllByText('Welcome back')).toHaveLength(1) // shown once, not duplicated by the resume
  })

  it('sends later turns on the resumed session', async () => {
    saveState({ session: { sessionId: 'old-session', token: 'old-token' } })
    const client = fakeClient({ getSession: vi.fn().mockResolvedValue(response({ session_id: 'old-session' }, 'Back')) })
    render(<App client={client} />)
    await screen.findByText('Back')
    await userEvent.setup().type(screen.getByLabelText(MOBILE_STRINGS.en.plan.inputLabel), 'Chennai to Madurai{Enter}')
    await waitFor(() => expect(client.sendMessage).toHaveBeenCalledWith('old-session', 'Chennai to Madurai', 'en'))
  })

  it('forgets the stored session and starts a new one when the backend no longer knows it', async () => {
    saveState({ session: { sessionId: 'gone', token: 'stale-token' } })
    const client = fakeClient({ getSession: vi.fn().mockRejectedValue(new ApiError(404, 'session_not_found', 'Session not found.')) })
    render(<App client={client} />)
    await waitFor(() => expect(client.createSession).toHaveBeenCalledTimes(1))
    expect(client.setSessionToken).toHaveBeenLastCalledWith(null)
    await waitFor(() => expect(loadState().session).toEqual({ sessionId: 'new-session', token: 'new-token' }))
  })

  it('starts a new session when the stored record is not usable', async () => {
    sessionStorage.setItem(KEY, JSON.stringify({ language: 'fr', session: { sessionId: 42, token: {} } }))
    const client = fakeClient()
    render(<App client={client} />)
    await waitFor(() => expect(client.createSession).toHaveBeenCalledWith('en'))
    expect(client.getSession).not.toHaveBeenCalled()
  })

  it('keeps working when sessionStorage throws', async () => {
    const get = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
    try {
      const client = fakeClient()
      render(<App client={client} />)
      await waitFor(() => expect(client.createSession).toHaveBeenCalledWith('en'))
      expect(await screen.findByText('Hello')).toBeInTheDocument()
    } finally {
      get.mockRestore()
      set.mockRestore()
    }
  })

  it('starts the app in the persisted language and creates the session in it', async () => {
    saveState({ language: 'ta' })
    const client = fakeClient()
    render(<App client={client} />)
    await waitFor(() => expect(client.createSession).toHaveBeenCalledWith('ta'))
    expect(screen.getByRole('heading', { name: MOBILE_STRINGS.ta.plan.title })).toBeInTheDocument()
  })

  it('persists a language change without losing the session', async () => {
    window.location.hash = '/profile'
    const client = fakeClient()
    render(<App client={client} />)
    await waitFor(() => expect(loadState().session?.sessionId).toBe('new-session'))
    await act(async () => { await userEvent.setup().click(await screen.findByRole('button', { name: 'தமிழ்' })) })
    expect(loadState()).toEqual({ language: 'ta', session: { sessionId: 'new-session', token: 'new-token' } })
  })

  it.each([
    ['offline', new ApiError(0, 'network_error', 'Cannot reach the planner service.')],
    ['a timeout', new ApiError(0, 'timeout', 'took too long')],
    ['a 503', new ApiError(503, 'storage_unavailable', 'Saved data is temporarily unavailable.')],
  ])('keeps the stored session after %s on reload, and Retry resumes the same plan', async (_label, error) => {
    saveState({ session: { sessionId: 'old-session', token: 'old-token' } })
    const getSession = vi.fn()
      .mockRejectedValueOnce(error)
      .mockResolvedValueOnce(response({ session_id: 'old-session', status: 'presenting_recommendations' }, 'Welcome back'))
    const client = fakeClient({ getSession })
    render(<App client={client} />)
    const alert = await screen.findByRole('alert')
    expect(client.createSession).not.toHaveBeenCalled() // the saved plan is not thrown away
    expect(loadState().session).toEqual({ sessionId: 'old-session', token: 'old-token' })
    expect(client.setSessionToken).not.toHaveBeenCalledWith(null)
    await userEvent.setup().click(within(alert).getByRole('button', { name: /Retry/ }))
    expect(await screen.findByText('Welcome back')).toBeInTheDocument()
    expect(getSession).toHaveBeenCalledTimes(2)
    expect(client.createSession).not.toHaveBeenCalled()
  })

  it('a token the backend rejects is cleared and a fresh session started', async () => {
    saveState({ session: { sessionId: 'old-session', token: 'bad-token' } })
    const client = fakeClient({ getSession: vi.fn().mockRejectedValue(new ApiError(401, 'invalid_session_token', 'bad')) })
    render(<App client={client} />)
    await waitFor(() => expect(client.createSession).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(loadState().session).toEqual({ sessionId: 'new-session', token: 'new-token' }))
  })
})
