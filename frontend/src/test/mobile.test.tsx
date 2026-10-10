import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import { ApiError, type ApiClient } from '../api/client'
import { RELAX_PATCHES } from '../api/relax'
import type { Recommendation, SessionState } from '../api/types'
import { parseRoute } from '../mobile/router'
import { baseState, rec, response, withRecs } from './fixtures'

const GREETING = 'Tell me where and when you want to travel.'

const liveRec: Recommendation = {
  ...rec,
  labels: ['best_overall', 'fastest'],
  selected_class: null, fare_per_passenger: null, total_fare: null,
  explanation: 'Recommended because it is the quickest eligible journey (7 h 40 min).',
  unverified: ['Fare not available from the data source — check the official fare before booking.'],
  option: {
    ...rec.option, option_id: 'RR-22640-CBE-MAS@2026-10-10', fares: {}, classes: [],
    legs: [{ ...rec.option.legs[0], train_no: '22640', train_name: 'MGR Chennai Central SF Express' }],
    provenance: { mode: 'live', source: 'RailRadar live API (third-party)', as_of: '2026-10-10T15:21:00+05:30', note: 'Live third-party data' },
  },
}
const liveState: Partial<SessionState> = {
  ...withRecs,
  data_mode: 'live',
  recommendations: { ...withRecs.recommendations!, recommendations: [liveRec], provenance: liveRec.option.provenance, notes: [] },
}

function fakeClient(overrides: Partial<ApiClient> = {}): ApiClient {
  return {
    baseUrl: 'http://test',
    health: vi.fn().mockResolvedValue({ status: 'ok', api_version: '0.1.0', data_mode: 'demo', data_provider: { requested: 'demo', active: 'demo', reason: null }, ai: { active: false } }),
    reference: vi.fn().mockResolvedValue({ places: [], classes: ['SL'], passenger_needs: [], budget_priorities: [], transfer_preferences: [], disruption_events: [], data_notice: 'DEMO' }),
    createSession: vi.fn().mockResolvedValue(response({}, GREETING)),
    getSession: vi.fn(),
    sendMessage: vi.fn().mockResolvedValue(response(withRecs, 'I found 3 eligible option(s).')),
    patchJourney: vi.fn().mockResolvedValue(response(withRecs, '')),
    recommendations: vi.fn(),
    select: vi.fn().mockResolvedValue(response({ ...withRecs, status: 'awaiting_confirmation', selected_option_id: rec.option.option_id }, 'You selected D103.')),
    confirm: vi.fn().mockResolvedValue(response({
      ...withRecs, status: 'confirmed', selected_option_id: rec.option.option_id,
      confirmation: { confirmation_id: 'RSP-MOBILE1', confirmed_at: '', selected_option_id: rec.option.option_id, constraints_hash: 'abc', handoff: { module: 'smart_passenger_planner' }, superseded: false },
    }, 'Confirmed. No ticket has been booked.')),
    reassess: vi.fn().mockRejectedValue(new ApiError(409, 'no_relevant_event', 'No delays or cancellations are currently reported for your trains (live status).')),
    cancel: vi.fn(),
    ...overrides,
  } as ApiClient
}

async function open(route: string, client = fakeClient()) {
  window.location.hash = `/${route}`
  const user = userEvent.setup()
  render(<App client={client} />)
  await waitFor(() => expect(client.createSession).toHaveBeenCalled())
  await waitFor(() => expect(client.health).toHaveBeenCalled())
  return { client, user }
}

beforeEach(() => {
  window.localStorage.clear()
  delete (globalThis as Record<string, unknown>).webkitSpeechRecognition
})

describe('router', () => {
  it('parses hashes and falls back to home', () => {
    expect(parseRoute('#/options')).toBe('options')
    expect(parseRoute('#/nope')).toBe('home')
    expect(parseRoute('')).toBe('home')
  })
})

