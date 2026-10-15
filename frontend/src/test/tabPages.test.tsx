// Bottom-navigation pages: Alerts (delay estimate + departure board), My Trips and Profile, in both languages.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import { ApiError, type ApiClient } from '../api/client'
import type { DelayPrediction, DepartureBoard } from '../api/types'
import { saveState } from '../mobile/persist'
import { MOBILE_STRINGS, fill } from '../mobile/strings'
import { saveTrip, type SavedTrip } from '../mobile/trips'
import { response } from './fixtures'

const en = MOBILE_STRINGS.en
const ta = MOBILE_STRINGS.ta

const prov = { mode: 'cached', source: 'RailRadar live API (third-party)', as_of: '2026-10-10T09:45:00+05:30', note: 'Built from cached results.' } as const

const board = (departures: DepartureBoard['departures']): DepartureBoard => ({
  station: { code: 'MAS', name: 'Chennai Central' }, window_start: '2026-10-10T10:00:00+05:30', window_end: '2026-10-10T12:00:00+05:30',
  neighbours_checked: [], complete: true, reason: null, provenance: prov, departures,
})

const dep = (over: Partial<DepartureBoard['departures'][number]> = {}): DepartureBoard['departures'][number] => ({
  train_no: '12676', train_name: 'Kovai Express', scheduled_departure: '2026-10-10T10:30:00+05:30',
  towards: [{ code: 'CBE', name: 'Coimbatore Jn' }], delay_minutes: 12, cancelled: false, status_as_of: null, ...over,
})

const prediction = (over: Partial<DelayPrediction> = {}): DelayPrediction => ({
  train_number: '12658', station_code: 'MAS', train_class: 'Mail/Express', live_input_delay_minutes: 0,
  historical_mean_delay_minutes: 12, historical_scope: 'pair', predicted_delay_minutes: 10,
  on_time_probability: 0.37, on_time_threshold_minutes: 20, risk_level: 'LOW', model_version: '2026-10-01',
  mae_minutes: 6.4, baseline_mae_minutes: 7.1, basis: 'trained_model', insights: [],
  provenance: { mode: 'fallback', source: 'RailSaathi delay model', as_of: '2026-10-10T09:00:00+05:30', note: 'Estimate.' },
  ...over,
})

function fakeClient(over: Partial<ApiClient> = {}): ApiClient {
  return {
    baseUrl: 'http://test',
    departures: vi.fn().mockResolvedValue(board([dep()])),
    predictDelay: vi.fn().mockResolvedValue(prediction()),
    health: vi.fn().mockResolvedValue({ status: 'ok', api_version: '1', data_mode: 'demo', data_provider: { requested: 'demo', active: 'demo', reason: null }, ai: { active: true, provider: 'gemini' } }),
    reference: vi.fn().mockResolvedValue({ places: [], classes: [], passenger_needs: [], budget_priorities: [], transfer_preferences: [], disruption_events: [], data_notice: '' }),
    createSession: vi.fn().mockResolvedValue(response({}, 'Hello')),
    ...over,
  } as unknown as ApiClient
}

function open(route: string, client = fakeClient()) {
  window.location.hash = `/${route}`
  render(<App client={client} />)
  return client
}

