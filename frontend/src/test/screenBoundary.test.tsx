// A lazy screen chunk that cannot be fetched (offline, or removed by a newer deploy) shows a reason and a reload
// button instead of unmounting the whole app.
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import type { ApiClient } from '../api/client'
import { ScreenBoundary } from '../components/ScreenBoundary'
import { MOBILE_STRINGS } from '../mobile/strings'
import { response } from './fixtures'

vi.mock('../mobile/screens/StationTour', () => {
  throw new TypeError('Failed to fetch dynamically imported module: /assets/StationTour-old.js')
})

const m = MOBILE_STRINGS.en

function client(): ApiClient {
  return {
    baseUrl: 'http://test',
    health: vi.fn().mockResolvedValue({ status: 'ok', api_version: '1', data_mode: 'demo', data_provider: { requested: 'demo', active: 'demo', reason: null }, ai: {} }),
    reference: vi.fn().mockResolvedValue({ places: [], classes: [], passenger_needs: [], budget_priorities: [], transfer_preferences: [], disruption_events: [], data_notice: '' }),
    createSession: vi.fn().mockResolvedValue(response({}, 'Hello')),
  } as unknown as ApiClient
}

describe('ScreenBoundary', () => {
  let quiet: ReturnType<typeof vi.spyOn>
  beforeEach(() => { quiet = vi.spyOn(console, 'error').mockImplementation(() => undefined) }) // React reports the caught error
  afterEach(() => quiet.mockRestore())

  it('a rejected lazy import of the tour shows the reason and a reload button; other screens still work', async () => {
    window.location.hash = '/tour?station=chennai_central'
    render(<App client={client()} />)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveAttribute('data-code', 'screen_load_failed')
    expect(alert).toHaveTextContent(m.errors.screenFailed)
    expect(screen.getByRole('button', { name: m.errors.reload })).toBeInTheDocument()

    act(() => { window.location.hash = '/home' })
    await waitFor(() => expect(screen.queryByText(m.errors.screenFailed)).not.toBeInTheDocument())
    expect(await screen.findByText('Popular Routes')).toBeInTheDocument()
  })

  it('reload button calls the reload handler; Tamil text is used in Tamil', async () => {
    const onReload = vi.fn()
    const Boom = () => { throw new Error('chunk') }
    const ta = MOBILE_STRINGS.ta.errors
    render(<ScreenBoundary message={ta.screenFailed} reloadLabel={ta.reload} onReload={onReload}><Boom /></ScreenBoundary>)
    expect(screen.getByRole('alert')).toHaveTextContent(ta.screenFailed)
    expect(ta.screenFailed).not.toBe(m.errors.screenFailed)
    await userEvent.setup().click(screen.getByRole('button', { name: ta.reload }))
    expect(onReload).toHaveBeenCalledTimes(1)
  })
})