describe('Dashboard', () => {
  it('starts a real planner request from a popular route and opens the voice agent', async () => {
    const { client, user } = await open('home')
    expect(screen.getByText('Popular Routes')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Chennai → Bengaluru/ }))
    await waitFor(() => expect(client.sendMessage).toHaveBeenCalledWith(baseState.session_id, 'from Chennai to Bengaluru', 'en'))
    await waitFor(() => expect(window.location.hash).toBe('#/plan'))
    expect(await screen.findByText('Plan with AI')).toBeInTheDocument()
  })

  it('switches language to Tamil', async () => {
    const { user } = await open('home')
    await user.click(screen.getByRole('button', { name: 'தமிழ்' }))
    expect(screen.getByText('வணக்கம்,')).toBeInTheDocument()
  })
})

describe('AI Voice Agent', () => {
  it('sends typed text to the backend and shows the extracted details and progress', async () => {
    const { client, user } = await open('plan')
    expect(screen.getByText('Voice input is not supported in this browser. Please type your request below.')).toBeInTheDocument()
    await user.type(screen.getByLabelText('Type your journey request'), 'Coimbatore to Chennai before 9 am tomorrow, 2 people')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(client.sendMessage).toHaveBeenCalledWith(baseState.session_id, 'Coimbatore to Chennai before 9 am tomorrow, 2 people', 'en')
    const details = await screen.findByRole('region', { name: 'Journey details' })
    expect(within(details).getByText('Coimbatore')).toBeInTheDocument()
    expect(within(details).getByText('09:00 (must)')).toBeInTheDocument()
    expect(screen.getByText('Journey options ready')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'View journey options' }))
    await waitFor(() => expect(window.location.hash).toBe('#/options'))
  })

  it('example prompts fill the input without sending', async () => {
    const { client, user } = await open('plan')
    await user.click(screen.getByRole('button', { name: /Find a direct train from Chennai to Coimbatore/ }))
    expect(screen.getByLabelText('Type your journey request')).toHaveValue('Find a direct train from Chennai to Coimbatore for 2 people.')
    expect(client.sendMessage).not.toHaveBeenCalled()
  })

  it('voice transcript fills the box, Send waits for Stop, nothing is auto-sent', async () => {
    let instance: { onresult: ((e: unknown) => void) | null; onend: (() => void) | null; lang: string } | null = null
    class FakeRecognition {
      lang = ''; interimResults = false; continuous = false
      onresult: ((e: unknown) => void) | null = null; onerror = null; onend: (() => void) | null = null
      constructor() { instance = this as never }
      start() {} stop() { this.onend?.() } abort() {}
    }
    ;(globalThis as Record<string, unknown>).webkitSpeechRecognition = FakeRecognition
    const { client, user } = await open('plan')
    await user.selectOptions(screen.getByLabelText('Speak in'), 'ta-IN')
    await user.click(screen.getByRole('button', { name: 'Start voice input' }))
    expect(instance!.lang).toBe('ta-IN')
    act(() => instance!.onresult?.({ results: [Object.assign([{ transcript: 'நாளை சென்னைக்கு', confidence: 0.9 }], { isFinal: true })] }))
    expect(screen.getByLabelText('Type your journey request')).toHaveValue('நாளை சென்னைக்கு')
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Stop voice input' }))
    expect(screen.getByRole('button', { name: 'Send' })).toBeEnabled()
    expect(client.sendMessage).not.toHaveBeenCalled()
  })

  it('shows API errors with a retry', async () => {
    const client = fakeClient({ sendMessage: vi.fn().mockRejectedValue(new ApiError(0, 'network_error', 'Cannot reach the planner service.')) })
    const { user } = await open('plan', client)
    await user.type(screen.getByLabelText('Type your journey request'), 'to Chennai')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Cannot reach the planner service.')
    expect(within(alert).getByRole('button', { name: /Retry/ })).toBeInTheDocument()
  })
})

