import { render, screen, waitFor } from '@testing-library/react'
import App from '../App'
import { ApiError, type ApiClient } from '../api/client'
import type { DepartureBoard } from '../api/types'
import { response } from './fixtures'

const prov = { mode: 'cached', source: 'RailRadar live API (third-party)', as_of: '2026-10-10T09:45:00+05:30', note: 'Built from cached results.' } as const

const board = (over: Partial<DepartureBoard> = {}): DepartureBoard => ({
  station: { code: 'MAS', name: 'Chennai Central' },
  window_start: '2026-10-10T10:00:00+05:30', window_end: '2026-10-10T12:00:00+05:30',
  neighbours_checked: [{ code: 'ED', name: 'Erode Jn' }], complete: true, reason: null, provenance: prov,
  departures: [{ train_no: '12676', train_name: 'Kovai Express', scheduled_departure: '2026-10-10T10:30:00+05:30',
    towards: [{ code: 'CBE', name: 'Coimbatore Jn' }], delay_minutes: 12, cancelled: false, status_as_of: null }],
  ...over,
})

async function open(b: DepartureBoard | Error) {
  window.location.hash = '/alerts'
  const c = {
    baseUrl: 'http://test',
    departures: vi.fn(b instanceof Error ? () => Promise.reject(b) : () => Promise.resolve(b)),
    health: vi.fn().mockResolvedValue({ status: 'ok', api_version: '1', data_mode: 'demo', data_provider: { requested: 'demo', active: 'demo', reason: null }, ai: {} }),
    reference: vi.fn().mockResolvedValue({ places: [], classes: [], passenger_needs: [], budget_priorities: [], transfer_preferences: [], disruption_events: [], data_notice: '' }),
    createSession: vi.fn().mockResolvedValue(response({}, 'Hello')),
  } as unknown as ApiClient
  render(<App client={c} />)
  await waitFor(() => expect(screen.getByText('Departure Board')).toBeInTheDocument())
  return c
}

describe('Departure board provenance', () => {
  it('shows a cached board with its mode, note and the coverage limit', async () => {
    await open(board())
    expect(await screen.findByText('Kovai Express')).toBeInTheDocument()
    expect(screen.getByTestId('provenance-badge')).toHaveAttribute('data-mode', 'cached')
    expect(screen.getByTestId('provenance-badge')).toHaveTextContent('Built from cached results.')
    expect(screen.getByText(/Only direct trains to nearby catalogue cities/)).toBeInTheDocument()
    expect(screen.queryByTestId('board-incomplete')).not.toBeInTheDocument()
  })

  it('an NTES board says it is the station board via an unofficial client, not a nearby-cities sample', async () => {
    await open(board({ neighbours_checked: [],
      provenance: { mode: 'live', source: 'NTES (unofficial client)', as_of: '2026-10-10T09:55:00+05:30', note: 'Station board as published by NTES.' } }))
    expect(await screen.findByText('Kovai Express')).toBeInTheDocument()
    expect(screen.getByTestId('board-coverage')).toHaveTextContent('unofficial client')
    expect(screen.queryByText(/nearby catalogue cities/)).not.toBeInTheDocument()
    expect(screen.getByTestId('provenance-badge')).toHaveTextContent('NTES (unofficial client)')
  })

  it('a demo board claims no coverage it does not have', async () => {
    await open(board({ neighbours_checked: [], provenance: { ...prov, mode: 'demo', source: 'RailSaathi sample timetable' } }))
    expect(await screen.findByText('Kovai Express')).toBeInTheDocument()
    expect(screen.queryByTestId('board-coverage')).not.toBeInTheDocument()
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

  it('shows the as-of time and the typed client is asked for the selected station', async () => {
    const c = await open(board())
    await screen.findByText('Kovai Express')
    expect(c.departures).toHaveBeenCalledWith('MAS', expect.anything())
    expect(screen.getByTestId('provenance-badge')).toHaveTextContent(/10 Oct.*09:45 IST/)
  })

  it('shows the error envelope message when the board cannot be fetched', async () => {
    await open(new ApiError(404, 'unknown_station', "This station is not in RailSaathi's station catalogue."))
    const el = await screen.findByRole('status')
    expect(el).toHaveAttribute('data-mode', 'unavailable')
    expect(el).toHaveTextContent("This station is not in RailSaathi's station catalogue.")
    expect(screen.queryByText('Kovai Express')).not.toBeInTheDocument()
  })
})

describe('Departure board in Tamil (review fix: coded NTES notes)', () => {
  const ntes = (over: Partial<DepartureBoard['provenance']> = {}) => ({
    mode: 'cached' as const, source: 'NTES (unofficial client)', as_of: '2026-10-10T09:55:00+05:30',
    note: 'CACHED: a recent NTES response reused from cache (fetched at the time shown). Live data from NTES ...',
    note_codes: ['ntes_cached', 'ntes_board', 'ntes'], ...over,
  })

  async function openTa(b: DepartureBoard) {
    window.sessionStorage.setItem('railsaathi.session.v1', JSON.stringify({ language: 'ta', session: null }))
    window.location.hash = '/alerts'
    const c = {
      baseUrl: 'http://test',
      departures: vi.fn(() => Promise.resolve(b)),
      health: vi.fn().mockResolvedValue({ status: 'ok', api_version: '1', data_mode: 'live', data_provider: { requested: 'ntes', active: 'ntes', reason: null }, ai: {} }),
      reference: vi.fn().mockResolvedValue({ places: [], classes: [], passenger_needs: [], budget_priorities: [], transfer_preferences: [], disruption_events: [], data_notice: '' }),
      createSession: vi.fn().mockResolvedValue(response({ language: 'ta' }, 'வணக்கம்')),
    } as unknown as ApiClient
    render(<App client={c} />)
    return c
  }

  afterEach(() => window.sessionStorage.clear())

  it('renders the NTES note and source in Tamil, with no English paragraph', async () => {
    await openTa(board({ neighbours_checked: [], provenance: ntes() }))
    expect(await screen.findByText('Kovai Express')).toBeInTheDocument()
    const badge = screen.getByTestId('provenance-badge')
    expect(badge).toHaveTextContent('சேமித்தது: சமீபத்திய NTES பதில்')
    expect(badge).toHaveTextContent('NTES (அதிகாரப்பூர்வமற்ற கிளையன்ட்)')
    expect(badge.textContent).not.toMatch(/unofficial client|Live data from NTES|CACHED: a recent/)
    expect(badge.getAttribute('title')).not.toMatch(/unofficial client/)
  })

  it('renders an unavailable board reason from its code in Tamil', async () => {
    await openTa(board({ departures: [], complete: false, reason: 'The live data provider could not be reached.',
      provenance: ntes({ mode: 'unavailable', note: 'The live data provider could not be reached.', note_codes: ['live_unavailable'] }) }))
    const el = await screen.findByRole('status')
    expect(el).toHaveTextContent('நேரடி தரவு வழங்குநரை அணுக முடியவில்லை.')
    expect(el.textContent).not.toMatch(/could not be reached|unofficial client/)
  })

  it('falls back to the English note for an unknown code', async () => {
    await openTa(board({ neighbours_checked: [], provenance: ntes({ note: 'Some new English note.', note_codes: ['ntes_future_code'] }) }))
    expect(await screen.findByText('Kovai Express')).toBeInTheDocument()
    expect(screen.getByTestId('provenance-badge')).toHaveTextContent('Some new English note.')
  })
})
