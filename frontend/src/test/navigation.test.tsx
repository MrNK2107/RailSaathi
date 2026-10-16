// Station navigation screen against a mocked ApiClient: auto-routing, swap, preferences, Map / Steps agreement,
// turn-by-turn, zoom, simulated closures (sent with the route request), active closures, relax chips, errors and
// the journey-code -> catalogue station lookup.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import { ApiError, createApiClient, type ApiClient } from '../api/client'
import type { RouteResult, StationDetails, StationDisruption } from '../api/types'
import { bounds, formatMinutes, routeDistance } from '../navigation/format'
import { saveState } from '../mobile/persist'
import { MOBILE_STRINGS } from '../mobile/strings'
import { baseState, rec, response, withRecs } from './fixtures'

const n = MOBILE_STRINGS.en.navigation
const ta = MOBILE_STRINGS.ta.navigation
const prov = { mode: 'cached' as const, source: 'RailSaathi station catalogue (schematic)', as_of: '2026-10-10T00:00:00+00:00', note: 'Schematic.' }

const details = (over: Partial<StationDetails> = {}, id = 'test_town', name = 'Test Town'): StationDetails => ({
  station: {
    station_id: id, station_name: name, map: { image: 'map.png', width: 1000, height: 1000 },
    nodes: [
      { id: 'ent', name: 'Main Gate', type: 'entrance', position: [0.1, 0.1], step_free: 'unknown' },
      { id: 'j1', name: 'Junction 1', type: 'junction', position: [0.5, 0.1], step_free: 'unknown' },
      { id: 'p1', name: 'Platform 1', type: 'platform', position: [0.5, 0.9], step_free: 'unknown' },
      { id: 'wc', name: 'Toilet', type: 'toilet', position: [0.9, 0.9], step_free: 'unknown' },
    ],
    edges: [
      { id: 'e1', from: 'ent', to: 'j1', path_type: 'walkway', step_free: 'unknown', geometry: [[0.1, 0.1], [0.3, 0.12], [0.5, 0.1]] },
      { id: 'e2', from: 'j1', to: 'p1', path_type: 'walkway', step_free: 'unknown', geometry: [[0.5, 0.1], [0.5, 0.9]] },
      { id: 'e3', from: 'p1', to: 'wc', path_type: 'stairs', step_free: 'unknown', geometry: [[0.5, 0.9], [0.9, 0.9]] },
    ],
  },
  version: 'local', layout_basis: 'schematic', routing_enabled: true, provenance: prov, ...over,
})

const okRoute: RouteResult = {
  status: 'ok', node_ids: ['ent', 'j1', 'p1'], edge_ids: ['e1', 'e2'],
  geometry: [[0.1, 0.1], [0.3, 0.12], [0.5, 0.1], [0.5, 0.9]],
  segments: [
    { edge_id: 'e1', from_node: 'ent', to_node: 'j1', geometry: [[0.1, 0.1], [0.3, 0.12], [0.5, 0.1]], path_type: 'walkway', level_change: 0, step_free: 'unknown' },
    { edge_id: 'e2', from_node: 'j1', to_node: 'p1', geometry: [[0.5, 0.1], [0.5, 0.9]], path_type: 'walkway', level_change: 0, step_free: 'reported' },
  ],
  distance_m: null, estimated_distance_m: 160, distance_basis: 'estimated_from_map_scale', estimated_duration_s: 133,
  duration_assumption: 'Assumes an average walking speed of 1.2 m/s; not measured.', accessibility_confidence: 'not_applicable',
  warnings: ['2 of 2 pathway(s) are not verified on site.'],
  instructions: [
    { step: 1, text: 'Start at Main Gate and walk east to Junction 1.', node_id: 'ent', edge_id: 'e1', distance_m: 40, distance_is_estimate: true },
    { step: 2, text: 'Turn right at Junction 1 and walk south to Platform 1.', node_id: 'j1', edge_id: 'e2', distance_m: 120, distance_is_estimate: true },
    { step: 3, text: 'Arrive at Platform 1.', node_id: 'p1', edge_id: null, distance_m: null, distance_is_estimate: false },
  ],
  reason: null, explanation: null, provenance: prov, previous_route_blocked: false, simulated_closures_applied: [],
  along_the_way: [{ node_id: 'wc', name: 'Toilet', type: 'toilet', on_route: false, distance_from_route_m: 12, progress: 0.9, step_free: 'unknown' }],
}
const noRoute: RouteResult = {
  ...okRoute, status: 'no_route', node_ids: [], edge_ids: [], geometry: [], segments: [], instructions: [], along_the_way: [],
  reason: 'accessibility_constraints', explanation: 'No step-free route: every path to Toilet uses stairs.',
}
const NO_PREFS = { avoid_stairs: false, wheelchair: false, require_verified_accessibility: false }
const lastRoute = (c: ApiClient) => {
  const calls = vi.mocked(c.stationRoute).mock.calls
  return calls[calls.length - 1][0]
}
/** A route for whatever endpoints were asked for, so swaps and "Go here" are visible in the summary. */
const echoRoute = vi.fn(async (body: { source: string; destination: string }) => ({
  ...okRoute, node_ids: [body.source, 'j1', body.destination],
}))

