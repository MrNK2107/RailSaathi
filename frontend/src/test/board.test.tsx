import { render, screen, waitFor } from '@testing-library/react'
import App from '../App'
import type { ApiClient } from '../api/client'
import type { DepartureBoard } from '../api/types'
import { response } from './fixtures'

const prov = { mode: 'cached', source: 'RailRadar live API (third-party)', as_of: '2026-10-10T09:45:00+05:30', note: 'Built from cached results.' } as const

const board = (over: Partial<DepartureBoard> = {}): DepartureBoard => ({
  station: { code: 'MAS', name: 'Chennai Central' },
  window_start: '2026-10-10T10:00:00+05:30', window_end: '2026-10-10T12:00:00+05:30',
  neighbours_checked: [], complete: true, reason: null, provenance: prov,
  departures: [{ train_no: '12676', train_name: 'Kovai Express', scheduled_departure: '2026-10-10T10:30:00+05:30',
    towards: [{ code: 'CBE', name: 'Coimbatore Jn' }], delay_minutes: 12, cancelled: false, status_as_of: null }],
  ...over,
})

async function open(b: DepartureBoard) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => b }))
  window.location.hash = '/alerts'
  const c = {
    baseUrl: 'http://test',
    health: vi.fn().mockResolvedValue({ status: 'ok', api_version: '1', data_mode: 'demo', data_provider: { requested: 'demo', active: 'demo', reason: null }, ai: {} }),
    reference: vi.fn().mockResolvedValue({ places: [], classes: [], passenger_needs: [], budget_priorities: [], transfer_preferences: [], disruption_events: [], data_notice: '' }),
    createSession: vi.fn().mockResolvedValue(response({}, 'Hello')),
  } as unknown as ApiClient
  render(<App client={c} />)
  await waitFor(() => expect(screen.getByText('Departure Board')).toBeInTheDocument())
}

afterEach(() => vi.unstubAllGlobals())

describe('Departure board provenance', () => {
  it('shows a cached board with its mode, note and the coverage limit', async () => {
    await open(board())
    expect(await screen.findByText('Kovai Express')).toBeInTheDocument()
    expect(screen.getByTestId('provenance-badge')).toHaveAttribute('data-mode', 'cached')
    expect(screen.getByTestId('provenance-badge')).toHaveTextContent('Built from cached results.')
    expect(screen.getByText(/Only direct trains to nearby catalogue cities/)).toBeInTheDocument()
    expect(screen.queryByTestId('board-incomplete')).not.toBeInTheDocument()
  })

  it('marks a stale board as STALE', async () => {
    await open(board({ provenance: { ...prov, mode: 'stale', note: 'STALE: quota used up.' } }))
    await screen.findByText('Kovai Express')
    expect(screen.getByTestId('provenance-badge')).toHaveAttribute('data-mode', 'stale')
    expect(screen.getByTestId('provenance-badge')).toHaveTextContent('STALE')
  })

  it('warns when the board is incomplete', async () => {
    await open(board({ complete: false, provenance: { ...prov, note: 'INCOMPLETE: some queries failed.' } }))
    expect(await screen.findByTestId('board-incomplete')).toHaveTextContent('trains may be missing')
    expect(screen.getByTestId('provenance-badge')).toHaveTextContent('INCOMPLETE')
  })

  it('shows the unavailable reason and no departures', async () => {
    await open(board({ departures: [], complete: false, reason: 'The live data provider could not be reached.',
      provenance: { ...prov, mode: 'unavailable', note: 'The live data provider could not be reached.' } }))
    const el = await screen.findByRole('status')
    expect(el).toHaveAttribute('data-mode', 'unavailable')
    expect(el).toHaveTextContent('The live data provider could not be reached.')
    expect(screen.queryByText('Kovai Express')).not.toBeInTheDocument()
  })

  it('an empty board says only nearby catalogue cities were checked', async () => {
    await open(board({ departures: [] }))
    expect(await screen.findByText(/does not mean the station has no trains/)).toBeInTheDocument()
  })
})
