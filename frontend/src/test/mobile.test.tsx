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
    stations: vi.fn().mockResolvedValue([]),
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
  // Every screen is a lazy chunk: wait for it to replace the Suspense fallback.
  await waitFor(() => expect(screen.queryByText('Loading…')).not.toBeInTheDocument())
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
    expect(screen.getByRole('button', { name: /சென்னை → மதுரை/ })).toBeInTheDocument()
    expect(screen.getByText('நேரடி ரயில் அறிவிப்புகள்')).toBeInTheDocument()
    const card = screen.getByRole('button', { name: /சென்னை → மதுரை/ })
    expect(within(card).getByText('மதுரை சந்திப்பு')).toBeInTheDocument()
    expect(within(card).queryByText('Madurai Junction')).not.toBeInTheDocument()
  })

  it('shows the four popular routes as cards with station codes, no fares or timings, and no mislabelled photo', async () => {
    await open('home')
    const expected: [string, string, string | null][] = [
      ['Chennai → Bengaluru', 'MAS → SBC', null],
      ['Chennai → Coimbatore', 'MAS → CBE', 'coimbatore'],
      ['Chennai → Madurai', 'MAS → MDU', 'madurai'],
      ['Chennai → Tiruchirappalli', 'MAS → TPJ', 'tiruchirappalli'],
    ]
    for (const [name, codes, image] of expected) {
      const card = screen.getByRole('button', { name: new RegExp(name) })
      expect(within(card).getByText(codes)).toBeInTheDocument()
      expect(within(card).getByText('Plan this route')).toBeInTheDocument()
      expect(card.textContent).not.toMatch(/₹|\d+ ?h\b/)
      // No Bengaluru photo exists, so that card must not borrow another city's picture.
      const img = card.querySelector('img')
      if (image) expect(img?.getAttribute('src')).toContain(image)
      else expect(img).toBeNull()
    }
  })

  it('live alerts promo is honest: no push alerts, opens Alerts when nothing is confirmed', async () => {
    const { user } = await open('home')
    const promo = screen.getByRole('region', { name: 'Live train alerts' })
    expect(within(promo).getByText('RailSaathi does not send push alerts.')).toBeInTheDocument()
    expect(within(promo).getByTestId('provenance-badge')).toHaveAttribute('data-mode', 'demo')
    await user.click(within(promo).getByRole('button', { name: 'Open alerts' }))
    await waitFor(() => expect(window.location.hash).toBe('#/alerts'))
  })

  it('live alerts promo offers live status once a plan is confirmed', async () => {
    const confirmed = {
      ...withRecs, status: 'confirmed', selected_option_id: rec.option.option_id,
      confirmation: { confirmation_id: 'RSP-MOBILE1', confirmed_at: '', selected_option_id: rec.option.option_id, constraints_hash: 'abc', handoff: { module: 'smart_passenger_planner' }, superseded: false },
    } as Partial<SessionState>
    const { user } = await open('home', fakeClient({ createSession: vi.fn().mockResolvedValue(response(confirmed, 'Confirmed.')) }))
    const promo = screen.getByRole('region', { name: 'Live train alerts' })
    await user.click(within(promo).getByRole('button', { name: 'Check live status' }))
    await waitFor(() => expect(window.location.hash).toBe('#/confirmation'))
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
    const speakIn = screen.getByRole('group', { name: 'Speak in' })
    expect(within(speakIn).getAllByRole('button').map((b) => b.textContent)).toEqual(['தமிழ்', 'English', 'Tanglish'])
    await user.click(within(speakIn).getByRole('button', { name: 'தமிழ்' }))
    const waves = screen.getAllByTestId('voice-wave')
    expect(waves).toHaveLength(2)
    waves.forEach((w) => expect(w).toHaveAttribute('data-listening', 'false'))
    await user.click(screen.getByRole('button', { name: 'Start voice input' }))
    expect(instance!.lang).toBe('ta-IN')
    expect(screen.getByRole('status')).toHaveTextContent('Listening')
    screen.getAllByTestId('voice-wave').forEach((w) => expect(w).toHaveAttribute('data-listening', 'true'))
    act(() => instance!.onresult?.({ results: [Object.assign([{ transcript: 'நாளை சென்னைக்கு', confidence: 0.9 }], { isFinal: true })] }))
    expect(screen.getByLabelText('Type your journey request')).toHaveValue('நாளை சென்னைக்கு')
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Stop voice input' }))
    expect(screen.getByRole('button', { name: 'Send' })).toBeEnabled()
    expect(screen.getByRole('status')).toHaveTextContent('Transcript ready')
    screen.getAllByTestId('voice-wave').forEach((w) => expect(w).toHaveAttribute('data-listening', 'false'))
    expect(client.sendMessage).not.toHaveBeenCalled()
  })

  it('renders the supplied artwork: background, robot, mic button image and two voice waves', async () => {
    await open('plan')
    expect(screen.getByRole('img', { name: 'RailSaathi AI assistant robot' }).getAttribute('src')).toContain('robot')
    const mic = screen.getByRole('button', { name: 'Start voice input' })
    expect(within(mic).getByRole('presentation').getAttribute('src')).toContain('mic-button')
    expect(mic).toHaveAttribute('data-state', 'unsupported')
    expect(mic).toBeDisabled()
    expect(screen.getByTestId('voice-hero').getAttribute('data-bg')).toContain('station-bg')
  })

  it('Tanglish uses Indian-English recognition and permission denial is explained', async () => {
    let lang = ''
    class FakeRecognition {
      lang = ''; interimResults = false; continuous = false; onresult = null; onerror = null; onend = null
      start() { lang = this.lang } stop() {} abort() {}
    }
    ;(globalThis as Record<string, unknown>).webkitSpeechRecognition = FakeRecognition
    Object.defineProperty(navigator, 'permissions', {
      configurable: true, value: { query: vi.fn().mockResolvedValue({ state: 'denied', onchange: null }) },
    })
    try {
      const { user } = await open('plan')
      await user.click(within(screen.getByRole('group', { name: 'Speak in' })).getByRole('button', { name: 'Tanglish' }))
      expect(await screen.findByText(/Microphone access is blocked/)).toBeInTheDocument()
      await user.click(screen.getByRole('button', { name: 'Start voice input' }))
      expect(lang).toBe('en-IN')
    } finally {
      delete (navigator as unknown as Record<string, unknown>).permissions
    }
  })

  it('works when the Permissions API is missing', async () => {
    ;(globalThis as Record<string, unknown>).webkitSpeechRecognition = class { start() {} stop() {} abort() {} }
    await open('plan')
    expect(screen.getByRole('status')).toHaveTextContent('Tap the microphone and speak')
  })

  it('keeps the journey card hidden until every mandatory detail is collected', async () => {
    const partial: Partial<SessionState> = {
      ...baseState, status: 'collecting_details', missing_fields: ['destination', 'journey_date', 'passenger_count'],
      journey: { ...withRecs.journey!, destination: null, journey_date: null, passenger_count: null },
    }
    const client = fakeClient({
      sendMessage: vi.fn()
        .mockResolvedValueOnce(response(partial, 'Where do you want to go?'))
        .mockResolvedValueOnce(response(withRecs, 'I found 3 eligible option(s).')),
    })
    const { user } = await open('plan', client)
    await user.type(screen.getByLabelText('Type your journey request'), 'from Coimbatore')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    const thread = screen.getByTestId('chat-thread')
    expect(await within(thread).findByText('Where do you want to go?')).toBeInTheDocument()
    expect(within(thread).getByText('from Coimbatore').closest('[data-role]')).toHaveAttribute('data-role', 'user')
    expect(screen.queryByRole('region', { name: 'Journey details' })).not.toBeInTheDocument()

    await user.type(screen.getByLabelText('Type your journey request'), 'to Chennai tomorrow, 2 people')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByRole('region', { name: 'Journey details' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'View journey options' })).toBeInTheDocument()
  })

  it('chat is a thread with the composer at the bottom and one mic button at a time', async () => {
    ;(globalThis as Record<string, unknown>).webkitSpeechRecognition = class { start() {} stop() {} abort() {} }
    const { user } = await open('plan')
    expect(screen.getAllByRole('button', { name: 'Start voice input' })).toHaveLength(1)
    await user.type(screen.getByLabelText('Type your journey request'), 'Coimbatore to Chennai tomorrow, 2 people')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await screen.findByRole('region', { name: 'Journey details' })
    const composer = screen.getByRole('form', { name: 'Message' })
    expect(screen.getAllByRole('button', { name: 'Start voice input' })).toHaveLength(1)
    expect(within(composer).getByRole('button', { name: 'Start voice input' })).toBeInTheDocument()
    expect(within(composer).getByRole('button', { name: 'Send' })).toBeInTheDocument()
    const thread = screen.getByTestId('chat-thread')
    expect(within(thread).getAllByTestId('bubble').map((b) => b.getAttribute('data-role'))).toEqual(['assistant', 'user', 'assistant'])
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

  it('labels demo journeys with the shared provenance badge on options and details', async () => {
    const { user } = await withState(withRecs)
    const card = await screen.findByRole('article', { name: /D103/ })
    const badge = within(card).getByTestId('provenance-badge')
    expect(badge).toHaveAttribute('data-mode', 'demo')
    expect(badge).toHaveTextContent('DEMO')
    await user.click(screen.getByRole('button', { name: 'View details: D103' }))
    await screen.findByText('Journey Details')
    expect(screen.getByTestId('provenance-badge')).toHaveAttribute('data-mode', 'demo')
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
  it('station navigation has no placeholder map, mock compass or permanently disabled buttons', async () => {
    await open('navigation')
    expect(await screen.findByLabelText('Station')).toBeInTheDocument()
    expect(screen.queryByText(/Preview only/)).not.toBeInTheDocument()
    expect(screen.queryByText(/AR Bearing Compass/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Start Navigation/ })).not.toBeInTheDocument()
    expect(screen.getByTestId('coach-unknown')).toHaveTextContent('Coach position: unknown')
  })

  it('help screen has real tel: links and never claims assistance is booked', async () => {
    await open('help')
    expect(screen.getByRole('link', { name: /Call 139 \(Railway Helpline\)/ })).toHaveAttribute('href', 'tel:139')
    expect(screen.getByRole('link', { name: /Railway Police/ })).toHaveAttribute('href', 'tel:139')
    expect(screen.getByText(/does not mean assistance is booked or guaranteed/)).toBeInTheDocument()
  })

  it('confirmation without a confirmed plan says so', async () => {
    await open('confirmation')
    expect(screen.getByText(/No confirmed plan yet/)).toBeInTheDocument()
  })
})
