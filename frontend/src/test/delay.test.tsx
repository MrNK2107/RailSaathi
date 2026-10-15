import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import type { ApiClient } from '../api/client'
import { response } from './fixtures'

const board = { station: { code: 'MAS', name: 'Chennai Central' }, window_start: '2026-10-10T10:00:00+05:30',
  window_end: '2026-10-10T12:00:00+05:30', neighbours_checked: [], complete: true, reason: null, departures: [],
  provenance: { mode: 'cached', source: 'RailRadar', as_of: '2026-10-10T09:45:00+05:30', note: 'n' } }

async function predict(result: object) {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({
    ok: true, json: async () => (String(url).includes('/predict/delay') ? result : board),
  })))
  window.location.hash = '/alerts'
  const c = {
    baseUrl: 'http://test',
    health: vi.fn().mockResolvedValue({ status: 'ok', api_version: '1', data_mode: 'demo', data_provider: { requested: 'demo', active: 'demo', reason: null }, ai: {} }),
    reference: vi.fn().mockResolvedValue({ places: [], classes: [], passenger_needs: [], budget_priorities: [], transfer_preferences: [], disruption_events: [], data_notice: '' }),
    createSession: vi.fn().mockResolvedValue(response({}, 'Hello')),
  } as unknown as ApiClient
  render(<App client={c} />)
  await waitFor(() => expect(screen.getByText('Delay Estimate')).toBeInTheDocument())
  await userEvent.click(screen.getByRole('button', { name: 'Predict Delay' }))
  return screen.findByTestId('delay-result')
}

afterEach(() => vi.unstubAllGlobals())

describe('Delay estimate result', () => {
  it('shows no delay figure, risk badge or fake confidence when there is no data', async () => {
    const el = await predict({ train_number: '12658', predicted_delay_minutes: null, risk_level: null, on_time_probability: null })
    expect(el).toHaveTextContent('No historical data is available')
    expect(el).not.toHaveTextContent('null')
    expect(el).not.toHaveTextContent('Low Delay Risk')
    expect(el).not.toHaveTextContent('88%')
  })

  it('omits the probability tile when the model gives none (history only)', async () => {
    const el = await predict({ train_number: '12658', predicted_delay_minutes: 30, risk_level: 'MODERATE', on_time_probability: null })
    expect(el).toHaveTextContent('+30 mins')
    expect(el).toHaveTextContent('High Delay Risk')
    expect(el).not.toHaveTextContent('%')
  })

  it('shows the real on-time probability, never a default', async () => {
    const el = await predict({ train_number: '12658', predicted_delay_minutes: 10, risk_level: 'LOW', on_time_probability: 0.37 })
    expect(el).toHaveTextContent('37%')
    expect(el).not.toHaveTextContent('88%')
  })
})
