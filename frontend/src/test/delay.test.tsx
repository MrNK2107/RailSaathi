import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import { ApiError, type ApiClient } from '../api/client'
import type { DelayPrediction } from '../api/types'
import { response } from './fixtures'

const board = { station: { code: 'MAS', name: 'Chennai Central' }, window_start: '2026-10-10T10:00:00+05:30',
  window_end: '2026-10-10T12:00:00+05:30', neighbours_checked: [], complete: true, reason: null, departures: [],
  provenance: { mode: 'cached', source: 'RailRadar', as_of: '2026-10-10T09:45:00+05:30', note: 'n' } }

const NOTE = 'Modelled statistical estimate from historical records, not live data.'

const prediction = (over: Partial<DelayPrediction> = {}): DelayPrediction => ({
  train_number: '12658', station_code: 'MAS', train_class: 'Mail/Express', live_input_delay_minutes: 0,
  historical_mean_delay_minutes: 12, historical_scope: 'pair', predicted_delay_minutes: 10,
  on_time_probability: 0.37, on_time_threshold_minutes: 15, risk_level: 'LOW', model_version: '2026-10-01',
  mae_minutes: 6.4, baseline_mae_minutes: 7.1, basis: 'trained_model', insights: [],
  provenance: { mode: 'fallback', source: 'RailSaathi delay model', as_of: '2026-10-10T09:00:00+05:30', note: NOTE },
  ...over,
})

async function predict(result: DelayPrediction | Error) {
  window.location.hash = '/alerts'
  const c = {
    baseUrl: 'http://test',
    departures: vi.fn().mockResolvedValue(board),
    predictDelay: vi.fn(result instanceof Error ? () => Promise.reject(result) : () => Promise.resolve(result)),
    health: vi.fn().mockResolvedValue({ status: 'ok', api_version: '1', data_mode: 'demo', data_provider: { requested: 'demo', active: 'demo', reason: null }, ai: {} }),
    reference: vi.fn().mockResolvedValue({ places: [], classes: [], passenger_needs: [], budget_priorities: [], transfer_preferences: [], disruption_events: [], data_notice: '' }),
    createSession: vi.fn().mockResolvedValue(response({}, 'Hello')),
  } as unknown as ApiClient
  render(<App client={c} />)
  await waitFor(() => expect(screen.getByText('Delay Estimate')).toBeInTheDocument())
  await userEvent.click(screen.getByRole('button', { name: 'Predict Delay' }))
  return { c, el: await screen.findByTestId('delay-result') }
}

describe('Delay estimate result', () => {
  it('shows no delay figure, risk badge or fake confidence when there is no data', async () => {
    const { el } = await predict(prediction({
      predicted_delay_minutes: null, risk_level: null, on_time_probability: null, mae_minutes: null,
      model_version: 'history-only', basis: 'none',
    }))
    expect(el).toHaveTextContent('No historical data is available')
    expect(el).toHaveTextContent('No data')
    expect(el).not.toHaveTextContent('null')
    expect(el).not.toHaveTextContent('Delay Risk')
    expect(el).not.toHaveTextContent('Typical error')
    expect(el).not.toHaveTextContent('%')
  })

  it('omits the probability tile when the model gives none (history only)', async () => {
    const { el } = await predict(prediction({
      predicted_delay_minutes: 30, risk_level: 'MODERATE', on_time_probability: null, mae_minutes: null,
      basis: 'history_only', model_version: 'history-only',
    }))
    expect(el).toHaveTextContent('+30 min')
    expect(el).toHaveTextContent('Historical average only')
    expect(el).not.toHaveTextContent('%')
    expect(el).not.toHaveTextContent('Typical error')
  })

  it('shows the real on-time probability, never a default', async () => {
    const { el } = await predict(prediction())
    expect(el).toHaveTextContent('37%')
    expect(el).not.toHaveTextContent('88%')
  })

  it('takes the risk label from the backend risk_level, not from the minutes', async () => {
    // 10 minutes would be "low" by a client-side threshold; the backend said HIGH, so HIGH is shown.
    const { el } = await predict(prediction({ predicted_delay_minutes: 10, risk_level: 'HIGH' }))
    expect(el).toHaveTextContent('High Delay Risk')
    expect(el).not.toHaveTextContent('Low Delay Risk')
  })

  it('labels a moderate risk as moderate', async () => {
    const { el } = await predict(prediction({ predicted_delay_minutes: 30, risk_level: 'MODERATE' }))
    expect(el).toHaveTextContent('Moderate Delay Risk')
  })

  it('shows MAE, model version, basis and the provenance note', async () => {
    const { c, el } = await predict(prediction())
    expect(c.predictDelay).toHaveBeenCalledWith('12658', 'MAS')
    const basis = within(el).getByTestId('delay-basis')
    expect(basis).toHaveTextContent('Trained model')
    expect(basis).toHaveTextContent('Model 2026-10-01')
    expect(basis).toHaveTextContent('±6.4 min')
    const badge = within(el).getByTestId('provenance-badge')
    expect(badge).toHaveAttribute('data-mode', 'fallback')
    expect(badge).toHaveTextContent(NOTE)
  })

  it('shows the error envelope message when the estimate cannot be fetched', async () => {
    window.location.hash = '/alerts'
    const c = {
      baseUrl: 'http://test',
      departures: vi.fn().mockResolvedValue(board),
      predictDelay: vi.fn().mockRejectedValue(new ApiError(503, 'delay_model_unavailable', 'The delay estimate is not set up.')),
      health: vi.fn().mockResolvedValue({ status: 'ok', api_version: '1', data_mode: 'demo', data_provider: { requested: 'demo', active: 'demo', reason: null }, ai: {} }),
      reference: vi.fn().mockResolvedValue({ places: [], classes: [], passenger_needs: [], budget_priorities: [], transfer_preferences: [], disruption_events: [], data_notice: '' }),
      createSession: vi.fn().mockResolvedValue(response({}, 'Hello')),
    } as unknown as ApiClient
    render(<App client={c} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Predict Delay' }))
    const alert = await screen.findByText('The delay estimate is not set up.')
    expect(alert.closest('[data-mode="unavailable"]')).not.toBeNull()
    expect(screen.queryByTestId('delay-result')).not.toBeInTheDocument()
  })
})