describe('Alerts', () => {
  it('shows departure rows in English with status, delay and destination', async () => {
    open('alerts', fakeClient({ departures: vi.fn().mockResolvedValue(board([
      dep(), dep({ train_no: '12001', train_name: 'Shatabdi', delay_minutes: 0 }), dep({ train_no: '12002', train_name: 'Mail', delay_minutes: null }),
      dep({ train_no: '12003', train_name: 'Passenger', cancelled: true }),
    ])) }))
    await screen.findByText('Kovai Express')
    expect(screen.getAllByText('Dep 10:30 · towards Coimbatore Jn')).toHaveLength(4)
    expect(screen.getByText('+12 min')).toBeInTheDocument()
    expect(screen.getByText('On time')).toBeInTheDocument()
    expect(screen.getByText('Status unknown')).toBeInTheDocument()
    expect(screen.getByText('Cancelled')).toBeInTheDocument()
  })

  it('shows the same rows in Tamil, with no English status words left', async () => {
    saveState({ language: 'ta' })
    open('alerts', fakeClient({ departures: vi.fn().mockResolvedValue(board([
      dep(), dep({ train_no: '12001', train_name: 'Shatabdi', delay_minutes: 0 }), dep({ train_no: '12003', train_name: 'Passenger', cancelled: true }),
    ])) }))
    await screen.findByText('Kovai Express')
    expect(screen.getByRole('heading', { name: ta.alerts.title })).toBeInTheDocument()
    expect(screen.getByText(fill(ta.alerts.board.delayed, { n: 12 }))).toBeInTheDocument()
    expect(screen.getByText(ta.alerts.board.onTime)).toBeInTheDocument()
    expect(screen.getByText(ta.alerts.board.cancelled)).toBeInTheDocument()
    expect(screen.getAllByText(fill(ta.alerts.board.departsTowards, { time: '10:30', places: 'Coimbatore Jn' }))).toHaveLength(3)
    expect(screen.queryByText(/Cancelled|On time|towards|\bDep\b/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: ta.alerts.board.refresh })).toBeInTheDocument()
  })

  it('marks the chosen station chip with aria-pressed and loads that station', async () => {
    const client = open('alerts')
    await screen.findByText('Kovai Express')
    expect(screen.getByRole('button', { name: 'MAS' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'SBC' })).toHaveAttribute('aria-pressed', 'false')
    await userEvent.setup().click(screen.getByRole('button', { name: 'SBC' }))
    expect(screen.getByRole('button', { name: 'SBC' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'MAS' })).toHaveAttribute('aria-pressed', 'false')
    await waitFor(() => expect(client.departures).toHaveBeenLastCalledWith('SBC', expect.anything()))
  })

  it('names the station in the load-failure message, in the UI language', async () => {
    saveState({ language: 'ta' })
    open('alerts', fakeClient({ departures: vi.fn().mockRejectedValue(new Error('offline')) }))
    expect(await screen.findByText(fill(ta.alerts.board.loadFailed, { station: 'MAS' }))).toBeInTheDocument()
  })

  it('uses the on-time threshold the backend reports, not a hard-coded 15 minutes', async () => {
    open('alerts')
    await userEvent.setup().click(await screen.findByRole('button', { name: en.alerts.delay.predict }))
    const result = await screen.findByTestId('delay-result')
    expect(within(result).getByText(fill(en.alerts.delay.onTime, { n: 20 }))).toBeInTheDocument()
    expect(result).not.toHaveTextContent('15 min')
    expect(result).toHaveTextContent('+10 min')
    expect(result).toHaveTextContent('37%')
  })

  it('shows the delay result in Tamil', async () => {
    saveState({ language: 'ta' })
    open('alerts')
    await userEvent.setup().click(await screen.findByRole('button', { name: ta.alerts.delay.predict }))
    const result = await screen.findByTestId('delay-result')
    expect(result).toHaveTextContent(fill(ta.alerts.delay.typicalValue, { n: 10 }))
    expect(result).toHaveTextContent(ta.alerts.delay.risk.LOW)
    expect(result).toHaveTextContent(fill(ta.alerts.delay.onTime, { n: 20 }))
  })

  it('shows the backend error message when the estimate fails', async () => {
    open('alerts', fakeClient({ predictDelay: vi.fn().mockRejectedValue(new ApiError(503, 'unavailable', 'Delay model is not loaded.')) }))
    await userEvent.setup().click(await screen.findByRole('button', { name: en.alerts.delay.predict }))
    expect(await screen.findByText('Delay model is not loaded.')).toBeInTheDocument()
    expect(screen.queryByTestId('delay-result')).not.toBeInTheDocument()
  })

  it('says push alerts are not sent instead of claiming a connection that does not exist', async () => {
    open('alerts')
    expect(await screen.findByText(en.alerts.body)).toBeInTheDocument()
    expect(en.alerts.body).not.toMatch(/not connected|preview/i)
  })
})

const trip = (over: Partial<SavedTrip> = {}): SavedTrip => ({
  confirmationId: 'RSP-ABC1', savedAt: '2026-10-10T10:00:00Z', trainNo: '12658', trainName: 'Bengaluru Mail',
  fromLabel: 'Chennai Central (MAS)', toLabel: 'KSR Bengaluru (SBC)', journeyDate: '2026-10-12',
  departure: '2026-10-12T22:00:00+05:30', arrival: '2026-10-13T04:30:00+05:30', passengers: 2, dataMode: 'live',
  handoff: {}, ...over,
})

