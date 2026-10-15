import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import App from '../App'
import { ApiError, type ApiClient } from '../api/client'
import type { RouteResult, StationDetails, StationInfo } from '../api/types'
import EmergencyHelpModal from '../components/EmergencyHelpModal'
import StationBlueprintModal from '../components/StationBlueprintModal'
import { MOBILE_STRINGS } from '../mobile/strings'
import { response } from './fixtures'

const m = MOBILE_STRINGS.en
const prov = { mode: 'cached' as const, source: 'RailSaathi station catalogue (schematic)', as_of: '2026-10-10T00:00:00+00:00', note: 'The layout is schematic: not surveyed, not to scale.' }

const details = (over: Partial<StationDetails> = {}): StationDetails => ({
  station: {
    station_id: 'chennai_central', station_name: 'Chennai Central', map: { image: 'map.png', width: 1000, height: 500 },
    nodes: [
      { id: 'ent_a', name: 'Wall Tax Road', type: 'entrance', position: [0.1, 0.5], step_free: 'unknown' },
      { id: 'platform_10', name: 'Platform 10', type: 'platform', position: [0.8, 0.5], step_free: 'unknown' },
    ],
    edges: [{ id: 'e1', from: 'ent_a', to: 'platform_10', path_type: 'walkway', step_free: 'unknown', geometry: [[0.1, 0.5], [0.8, 0.5]] }],
  },
  version: 'local', layout_basis: 'schematic', routing_enabled: true, provenance: prov, ...over,
})

const route = (over: Partial<RouteResult> = {}): RouteResult => ({
  status: 'ok', geometry: [[0.1, 0.5], [0.8, 0.5]],
  segments: [
    { edge_id: 'e1', path_type: 'walkway', step_free: 'verified' },
    { edge_id: 'e2', path_type: 'stairs', step_free: 'unknown' },
    { edge_id: 'e3', path_type: 'ramp', step_free: 'reported' },
  ],
  instructions: [
    { step: 1, text: 'Walk along the concourse', node_id: 'ent_a', edge_id: 'e1', distance_m: 120.4, distance_is_estimate: true },
    { step: 2, text: 'Take the stairs to the bridge', node_id: 'x', edge_id: 'e2', distance_m: null, distance_is_estimate: false },
    { step: 3, text: 'Use the ramp to the platform', node_id: 'platform_10', edge_id: 'e3', distance_m: 30, distance_is_estimate: false },
  ],
  distance_m: null, estimated_distance_m: 150, distance_basis: 'estimated_from_map_scale',
  estimated_duration_s: null, duration_assumption: null, accessibility_confidence: 'unverified', warnings: [],
  explanation: null, reason: null, along_the_way: [], provenance: prov, ...over,
})

const info = (): StationInfo => ({
  checked_on: '2026-10-10', disclaimer: 'Numbers collected from online references.', layout_basis: 'schematic',
  layout_note: 'Schematic layout, not surveyed.', provenance: prov, amenities: [{ name: 'Cloak room', detail: 'Luggage deposit.', mapped: false }],
  helplines: [
    { id: 'rail_madad_139', number: '139', label: 'Rail Madad', purpose: 'Security and medical help.', category: 'railway', priority: 1,
      sources: [{ name: 'DoT circular', url: 'https://dotws.cdot.in/x.pdf' }, { name: 'Odd source', url: 'javascript:alert(1)' }] },
    { id: 'rail_madad_web', number: null, url: 'https://railmadad.indianrailways.gov.in', label: 'Rail Madad web portal', purpose: 'Complaints.', category: 'railway', priority: 2, sources: [] },
  ],
})

function client(over: Record<string, unknown> = {}): ApiClient {
  return {
    baseUrl: 'http://test',
    station: vi.fn().mockResolvedValue(details()),
    stationInfo: vi.fn().mockResolvedValue(info()),
    stationRoute: vi.fn().mockResolvedValue(route()),
    stations: vi.fn().mockResolvedValue([{ station_id: 'chennai_central', station_name: 'Chennai Central', city: 'Chennai' }]),
    rakePosition: vi.fn(),
    health: vi.fn().mockResolvedValue({ status: 'ok', api_version: '1', data_mode: 'demo', data_provider: { requested: 'demo', active: 'demo', reason: null }, ai: {} }),
    reference: vi.fn().mockResolvedValue({ places: [], classes: [], passenger_needs: [], budget_priorities: [], transfer_preferences: [], disruption_events: [], data_notice: '' }),
    createSession: vi.fn().mockResolvedValue(response({}, 'Hello')),
    ...over,
  } as unknown as ApiClient
}

function Harness({ c, which }: { c: ApiClient; which: 'blueprint' | 'sos' }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>opener</button>
      <button type="button">outside</button>
      {which === 'blueprint'
        ? <StationBlueprintModal isOpen={open} onClose={() => setOpen(false)} client={c} m={m} stationId="chennai_central" initialDestination="platform_10" />
        : <EmergencyHelpModal isOpen={open} onClose={() => setOpen(false)} client={c} m={m} stationId="chennai_central" />}
    </>
  )
}

