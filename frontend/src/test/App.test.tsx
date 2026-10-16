import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../ClassicApp'
import { RELAX_PATCHES } from '../api/relax'
import { ApiError, type ApiClient } from '../api/client'
import { toPatch } from '../components/FieldEditor'
import { baseState, rec, response, withRecs } from './fixtures'

function fakeClient(overrides: Partial<ApiClient> = {}): ApiClient {
  return {
    baseUrl: 'http://test',
    health: vi.fn().mockResolvedValue({ status: 'ok', api_version: '0.1.0', data_mode: 'demo', ai: { active: false } }),
    reference: vi.fn().mockResolvedValue({
      places: [{ id: 'chennai', label: 'Chennai (any station)', kind: 'city', station_codes: ['MAS'] }],
      classes: ['SL'], passenger_needs: [], budget_priorities: [], transfer_preferences: [],
      disruption_events: [{ id: 'SIM-DELAY-D103', type: 'delay', train_no: 'D103', delay_minutes: 150, label: 'Simulated delay', simulated: true }],
      data_notice: 'DEMO',
    }),
    createSession: vi.fn().mockResolvedValue(response({}, 'Tell me where and when you want to travel.')),
    getSession: vi.fn(),
    sendMessage: vi.fn().mockResolvedValue(response(withRecs, 'I found 3 eligible option(s).')),
    patchJourney: vi.fn().mockResolvedValue(response(withRecs, '')),
    recommendations: vi.fn(),
    select: vi.fn().mockResolvedValue(response({ ...withRecs, status: 'awaiting_confirmation', selected_option_id: rec.option.option_id }, 'You selected D103.')),
    confirm: vi.fn().mockResolvedValue(response({
      ...withRecs, status: 'confirmed', selected_option_id: rec.option.option_id,
      confirmation: { confirmation_id: 'RSP-TEST', confirmed_at: '', selected_option_id: rec.option.option_id, constraints_hash: 'abc', handoff: { module: 'smart_passenger_planner' }, superseded: false },
    }, 'Your journey plan is confirmed for handoff. No ticket has been booked.')),
    reassess: vi.fn(),
    cancel: vi.fn(),
    ...overrides,
  } as ApiClient
}

describe('App', () => {
  it('shows the demo notice, starts a session and an empty recommendation state', async () => {
    render(<App client={fakeClient()} />)
    expect(screen.getByRole('note')).toHaveTextContent(/DEMO DATA/)
    expect(await screen.findByText('Tell me where and when you want to travel.')).toBeInTheDocument()
    expect(screen.getByText(/Recommendations appear here/)).toBeInTheDocument()
    expect(screen.getByText(/Voice input is not supported/)).toBeInTheDocument()
  })

  it('runs the full flow: message → recommendations → select → confirm (no booking)', async () => {
    const client = fakeClient()
    const user = userEvent.setup()
    render(<App client={client} />)
    await screen.findByText('Tell me where and when you want to travel.')
    await user.type(screen.getByLabelText('Type your travel request'), 'from Coimbatore to Chennai before 9 am tomorrow')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(client.sendMessage).toHaveBeenCalledWith(baseState.session_id, 'from Coimbatore to Chennai before 9 am tomorrow', 'en')
    const card = await screen.findByRole('article')
    expect(within(card).getByText('Lowest cost')).toBeInTheDocument()
    expect(within(card).getByText(/not been verified/)).toBeInTheDocument()
    await user.click(within(card).getByRole('button', { name: 'Select this option' }))
    expect(await screen.findByText(/No ticket will be booked/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Confirm plan for handoff' }))
    expect(await screen.findByText(/RSP-TEST/)).toBeInTheDocument()
    expect(screen.getByText(/No ticket has been booked\. Assistance/)).toBeInTheDocument()
  })

  it('shows API errors with a retry for transient failures', async () => {
    const client = fakeClient({ sendMessage: vi.fn().mockRejectedValue(new ApiError(0, 'network_error', 'Cannot reach the planner service.')) })
    const user = userEvent.setup()
    render(<App client={client} />)
    await screen.findByText('Tell me where and when you want to travel.')
    await user.type(screen.getByLabelText('Type your travel request'), 'hello')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    // Passenger copy from the string table, never the client's developer text.
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Cannot reach RailSaathi. Check your connection and try again.')
    expect(alert).not.toHaveTextContent('planner service')
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })

  it('starts a new session when the old one expired', async () => {
    const client = fakeClient({ sendMessage: vi.fn().mockRejectedValue(new ApiError(410, 'session_expired', 'expired')) })
    const user = userEvent.setup()
    render(<App client={client} />)
    await screen.findByText('Tell me where and when you want to travel.')
    await user.type(screen.getByLabelText('Type your travel request'), 'hi')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(client.createSession).toHaveBeenCalledTimes(2))
    expect(await screen.findByText(/session expired/)).toBeInTheDocument()
  })

  it('switches the UI language to Tamil without restarting the session', async () => {
    const client = fakeClient()
    const user = userEvent.setup()
    render(<App client={client} />)
    await screen.findByText('Tell me where and when you want to travel.')
    await user.selectOptions(screen.getByLabelText('Language'), 'ta')
    expect(screen.getByRole('button', { name: 'அனுப்பு' })).toBeInTheDocument()
    expect(client.createSession).toHaveBeenCalledTimes(1)
  })

  it('edits a field through the summary form', async () => {
    const client = fakeClient()
    const user = userEvent.setup()
    render(<App client={client} />)
    await screen.findByText('Tell me where and when you want to travel.')
    await user.click(screen.getByRole('button', { name: 'Edit Passengers' }))
    const input = screen.getByRole('spinbutton', { name: 'Passengers' })
    await user.clear(input)
    await user.type(input, '3')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(client.patchJourney).toHaveBeenCalledWith(baseState.session_id, { passenger_count: 3 })
  })
})

describe('patch helpers', () => {
  it('maps editor values to API patches', () => {
    expect(toPatch('budget', { limit: '1500', strict: true, priority: '' })).toEqual({ budget_limit: 1500, budget_strict: true, budget_priority: null })
    expect(toPatch('origin', { place: '' })).toEqual({ origin: null })
    expect(RELAX_PATCHES.arrival_deadline).toEqual({ arrival_deadline: null })
  })
})