function client(over: Record<string, unknown> = {}, state: Partial<typeof baseState> = {}): ApiClient {
  return {
    baseUrl: 'http://test',
    stations: vi.fn().mockResolvedValue([
      { station_id: 'test_town', station_name: 'Test Town', city: null, station_code: 'TTN' },
      { station_id: 'chennai_central', station_name: 'Chennai Central', city: 'Chennai', station_code: 'MAS' },
    ]),
    station: vi.fn().mockImplementation(async (id: string) => (id === 'test_town' ? details() : details({}, id, 'Chennai Central'))),
    stationInfo: vi.fn().mockRejectedValue(new ApiError(404, 'station_not_found', 'nope')),
    disruptions: vi.fn().mockResolvedValue([]),
    stationRoute: echoRoute,
    clientConfig: vi.fn().mockResolvedValue({ google_maps_browser_key: null, features: { ar_guidance_stations: [], simulate_closures: true } }),
    rakePosition: vi.fn(),
    health: vi.fn().mockResolvedValue({ status: 'ok', api_version: '1', data_mode: 'demo', data_provider: { requested: 'demo', active: 'demo', reason: null }, ai: {} }),
    reference: vi.fn().mockResolvedValue({ places: [], classes: [], passenger_needs: [], budget_priorities: [], transfer_preferences: [], disruption_events: [], data_notice: '' }),
    createSession: vi.fn().mockResolvedValue(response(state, 'Hello')),
    ...over,
  } as unknown as ApiClient
}

beforeEach(() => {
  echoRoute.mockClear()
  window.location.hash = '/navigation'
})

async function openNav(c: ApiClient = client()) {
  const user = userEvent.setup()
  render(<App client={c} />)
  await screen.findByRole('combobox', { name: n.pickTo })
  return user
}

async function routeTo(user: ReturnType<typeof userEvent.setup>, id: string) {
  await user.selectOptions(screen.getByRole('combobox', { name: n.pickTo }), id)
  await screen.findByTestId('route-line')
}

describe('format helpers', () => {
  it('rounds durations up to whole minutes and prefers measured distances', () => {
    expect(formatMinutes(133)).toBe(2)
    expect(formatMinutes(10)).toBe(1)
    expect(formatMinutes(null)).toBeNull()
    expect(routeDistance(okRoute)).toBe(160)
    expect(routeDistance({ ...okRoute, distance_m: 150 })).toBe(150)
  })

  it('computes the bounding box of a polyline', () => {
    expect(bounds(okRoute.geometry)).toEqual({ minX: 0.1, minY: 0.1, maxX: 0.5, maxY: 0.9 })
    expect(bounds([])).toBeNull()
  })
})

describe('client.disruptions', () => {
  it('reads GET /api/disruptions/{station_id} and surfaces a 503 as disruptions_unavailable', async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(new Response('[]', { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: { code: 'disruptions_unavailable', message: 'Current closure information is unavailable.' } }), { status: 503 }))
    const api = createApiClient({ baseUrl: 'http://x', fetchImpl, retries: 0 })
    await expect(api.disruptions('chennai_central')).resolves.toEqual([])
    expect(fetchImpl.mock.calls[0][0]).toBe('http://x/api/disruptions/chennai_central')
    await expect(api.disruptions('chennai_central')).rejects.toMatchObject({ status: 503, code: 'disruptions_unavailable' })
  })
})