describe('My Trips', () => {
  beforeEach(() => localStorage.clear())

  it('shows the empty state and that trips stay on this device', async () => {
    open('trips')
    expect(await screen.findByText(en.trips.empty)).toBeInTheDocument()
    expect(screen.getByText(en.trips.deviceOnly)).toBeInTheDocument()
  })

  it('lists saved plans with a localised reference label and passenger count, and removes one', async () => {
    saveTrip(trip())
    saveTrip(trip({ confirmationId: 'RSP-XYZ9', trainName: 'Kovai Express', passengers: 1 }))
    open('trips')
    const items = await screen.findAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(screen.getByText('Ref RSP-ABC1')).toBeInTheDocument()
    expect(screen.getByText(/2 Passengers/)).toBeInTheDocument()
    expect(screen.getByText(/1 Passenger(?!s)/)).toBeInTheDocument()
    await userEvent.setup().click(within(items[0]).getByRole('button', { name: en.trips.remove }))
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
    expect(JSON.parse(localStorage.getItem('railsaathi.savedTrips.v1') ?? '{}').trips).toHaveLength(1)
  })

  it('shows the page and saved plans in Tamil', async () => {
    saveState({ language: 'ta' })
    saveTrip(trip())
    open('trips')
    expect(await screen.findByRole('heading', { name: ta.trips.title })).toBeInTheDocument()
    expect(screen.getByText(`${ta.trips.ref} RSP-ABC1`)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: ta.trips.remove })).toBeInTheDocument()
  })

  it('still lists trips that were saved by version 1 of the app (bare array)', async () => {
    localStorage.setItem('railsaathi.savedTrips.v1', JSON.stringify([trip({ confirmationId: 'OLD-1' })]))
    open('trips')
    expect(await screen.findByText('Ref OLD-1')).toBeInTheDocument()
  })
})

describe('Profile', () => {
  it('toggles the language with aria-pressed, switches every label and remembers the choice for the tab', async () => {
    const user = userEvent.setup()
    open('profile')
    expect(await screen.findByRole('heading', { name: en.profile.title })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'English' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'தமிழ்' })).toHaveAttribute('aria-pressed', 'false')

    await user.click(screen.getByRole('button', { name: 'தமிழ்' }))
    expect(screen.getByRole('heading', { name: ta.profile.title })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'தமிழ்' })).toHaveAttribute('aria-pressed', 'true')
    expect(document.documentElement.lang).toBe('ta')
    expect(JSON.parse(sessionStorage.getItem('railsaathi.session.v1') ?? '{}').language).toBe('ta')
    expect(screen.getByRole('navigation', { name: ta.nav.main })).toBeInTheDocument()
  })

  it('shows which AI model understands requests, and the built-in parser when none is active', async () => {
    open('profile')
    expect(await screen.findByText(fill(en.profile.aiActive, { provider: 'gemini' }))).toBeInTheDocument()
  })

  it('names the built-in parser when the AI is not active, and never claims Bedrock', async () => {
    open('profile', fakeClient({ health: vi.fn().mockResolvedValue({ status: 'ok', api_version: '1', data_mode: 'demo', data_provider: { requested: 'demo', active: 'demo', reason: null }, ai: { active: false } }) }))
    expect(await screen.findByText(en.profile.aiInactive)).toBeInTheDocument()
    expect(screen.queryByText(/Bedrock/)).not.toBeInTheDocument()
  })

  it('shows the data-source health and a reason when the provider is degraded', async () => {
    open('profile', fakeClient({ health: vi.fn().mockResolvedValue({ status: 'ok', api_version: '1', data_mode: 'fallback', data_provider: { requested: 'railradar', active: 'demo', reason: 'No RailRadar key.' }, ai: {} }) }))
    expect(await screen.findByText('No RailRadar key.')).toBeInTheDocument()
    expect(screen.getByTestId('provenance-badge')).toHaveAttribute('data-mode', 'fallback')
    expect(screen.getByTestId('provenance-badge')).toHaveTextContent(en.provenance.fallback)
  })
})