describe.each([['blueprint' as const, /Station blueprint and route/, 'Close'], ['sos' as const, /Emergency and station help/, 'Close']])(
  '%s modal dialog behaviour', (which, name, closeLabel) => {
    it('is a labelled modal dialog, traps focus, closes on Escape and restores focus', async () => {
      const user = userEvent.setup()
      render(<Harness c={client()} which={which} />)
      const opener = screen.getByRole('button', { name: 'opener' })
      await user.click(opener)
      const dialog = await screen.findByRole('dialog', { name })
      expect(dialog).toHaveAttribute('aria-modal', 'true')
      expect(within(dialog).getByRole('button', { name: closeLabel })).toBeInTheDocument()

      // Focus starts inside the dialog and Tab / Shift+Tab never leave it.
      expect(dialog).toContainElement(document.activeElement as HTMLElement)
      for (let i = 0; i < 12; i += 1) {
        await user.tab()
        expect(dialog).toContainElement(document.activeElement as HTMLElement)
      }
      for (let i = 0; i < 12; i += 1) {
        await user.tab({ shift: true })
        expect(dialog).toContainElement(document.activeElement as HTMLElement)
      }

      await user.keyboard('{Escape}')
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
      expect(opener).toHaveFocus()
    })

    it('the close button closes it', async () => {
      const user = userEvent.setup()
      render(<Harness c={client()} which={which} />)
      await user.click(screen.getByRole('button', { name: 'opener' }))
      await user.click(await screen.findByRole('button', { name: closeLabel }))
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
  })

describe('EmergencyHelpModal data', () => {
  it('shows helplines from the info API with sources and no hard-coded hospital text', async () => {
    const c = client()
    const user = userEvent.setup()
    render(<Harness c={c} which="sos" />)
    await user.click(screen.getByRole('button', { name: 'opener' }))
    const dialog = await screen.findByRole('dialog')
    await within(dialog).findByText('Rail Madad')
    expect(c.stationInfo).toHaveBeenCalledWith('chennai_central', expect.anything())
    expect(within(dialog).getByRole('link', { name: /Call 139/ })).toHaveAttribute('href', 'tel:139')
    expect(within(dialog).getByRole('link', { name: /Rail Madad web portal/ })).toHaveAttribute('href', 'https://railmadad.indianrailways.gov.in')
    expect(within(dialog).getByRole('link', { name: 'DoT circular' })).toHaveAttribute('href', 'https://dotws.cdot.in/x.pdf')
    // A non-https source is shown as plain text, never as a link.
    expect(within(dialog).queryByRole('link', { name: 'Odd source' })).not.toBeInTheDocument()
    expect(within(dialog).getByText(/Odd source/)).toBeInTheDocument()
    expect(within(dialog).getByText('Schematic layout, not surveyed.')).toBeInTheDocument()
    expect(within(dialog).getByTestId('provenance-badge')).toHaveAttribute('data-mode', 'cached')
    expect(dialog).not.toHaveTextContent(/Rajiv Gandhi|044-/)
  })

  it('names the station whose amenities and helplines are shown', async () => {
    const user = userEvent.setup()
    render(<Harness c={client()} which="sos" />)
    await user.click(screen.getByRole('button', { name: 'opener' }))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByRole('heading', { name: /Emergency and station help — Chennai Central/ })).toBeInTheDocument()
    expect(within(dialog).getByRole('heading', { name: /Station amenities — Chennai Central/ })).toBeInTheDocument()
  })

  it('falls back to the national numbers when the info API fails', async () => {
    const c = client({ stationInfo: vi.fn().mockRejectedValue(new ApiError(404, 'station_not_found', 'Station not found.')) })
    const user = userEvent.setup()
    render(<Harness c={c} which="sos" />)
    await user.click(screen.getByRole('button', { name: 'opener' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Call 139 (Rail Madad) or 112')
  })
})

describe('StationBlueprintModal route', () => {
  it('shows the schematic notice, distance as an estimate and step-free labels as returned', async () => {
    const c = client()
    const user = userEvent.setup()
    render(<Harness c={c} which="blueprint" />)
    await user.click(screen.getByRole('button', { name: 'opener' }))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText(/Schematic layout\./)).toBeInTheDocument()
    await waitFor(() => expect(c.stationRoute).toHaveBeenCalled())
    expect(c.stationRoute).toHaveBeenCalledWith(expect.objectContaining({ source: 'ent_a', destination: 'platform_10' }), expect.anything())
    expect(await within(dialog).findByText(/approx\. 150 m/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('tab', { name: 'Directions' }))
    const steps = await within(dialog).findAllByRole('listitem')
    expect(steps[0]).toHaveTextContent('Step-free: verified')
    expect(steps[1]).toHaveTextContent('Step-free: unknown')
    expect(steps[2]).toHaveTextContent('Step-free: reported, not verified')
    expect(steps[0]).toHaveTextContent('approx. 120 m')
    expect(within(dialog).queryByText(/100%/)).not.toBeInTheDocument()
  })
})

async function openNavigation(c: ApiClient) {
  window.location.hash = '/navigation'
  const user = userEvent.setup()
  render(<App client={c} />)
  await waitFor(() => expect(c.createSession).toHaveBeenCalled())
  return user
}

describe('Wayfinder screen states', () => {
  it('coach position is unknown until a composition is known, then comes from the backend', async () => {
    const c = client({
      rakePosition: vi.fn().mockResolvedValue({
        total_coaches: 5, total_rake_length_meters: 118,
        coaches: [], target_coach_info: { index: 3, coach_code: 'B1', coach_type: 'AC 3-Tier (3A)', distance_from_engine_meters: 46, platform_section: 'Middle' },
      }),
    })
    const user = await openNavigation(c)
    expect(await screen.findByTestId('coach-unknown')).toHaveTextContent('Coach position: unknown')
    expect(screen.queryByTestId('coach-position')).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('Coach order'), 'ENG-A1-B1-B2-S1')
    await user.type(screen.getByLabelText('Your coach'), 'B1')
    await user.click(screen.getByRole('button', { name: 'Find coach position' }))
    expect(c.rakePosition).toHaveBeenCalledWith('ENG-A1-B1-B2-S1', 'B1')
    expect(await screen.findByTestId('coach-position')).toHaveTextContent('Coach B1 is number 3 of 5 from the engine, about 46 m')
    expect(screen.queryByTestId('coach-unknown')).not.toBeInTheDocument()
  })

  it('a coach missing from the entered order stays unknown', async () => {
    const c = client({ rakePosition: vi.fn().mockResolvedValue({ total_coaches: 3, coaches: [], target_coach_info: null }) })
    const user = await openNavigation(c)
    await user.type(await screen.findByLabelText('Coach order'), 'ENG-A1-B1')
    await user.type(screen.getByLabelText('Your coach'), 'S9')
    await user.click(screen.getByRole('button', { name: 'Find coach position' }))
    expect(await screen.findByTestId('coach-unknown')).toHaveTextContent('That coach is not in the order you entered.')
  })

  it('shows step-free labels per step and the schematic notice for a routed station', async () => {
    const c = client()
    const user = await openNavigation(c)
    await user.selectOptions(await screen.findByLabelText('To platform or facility'), 'platform_10')
    await user.click(await screen.findByRole('tab', { name: /Step-by-Step/ }))
    const items = await screen.findAllByRole('listitem')
    expect(items.some((li) => li.textContent?.includes('Step-free: verified'))).toBe(true)
    expect(items.some((li) => li.textContent?.includes('Step-free: reported, not verified'))).toBe(true)
    expect(screen.getAllByText(/Schematic layout\./).length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: /Start Navigation/ })).not.toBeInTheDocument()
  })

  it('untraced station: shows the unavailable notice up front, no pickers, no route request, map kept', async () => {
    const c = client({ station: vi.fn().mockResolvedValue(details({ routing_enabled: false })) })
    const user = await openNavigation(c)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(m.navigation.routingUnavailable)
    expect(screen.queryByLabelText('To platform or facility')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Walking preference')).not.toBeInTheDocument()
    expect(screen.queryByText(/Choose where you are entering/)).not.toBeInTheDocument()
    expect(screen.getByRole('img', { name: /Station map/ })).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: /Step-by-Step/ }))
    expect(c.stationRoute).not.toHaveBeenCalled()
  })

  it('untraced station in the blueprint modal: notice, no pickers, no route request', async () => {
    const c = client({ station: vi.fn().mockResolvedValue(details({ routing_enabled: false })) })
    const user = userEvent.setup()
    render(<Harness c={c} which="blueprint" />)
    await user.click(screen.getByRole('button', { name: 'opener' }))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(m.navigation.routingUnavailable)
    expect(within(dialog).queryByLabelText('To platform or facility')).not.toBeInTheDocument()
    expect(c.stationRoute).not.toHaveBeenCalled()
  })

  it('a routing_unavailable error from the API shows the backend message', async () => {
    const msg = 'Step-by-step directions are not available for this station.'
    const c = client({ stationRoute: vi.fn().mockRejectedValue(new ApiError(503, 'routing_unavailable', msg)) })
    const user = await openNavigation(c)
    await user.selectOptions(await screen.findByLabelText('To platform or facility'), 'platform_10')
    expect(await screen.findByRole('alert')).toHaveTextContent(msg)
  })

  it('no_route explains why instead of drawing a route', async () => {
    const c = client({ stationRoute: vi.fn().mockResolvedValue(route({ status: 'no_route', segments: [], instructions: [], geometry: [], explanation: 'No verified step-free route exists.' })) })
    const user = await openNavigation(c)
    await user.selectOptions(await screen.findByLabelText('To platform or facility'), 'platform_10')
    expect(await screen.findByText('No verified step-free route exists.')).toBeInTheDocument()
    expect(screen.getByText('No route found')).toBeInTheDocument()
  })
})