describe('Station Navigation screen', () => {
  it('lists real places (no junctions), routes as soon as a destination is chosen and draws the stored polyline', async () => {
    const c = client()
    const user = await openNav(c)
    expect(screen.getByRole('heading', { name: n.title })).toBeInTheDocument()
    const to = screen.getByRole('combobox', { name: n.pickTo })
    expect(within(to).queryByText('Junction 1')).not.toBeInTheDocument()
    expect(screen.getByText(n.emptyMap)).toBeInTheDocument()
    expect(c.stationRoute).not.toHaveBeenCalled()
    await routeTo(user, 'p1')
    expect(c.stationRoute).toHaveBeenCalledWith(
      { station_id: 'test_town', source: 'ent', destination: 'p1', preferences: NO_PREFS, apply_disruptions: true },
      { signal: expect.any(AbortSignal) })
    expect(screen.getByTestId('route-line').getAttribute('points')).toBe('100,100 300,120 500,100 500,900')
    expect(screen.getByTestId('source-pin')).toBeInTheDocument()
    expect(screen.getByTestId('destination-pin')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Station map with the route from Main Gate to Platform 1' })).toBeInTheDocument()
    const summary = screen.getByLabelText(n.summary)
    expect(summary).toHaveTextContent('2 min')
    expect(summary).toHaveTextContent('160 m')
    expect(summary).toHaveTextContent('Shortest route')
    expect(summary).toHaveTextContent('(estimate)')
    expect(summary).toHaveTextContent('Assumes an average walking speed of 1.2 m/s')
    expect(summary).toHaveTextContent(n.routeStepFree.not_applicable)
    expect(summary).toHaveTextContent('2 of 2 pathway(s) are not verified on site.')
    expect(screen.getByText(/not yet verified on site/)).toBeInTheDocument()
    expect(screen.getByText(/Schematic layout\./)).toBeInTheDocument()
    expect(screen.getAllByTestId('provenance-badge').length).toBeGreaterThan(0)
    expect(c.disruptions).toHaveBeenCalledWith('test_town', expect.anything())
  })

  it('recalculates when either endpoint changes and when the endpoints are swapped', async () => {
    const c = client()
    const user = await openNav(c)
    await routeTo(user, 'p1')
    await user.selectOptions(screen.getByRole('combobox', { name: n.pickTo }), 'wc')
    await waitFor(() => expect(lastRoute(c)).toMatchObject({ source: 'ent', destination: 'wc' }))
    await user.click(screen.getByRole('button', { name: n.swap }))
    await waitFor(() => expect(lastRoute(c)).toMatchObject({ source: 'wc', destination: 'ent' }))
    expect(screen.getByRole('combobox', { name: n.pickFrom })).toHaveValue('wc')
    expect(screen.getByRole('combobox', { name: n.pickTo })).toHaveValue('ent')
    await waitFor(() => expect(screen.getByLabelText(n.summary)).toHaveTextContent('Toilet → Main Gate'))
  })

  it('"Go here" on an along-the-way place reroutes to it', async () => {
    const c = client()
    const user = await openNav(c)
    await routeTo(user, 'p1')
    const along = screen.getByRole('region', { name: n.alongWay })
    expect(along).toHaveTextContent('Toilet · about 12 m off the route')
    await user.click(within(along).getByRole('button', { name: n.goHere }))
    await waitFor(() => expect(lastRoute(c)).toMatchObject({ source: 'ent', destination: 'wc' }))
    expect(screen.getByRole('combobox', { name: n.pickTo })).toHaveValue('wc')
  })

  it('flags identical endpoints as invalid input instead of calling the engine', async () => {
    const c = client()
    const user = await openNav(c)
    await routeTo(user, 'p1')
    echoRoute.mockClear()
    await user.selectOptions(screen.getByRole('combobox', { name: n.pickFrom }), 'p1')
    expect(await screen.findAllByText(n.sameEndpoints)).not.toHaveLength(0)
    expect(screen.queryByTestId('route-line')).not.toBeInTheDocument()
    expect(c.stationRoute).not.toHaveBeenCalled()
  })

  it('pre-selects wheelchair routing when the passenger asked for a wheelchair', async () => {
    const c = client({}, { journey: { ...baseState.journey, passenger_needs: ['wheelchair'] } })
    const user = await openNav(c)
    await waitFor(() => expect(screen.getByRole('button', { name: n.wheelchair })).toHaveAttribute('aria-pressed', 'true'))
    expect(screen.getByRole('button', { name: n.avoidStairs })).toHaveAttribute('aria-pressed', 'true')
    await routeTo(user, 'p1')
    expect(lastRoute(c).preferences).toMatchObject({ wheelchair: true, avoid_stairs: true })
    expect(screen.getByLabelText(n.summary)).toHaveTextContent(n.shortestPrefs)
  })

  it('toggling an accessibility preference recalculates with the new constraints', async () => {
    const c = client()
    const user = await openNav(c)
    await routeTo(user, 'p1')
    await user.click(screen.getByRole('button', { name: n.avoidStairs }))
    await waitFor(() => expect(lastRoute(c).preferences).toEqual({ ...NO_PREFS, avoid_stairs: true }))
    await user.click(screen.getByRole('button', { name: n.verifiedOnly }))
    await waitFor(() => expect(lastRoute(c).preferences).toEqual({ ...NO_PREFS, avoid_stairs: true, require_verified_accessibility: true }))
  })

  it('keeps the Map and Step-by-Step views on the same route', async () => {
    const c = client()
    const user = await openNav(c)
    await routeTo(user, 'p1')
    await user.click(screen.getByRole('tab', { name: n.steps }))
    const steps = within(screen.getByRole('list', { name: n.steps })).getAllByRole('listitem')
    expect(steps.map((s) => s.querySelector('span > span')?.textContent)).toEqual([
      'Start at Main Gate and walk east to Junction 1.',
      'Turn right at Junction 1 and walk south to Platform 1.',
      'Arrive at Platform 1.',
    ])
    expect(steps[0]).toHaveTextContent('approx. 40 m')
    expect(steps[1]).toHaveTextContent(n.stepFree.reported)
    expect(screen.queryByTestId('route-line')).not.toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: n.mapView }))
    expect(screen.getByTestId('route-line').getAttribute('points')).toBe('100,100 300,120 500,100 500,900')
    expect(c.stationRoute).toHaveBeenCalledTimes(1)
  })

  it('steps through the instructions in order and can exit navigation', async () => {
    const user = await openNav()
    await routeTo(user, 'p1')
    expect(screen.queryByTestId('current-step-marker')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Start Navigation/ }))
    const status = () => screen.getByTestId('current-step')
    expect(status()).toHaveTextContent('Step 1 of 3')
    expect(status()).toHaveTextContent('Start at Main Gate')
    expect(status()).toHaveTextContent('not your real location')
    expect(screen.getByTestId('current-step-marker')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Next step/ }))
    expect(status()).toHaveTextContent('Step 2 of 3')
    await user.click(screen.getByRole('tab', { name: n.steps }))
    expect(screen.getByRole('listitem', { current: 'step' })).toHaveTextContent('Turn right at Junction 1')
    await user.click(screen.getByRole('button', { name: n.prevStep }))
    expect(status()).toHaveTextContent('Step 1 of 3')
    await user.click(screen.getByRole('button', { name: /Next step/ }))
    await user.click(screen.getByRole('button', { name: /Next step/ }))
    expect(status()).toHaveTextContent('Step 3 of 3')
    await user.click(screen.getByRole('button', { name: /Finish/ }))
    expect(screen.queryByTestId('current-step')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Start Navigation/ })).toBeInTheDocument()
  })

  it('zoom controls change the map scale within bounds', async () => {
    const user = await openNav()
    const map = screen.getByTestId('station-map')
    expect(map).toHaveAttribute('data-zoom', '1.6')
    await user.click(screen.getByRole('button', { name: n.zoomIn }))
    await user.click(screen.getByRole('button', { name: n.zoomIn }))
    expect(map).toHaveAttribute('data-zoom', '3.2')
    expect(screen.getByRole('button', { name: n.zoomIn })).toBeDisabled()
    for (let i = 0; i < 3; i += 1) await user.click(screen.getByRole('button', { name: n.zoomOut }))
    expect(map).toHaveAttribute('data-zoom', '1')
    expect(screen.getByRole('button', { name: n.zoomOut })).toBeDisabled()
    expect(screen.getByRole('img', { name: n.north })).toBeInTheDocument()
  })

  it('a simulated closure is sent with the route request, reroutes and explains it once', async () => {
    const c = client()
    const user = await openNav(c)
    await routeTo(user, 'p1')
    echoRoute.mockResolvedValueOnce({ ...okRoute, previous_route_blocked: true, simulated_closures_applied: ['e2'],
      warnings: ['SIMULATED DISRUPTION: your previous route is blocked at e2. Showing an alternative route.'] })
    const sim = screen.getByTestId('closure-simulator')
    expect(sim).toHaveTextContent(n.simulatedTag)
    await user.selectOptions(within(sim).getByRole('combobox', { name: n.closure }), 'e2')
    await user.click(within(sim).getByRole('button', { name: n.closeBtn }))
    await waitFor(() => expect(lastRoute(c)).toMatchObject({ simulate_closures: ['e2'], previous_edge_ids: ['e1', 'e2'] }))
    expect(await screen.findAllByText(/previous route is blocked/)).toHaveLength(1)
    expect(screen.getByText(n.previousBlocked)).toBeInTheDocument()
    expect(screen.getByText('Simulated closures active: 1')).toBeInTheDocument()
    expect(screen.getByTestId('closed-edge')).toHaveTextContent(n.closedSimulated)
    expect(screen.getByTestId('previous-route')).toBeInTheDocument()
    // Changing the destination keeps the closure but no longer asks about the old route.
    await user.selectOptions(screen.getByRole('combobox', { name: n.pickTo }), 'wc')
    await waitFor(() => expect(lastRoute(c)).toMatchObject({ destination: 'wc', simulate_closures: ['e2'] }))
    expect(lastRoute(c).previous_edge_ids).toBeUndefined()
    await user.click(screen.getByRole('button', { name: n.reopenAll }))
    await waitFor(() => expect(lastRoute(c).simulate_closures).toBeUndefined())
    expect(screen.queryByTestId('closed-edge')).not.toBeInTheDocument()
  })

  it('offers no closure simulator when client-config does not allow simulated closures', async () => {
    const c = client({ clientConfig: vi.fn().mockResolvedValue({ google_maps_browser_key: null, features: { ar_guidance_stations: [], simulate_closures: false } }) })
    const user = await openNav(c)
    await routeTo(user, 'p1')
    await waitFor(() => expect(c.clientConfig).toHaveBeenCalled())
    expect(screen.queryByTestId('closure-simulator')).not.toBeInTheDocument()
  })

  it('shows active closures from the disruption overlay, and says so when they are unavailable', async () => {
    const closure: StationDisruption = { id: 'd1', station_id: 'test_town', target_type: 'edge', target_id: 'e3', kind: 'pathway_closure',
      reason: 'Stairs under repair', source: 'control room', simulated: false, created_at: '2026-10-10T00:00:00Z', expires_at: '2026-10-11T00:00:00Z' }
    await openNav(client({ disruptions: vi.fn().mockResolvedValue([closure]) }))
    const panel = await screen.findByRole('region', { name: n.activeClosures })
    expect(panel).toHaveTextContent('Closed: Platform 1 → Toilet — Stairs under repair')
    expect(screen.getByTestId('closed-edge')).toHaveTextContent(`✕ ${n.closed}`)
    document.body.innerHTML = ''

    await openNav(client({ disruptions: vi.fn().mockRejectedValue(new ApiError(503, 'disruptions_unavailable', 'Current closure information is unavailable.')) }))
    expect(await screen.findByText(n.closuresUnavailable)).toHaveAttribute('data-code', 'disruptions_unavailable')
  })

  it('explains an unreachable destination and offers to relax the active preference', async () => {
    const c = client()
    const user = await openNav(c)
    await user.click(screen.getByRole('button', { name: n.avoidStairs }))
    echoRoute.mockResolvedValueOnce(noRoute)
    await user.selectOptions(screen.getByRole('combobox', { name: n.pickTo }), 'wc')
    expect(await screen.findByText('No step-free route: every path to Toilet uses stairs.')).toBeInTheDocument()
    expect(screen.queryByTestId('route-line')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: n.chooseDestination })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Turn off: Avoid stairs' }))
    await waitFor(() => expect(lastRoute(c)).toMatchObject({ destination: 'wc', preferences: NO_PREFS }))
    expect(await screen.findByTestId('route-line')).toBeInTheDocument()
  })

  it('a slow, superseded route response never replaces the newer one', async () => {
    let releaseFirst: (r: RouteResult) => void = () => {}
    const signals: AbortSignal[] = []
    const stationRoute = vi.fn((body: { destination: string }, o: { signal: AbortSignal }) => {
      signals.push(o.signal)
      if (body.destination === 'p1') return new Promise<RouteResult>((resolve) => { releaseFirst = resolve })
      return Promise.resolve({ ...okRoute, node_ids: ['ent', 'j1', 'wc'] })
    })
    const user = await openNav(client({ stationRoute }))
    await user.selectOptions(screen.getByRole('combobox', { name: n.pickTo }), 'p1')
    await user.selectOptions(screen.getByRole('combobox', { name: n.pickTo }), 'wc')
    await waitFor(() => expect(screen.getByLabelText(n.summary)).toHaveTextContent('Main Gate → Toilet'))
    expect(signals[0].aborted).toBe(true)
    releaseFirst({ ...okRoute, node_ids: ['ent', 'j1', 'p1'] })
    await new Promise((r) => setTimeout(r, 0))
    expect(screen.getByLabelText(n.summary)).toHaveTextContent('Main Gate → Toilet')
  })

  it('shows a route error from the backend', async () => {
    const user = await openNav(client({ stationRoute: vi.fn().mockRejectedValue(new ApiError(500, 'route_integrity_failed', 'Route integrity check failed')) }))
    await user.selectOptions(screen.getByRole('combobox', { name: n.pickTo }), 'p1')
    expect(await screen.findByRole('alert')).toHaveTextContent(`${n.routeFailed} Route integrity check failed`)
  })

  it('reports an unreachable station catalogue', async () => {
    render(<App client={client({ stations: vi.fn().mockRejectedValue(new ApiError(0, 'network_error', 'Cannot reach the planner service.')) })} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Cannot reach the planner service.')
  })

  it("opens the journey's station by its railway code from the catalogue", async () => {
    const c = client({}, { ...withRecs, selected_option_id: rec.option.option_id })
    render(<App client={c} />)
    // D103 boards at CBE (no floor plan) and arrives at MAS: Chennai Central.
    await waitFor(() => expect(c.station).toHaveBeenCalledWith('chennai_central', expect.anything()))
    expect(screen.getByLabelText(n.station)).toHaveValue('chennai_central')
    expect(screen.getByRole('img', { name: n.bannerAlt })).toBeInTheDocument()
    expect(await screen.findByText('D103 Demo Nilgiri Night Express')).toBeInTheDocument()
  })

  it('preselects no station when the journey has no floor plan, and shows no Chennai photo elsewhere', async () => {
    const other = { ...rec, option: { ...rec.option, legs: [{ ...rec.option.legs[0], to_code: 'MDU', to_name: 'Madurai' }] } }
    const state = { ...withRecs, recommendations: { ...withRecs.recommendations!, recommendations: [other] }, selected_option_id: other.option.option_id }
    const c = client({}, state)
    const user = userEvent.setup()
    render(<App client={c} />)
    expect(await screen.findByText(/RailSaathi has no floor plan for Coimbatore Junction/)).toBeInTheDocument()
    expect(c.station).not.toHaveBeenCalled()
    await user.selectOptions(screen.getByLabelText(n.station), 'test_town')
    await screen.findByRole('combobox', { name: n.pickTo })
    expect(screen.queryByRole('img', { name: n.bannerAlt })).not.toBeInTheDocument()
  })

  it('untraced station: plan only, the unavailable notice, no pickers, no chips and no route request', async () => {
    const c = client({ station: vi.fn().mockResolvedValue(details({ routing_enabled: false })) })
    const user = userEvent.setup()
    render(<App client={c} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(n.routingUnavailable)
    expect(screen.queryByRole('combobox', { name: n.pickTo })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: n.avoidStairs })).not.toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Station map of Test Town' })).toBeInTheDocument()
    expect(screen.queryByText(n.emptyMap)).not.toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: n.steps }))
    expect(screen.getAllByText(n.routingUnavailable).length).toBeGreaterThan(1)
    expect(c.stationRoute).not.toHaveBeenCalled()
    expect(c.disruptions).not.toHaveBeenCalled()
    expect(screen.queryByTestId('closure-simulator')).not.toBeInTheDocument()
  })

  it('renders in Tamil', async () => {
    saveState({ language: 'ta' })
    const user = userEvent.setup()
    render(<App client={client()} />)
    expect(await screen.findByRole('heading', { name: ta.title })).toBeInTheDocument()
    await screen.findByRole('combobox', { name: ta.pickTo })
    await user.selectOptions(screen.getByRole('combobox', { name: ta.pickTo }), 'p1')
    await screen.findByTestId('route-line')
    expect(screen.getByLabelText(ta.summary)).toHaveTextContent(`2 ${ta.min}`)
    expect(screen.getByRole('button', { name: ta.wheelchair })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /வழிகாட்டலைத் தொடங்கு/ })).toBeEnabled()
  })
})