describe('Journey Options', () => {
  async function withState(state: Partial<SessionState>, overrides: Partial<ApiClient> = {}) {
    const client = fakeClient({ sendMessage: vi.fn().mockResolvedValue(response(state, 'ok')), ...overrides })
    const ctx = await open('plan', client)
    await ctx.user.type(screen.getByLabelText('Type your journey request'), 'x')
    await ctx.user.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(client.sendMessage).toHaveBeenCalled())
    act(() => { window.location.hash = '/options' })
    return ctx
  }

  it('only shows tabs for returned categories and never invents a fare', async () => {
    await withState(liveState)
    const tabs = await screen.findByRole('tablist')
    expect(within(tabs).getAllByRole('tab').map((t) => t.textContent)).toEqual(['Best Match', 'Fastest'])
    const card = screen.getByRole('article', { name: /22640/ })
    expect(within(card).getByText('Fare not available')).toBeInTheDocument()
    expect(within(card).getByText('Classes not listed')).toBeInTheDocument()
    expect(within(card).getByText('LIVE · RailRadar')).toBeInTheDocument()
    expect(card.textContent).not.toContain('₹')
    expect(screen.getByTestId('source-line')).toHaveTextContent('RailRadar live API (third-party) · retrieved')
  })

  it('selecting a card calls the backend, then confirm produces the handoff (no booking) and can be saved', async () => {
    const { client, user } = await withState(withRecs)
    await user.click(await screen.findByRole('button', { name: 'View details: D103' }))
    expect(client.select).toHaveBeenCalledWith(baseState.session_id, rec.option.option_id)
    expect(await screen.findByText('Journey Details')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Confirm & Continue/ }))
    expect(client.confirm).toHaveBeenCalledWith(baseState.session_id, rec.option.option_id)
    expect(await screen.findByText('Journey Plan Ready!')).toBeInTheDocument()
    expect(screen.getByText('This is a journey plan only. No ticket has been booked.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Check live status/ }))
    expect(client.reassess).toHaveBeenCalledWith(baseState.session_id, null)
    expect(await screen.findByText('No delays or cancellations reported right now.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Save to My Trips/ }))
    expect(screen.getByRole('button', { name: /Saved on this device/ })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'My Trips' }))
    expect(await screen.findByText(/RSP-MOBILE1/)).toBeInTheDocument()
  })

  it('no feasible option offers the backend relax suggestion', async () => {
    const noFeasible: Partial<SessionState> = {
      ...withRecs, status: 'no_feasible_options',
      recommendations: { ...withRecs.recommendations!, recommendations: [], eligible_count: 0,
        relax_suggestions: [{ constraint: 'arrival_deadline', excluded_count: 3, message: 'Allow arrival after your deadline' }] },
    }
    const { client, user } = await withState(noFeasible)
    expect(await screen.findByText('No matching train found')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Allow arrival after your deadline' }))
    expect(client.patchJourney).toHaveBeenCalledWith(baseState.session_id, RELAX_PATCHES.arrival_deadline)
  })

  it('live data outage shows the backend message and a retry, with no journeys', async () => {
    const outage = response({ ...withRecs, status: 'error', recommendations: null }, 'Live train data is unavailable right now (RailRadar returned HTTP 429).')
    const { client, user } = await withState(outage.state)
    client.sendMessage = vi.fn().mockResolvedValue(outage)
    expect(screen.queryByRole('article')).not.toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: /Try again/ }))
    expect(client.sendMessage).toHaveBeenCalledWith(baseState.session_id, 'show options', 'en')
  })
})

describe('placeholder screens are honest', () => {
  it('station navigation is a labelled preview with navigation disabled', async () => {
    await open('navigation')
    expect(screen.getByText(/Preview only — in-station navigation is not connected yet/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Start Navigation/ })).toBeDisabled()
  })

  it('help screen has real tel: links and never claims assistance is booked', async () => {
    await open('help')
    expect(screen.getByRole('link', { name: /Call 139 \(Railway Helpline\)/ })).toHaveAttribute('href', 'tel:139')
    expect(screen.getByRole('link', { name: /Railway Police/ })).toHaveAttribute('href', 'tel:182')
    expect(screen.getByText(/does not mean assistance is booked or guaranteed/)).toBeInTheDocument()
  })

  it('confirmation without a confirmed plan says so', async () => {
    await open('confirmation')
    expect(screen.getByText(/No confirmed plan yet/)).toBeInTheDocument()
  })
})
