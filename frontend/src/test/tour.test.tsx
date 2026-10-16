// Virtual tour screen states and the Street View loader. The R3F canvas is mocked (no WebGL in jsdom) and so is
// the Maps loader; everything else is the real screen against a mocked API client.
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import { ApiError, type ApiClient } from '../api/client'
import type { ClientConfig, RouteResult, StationDetails, StationTour, TourPanorama } from '../api/types'
import type { TourSceneProps } from '../tour/TourScene'
import { loadStreetView, onMapsAuthFailure, resetStreetViewLoaderForTests } from '../tour/streetView'
import StreetViewDialog from '../tour/StreetViewDialog'
import { MOBILE_STRINGS } from '../mobile/strings'
import routeJson from './data/chennai_central_route.json'
import tourJson from './data/chennai_central_tour.json'
import { response } from './fixtures'

const scene = vi.hoisted(() => ({ last: null as TourSceneProps | null, throws: false }))
vi.mock('../tour/TourScene', () => ({
  default: (props: TourSceneProps) => {
    if (scene.throws) throw new Error('WebGL context lost')
    scene.last = props
    return <div data-testid="tour-scene" role="img" aria-label={props.label} />
  },
}))
const env = vi.hoisted(() => ({ webgl: true, reduced: false }))
vi.mock('../tour/environment', () => ({
  hasWebGL: () => env.webgl, useReducedMotion: () => env.reduced, prefersReducedMotion: () => env.reduced,
}))
const maps = vi.hoisted(() => ({ setOptions: vi.fn(), importLibrary: vi.fn() }))
vi.mock('@googlemaps/js-api-loader', () => maps)

const m = MOBILE_STRINGS.en
const chennai = tourJson as unknown as StationTour
const chennaiRoute = routeJson as unknown as RouteResult
const KEY = 'browser-key-123'

const pano = (pano_id: string, node_id: string, heading = 0): TourPanorama =>
  ({ pano_id, node_id, heading, pitch: 0, kind: 'street_view', verified_on: null })
const withPanos = (): StationTour => ({
  ...chennai, panoramas: [pano('PANO_ENTRANCE', 'ent_wall_tax', 180), pano('PANO_P10', 'platform_10', 90), pano('PANO_SHOP', 'shop_ne')],
})
/** Egmore-like: untraced, no scale, no geo reference, routing disabled. */
const untraced = (): StationTour => ({
  ...chennai, station_id: 'chennai_egmore', station_name: 'Chennai Egmore', routing_enabled: false, ar_enabled: false,
  scale: null, geo_reference: null, levels: [], areas: [], panoramas_note: null,
  map: { url: '/api/stations/chennai_egmore/map', width_px: 1200, height_px: 700 },
})

function details(tour: StationTour): StationDetails {
  return {
    station: {
      station_id: tour.station_id, station_name: tour.station_name, map: { image: 'map.png', width: tour.map.width_px, height: tour.map.height_px },
      nodes: tour.nodes.map(({ id, name, type, position, step_free }) => ({ id, name, type, position, step_free })),
      edges: tour.edges.map(({ id, from, to, path_type, step_free, geometry }) => ({ id, from, to, path_type, step_free, geometry })),
    },
    version: tour.version, layout_basis: tour.layout_basis, routing_enabled: tour.routing_enabled, provenance: tour.provenance,
  }
}

function client(tour: StationTour = chennai, config: ClientConfig | Error = { google_maps_browser_key: null, features: { ar_guidance_stations: [] } }, over: Record<string, unknown> = {}): ApiClient {
  return {
    baseUrl: 'http://test',
    stations: vi.fn().mockResolvedValue([
      { station_id: 'chennai_central', station_name: 'Chennai Central', city: 'Chennai' },
      { station_id: 'chennai_egmore', station_name: 'Chennai Egmore', city: 'Chennai' },
    ]),
    stationTour: vi.fn().mockResolvedValue(tour),
    station: vi.fn().mockResolvedValue(details(tour)),
    stationRoute: vi.fn().mockResolvedValue(chennaiRoute),
    clientConfig: config instanceof Error ? vi.fn().mockRejectedValue(config) : vi.fn().mockResolvedValue(config),
    stationInfo: vi.fn(),
    rakePosition: vi.fn(),
    health: vi.fn().mockResolvedValue({ status: 'ok', api_version: '1', data_mode: 'demo', data_provider: { requested: 'demo', active: 'demo', reason: null }, ai: {} }),
    reference: vi.fn().mockResolvedValue({ places: [], classes: [], passenger_needs: [], budget_priorities: [], transfer_preferences: [], disruption_events: [], data_notice: '' }),
    createSession: vi.fn().mockResolvedValue(response({}, 'Hello')),
    ...over,
  } as unknown as ApiClient
}

function fakeStreetView(status = 'OK') {
  const instances: { el: HTMLElement; opts: google.maps.StreetViewPanoramaOptions; listeners: Record<string, () => void>; setPano: ReturnType<typeof vi.fn>; setPov: ReturnType<typeof vi.fn> }[] = []
  class StreetViewPanorama {
    listeners: Record<string, () => void> = {}
    setPano = vi.fn()
    setPov = vi.fn()
    constructor(public el: HTMLElement, public opts: google.maps.StreetViewPanoramaOptions) { instances.push(this) }
    addListener(ev: string, fn: () => void) { this.listeners[ev] = fn; return { remove: () => undefined } }
    getStatus() { return status }
  }
  return { lib: { StreetViewPanorama } as unknown as google.maps.StreetViewLibrary, instances }
}

async function openTour(c: ApiClient, hash = '/tour?station=chennai_central') {
  window.location.hash = hash
  const user = userEvent.setup()
  render(<App client={c} />)
  await waitFor(() => expect(c.createSession).toHaveBeenCalled())
  return user
}

beforeEach(() => {
  scene.last = null
  scene.throws = false
  env.webgl = true
  env.reduced = false
  maps.setOptions.mockReset()
  maps.importLibrary.mockReset()
  resetStreetViewLoaderForTests()
})

describe('Street View loader', () => {
  it('configures the Maps API once with the browser key and loads only the streetView library', async () => {
    const { lib } = fakeStreetView()
    maps.importLibrary.mockResolvedValue(lib)
    await expect(loadStreetView(KEY)).resolves.toBe(lib)
    await expect(loadStreetView(KEY)).resolves.toBe(lib)
    expect(maps.setOptions).toHaveBeenCalledTimes(1)
    expect(maps.setOptions).toHaveBeenCalledWith({ key: KEY, v: 'weekly' })
    expect(maps.importLibrary).toHaveBeenCalledTimes(1)
    expect(maps.importLibrary).toHaveBeenCalledWith('streetView')
  })

  it('refuses a second, different key and keeps a failed load failed', async () => {
    maps.importLibrary.mockRejectedValue(new Error('network'))
    await expect(loadStreetView(KEY)).rejects.toThrow('network')
    await expect(loadStreetView(KEY)).rejects.toThrow('network')
    await expect(loadStreetView('other')).rejects.toThrow(/another key/)
    expect(maps.importLibrary).toHaveBeenCalledTimes(1)
  })

  it('reports key rejections (gm_authFailure) to subscribers until they unsubscribe', async () => {
    maps.importLibrary.mockResolvedValue(fakeStreetView().lib)
    await loadStreetView(KEY)
    const fn = vi.fn()
    const off = onMapsAuthFailure(fn)
    window.gm_authFailure?.()
    off()
    window.gm_authFailure?.()
    expect(fn).toHaveBeenCalledTimes(1)
  })
})

describe('StreetViewDialog states', () => {
  const stops = [pano('PANO_ENTRANCE', 'ent_wall_tax', 180), pano('PANO_P10', 'platform_10', 90)]
  const renderDialog = (apiKey: string | null, index = 0, onIndex = vi.fn()) =>
    render(<StreetViewDialog open onClose={vi.fn()} tour={withPanos()} apiKey={apiKey} stops={stops} index={index} onIndex={onIndex} m={m.tour} />)

  it('no key: explains and links out to the panorama and the place in Google Maps; the Maps API is never loaded', () => {
    renderDialog(null)
    const alert = screen.getByRole('alert')
    expect(alert).toHaveAttribute('data-status', 'no_key')
    expect(alert).toHaveTextContent(m.tour.noKey)
    expect(within(alert).getByRole('link', { name: m.tour.openPanoInMaps })).toHaveAttribute('href',
      'https://www.google.com/maps/@?api=1&map_action=pano&pano=PANO_ENTRANCE&heading=180&pitch=0')
    expect(within(alert).getByRole('link', { name: m.tour.openInMaps }).getAttribute('href')).toMatch(/^https:\/\/www\.google\.com\/maps\/search\/\?api=1&query=13\.08/)
    expect(alert).toHaveTextContent('within about 50 m')
    expect(maps.setOptions).not.toHaveBeenCalled()
    expect(maps.importLibrary).not.toHaveBeenCalled()
  })

  it('with a key: loading, then Google\'s StreetViewPanorama at the pano id and heading; steps move along the route', async () => {
    const { lib, instances } = fakeStreetView()
    let resolve: (l: google.maps.StreetViewLibrary) => void = () => undefined
    maps.importLibrary.mockReturnValue(new Promise((r) => { resolve = r }))
    const onIndex = vi.fn()
    const { rerender } = renderDialog(KEY, 0, onIndex)
    expect(screen.getByRole('status')).toHaveTextContent(m.tour.svLoading)
    await act(async () => resolve(lib))
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(instances).toHaveLength(1)
    expect(instances[0].el).toBe(screen.getByTestId('street-view-holder'))
    expect(instances[0].opts).toMatchObject({ pano: 'PANO_ENTRANCE', pov: { heading: 180, pitch: 0 }, motionTracking: false })
    expect(screen.getByText('Point 1 of 2: Main Entrance (Wall Tax Road)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: m.tour.prevPano })).toBeDisabled()
    await userEvent.setup().click(screen.getByRole('button', { name: m.tour.nextPano }))
    expect(onIndex).toHaveBeenCalledWith(1)
    rerender(<StreetViewDialog open onClose={vi.fn()} tour={withPanos()} apiKey={KEY} stops={stops} index={1} onIndex={onIndex} m={m.tour} />)
    expect(instances[0].setPano).toHaveBeenLastCalledWith('PANO_P10')
    expect(instances[0].setPov).toHaveBeenLastCalledWith({ heading: 90, pitch: 0 })
    expect(instances).toHaveLength(1)
  })

  it('Maps outage (the library fails to load): explains and links out', async () => {
    maps.importLibrary.mockRejectedValue(new Error('offline'))
    renderDialog(KEY)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveAttribute('data-status', 'failed')
    expect(alert).toHaveTextContent(m.tour.outage)
    expect(within(alert).getByRole('link', { name: m.tour.openPanoInMaps })).toBeInTheDocument()
  })

  it('a pano Google cannot serve (status not OK) and a rejected key both fall back to the link-out', async () => {
    const { lib, instances } = fakeStreetView('ZERO_RESULTS')
    maps.importLibrary.mockResolvedValue(lib)
    const first = renderDialog(KEY)
    await waitFor(() => expect(instances).toHaveLength(1))
    act(() => instances[0].listeners.status_changed())
    expect(screen.getByRole('alert')).toHaveAttribute('data-status', 'failed')
    first.unmount()

    resetStreetViewLoaderForTests()
    const ok = fakeStreetView()
    maps.importLibrary.mockResolvedValue(ok.lib)
    renderDialog(KEY)
    await waitFor(() => expect(ok.instances).toHaveLength(1))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    act(() => window.gm_authFailure?.())
    expect(screen.getByRole('alert')).toHaveTextContent(m.tour.outage)
  })
})

describe('Tour screen', () => {
  it('is lazy-loaded at #/tour, shows the loading state, then the schematic model with its permanent label', async () => {
    let resolveTour: (t: StationTour) => void = () => undefined
    const c = client(chennai, undefined, { stationTour: vi.fn().mockReturnValue(new Promise((r) => { resolveTour = r })) })
    await openTour(c)
    expect(await screen.findByText(m.tour.loading)).toBeInTheDocument()
    await act(async () => resolveTour(chennai))
    expect(await screen.findByTestId('tour-scene')).toHaveAccessibleName(/3D schematic model of Chennai Central/)
    expect(c.stationTour).toHaveBeenCalledWith('chennai_central', expect.anything())
    expect(screen.getByTestId('schematic-label')).toHaveTextContent('Schematic — not to scale')
    expect(screen.getByText(/Schematic layout\./)).toBeInTheDocument() // StationNotice
    expect(screen.getByText(m.tour.nominalHeights)).toBeInTheDocument()
    expect(scene.last!.spec.pins).toHaveLength(chennai.nodes.length)
    expect(scene.last!.floorUrl).toBe('http://test/api/stations/chennai_central/map')
    expect(scene.last!.flying).toBe(false)
    expect(screen.getByLabelText('From entrance')).toBeInTheDocument()
  })

  it('no key and no panoramas: an explanatory line, no "See it" buttons, a link to the station area in Google Maps', async () => {
    const c = client()
    await openTour(c)
    const section = await screen.findByTestId('street-view-section')
    expect(within(section).getByRole('note')).toHaveTextContent(m.tour.noKeyShort)
    expect(within(section).getByText(m.tour.noPanoramas)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /See .* in Street View/ })).not.toBeInTheDocument()
    expect(within(section).getByRole('link', { name: m.tour.openStationInMaps })).toHaveAttribute('href',
      'https://www.google.com/maps/search/?api=1&query=13.0825%2C80.275')
    expect(section).toHaveTextContent('within about 50 m')
  })

  it('client-config failing is treated as no key (link-out), not as an error', async () => {
    await openTour(client(chennai, new ApiError(0, 'network_error', 'down')))
    expect(within(await screen.findByTestId('street-view-section')).getByRole('note')).toHaveTextContent(m.tour.noKeyShort)
  })

  it('populated panoramas with a key: "See it" per panorama node opens Google\'s viewer; a route gives route stops', async () => {
    const { lib, instances } = fakeStreetView()
    maps.importLibrary.mockResolvedValue(lib)
    const c = client(withPanos(), { google_maps_browser_key: KEY, features: { ar_guidance_stations: [] } })
    const user = await openTour(c)
    const section = await screen.findByTestId('street-view-section')
    expect(within(section).queryByRole('note')).not.toBeInTheDocument()
    const buttons = within(section).getAllByRole('button', { name: /See .* in Street View/ })
    expect(buttons).toHaveLength(3)
    await user.click(within(section).getByRole('button', { name: 'See Food / Shop (north-east) in Street View' }))
    const dialog = await screen.findByRole('dialog')
    await waitFor(() => expect(instances).toHaveLength(1))
    expect(instances[0].opts.pano).toBe('PANO_SHOP')
    expect(maps.setOptions).toHaveBeenCalledWith({ key: KEY, v: 'weekly' })
    await user.click(within(dialog).getByRole('button', { name: m.tour.close }))

    // Choose a route Wall Tax Road → Platform 10: its panorama nodes become stops in walking order.
    await user.selectOptions(screen.getByLabelText('To platform or facility'), 'platform_10')
    await waitFor(() => expect(c.stationRoute).toHaveBeenCalled())
    await user.click(await screen.findByRole('button', { name: m.tour.walkRoutePanos }))
    const routeDialog = await screen.findByRole('dialog')
    expect(within(routeDialog).getByText(/Point 1 of 2: Main Entrance \(Wall Tax Road\)/)).toBeInTheDocument()
  })

  it('route fly-through: same mobility options as the blueprint, the route path reaches the scene, play toggles flying', async () => {
    const c = client()
    const user = await openTour(c)
    await screen.findByTestId('tour-scene')
    await user.selectOptions(screen.getByLabelText('Walking preference'), 'wheelchair')
    await user.selectOptions(screen.getByLabelText('To platform or facility'), 'platform_10')
    await waitFor(() => expect(c.stationRoute).toHaveBeenLastCalledWith(expect.objectContaining({
      station_id: 'chennai_central', source: 'ent_wall_tax', destination: 'platform_10',
      preferences: { wheelchair: true, avoid_stairs: true, require_verified_accessibility: false },
    }), expect.anything()))
    await waitFor(() => expect(scene.last!.path?.length).toBeGreaterThan(1))
    expect(scene.last!.pose).not.toBeNull() // framed from above, without animation
    expect(scene.last!.markers.map((x) => x.id)).toEqual(['ent_wall_tax', 'platform_10'])
    await user.click(screen.getByRole('button', { name: m.tour.play }))
    expect(scene.last!.flying).toBe(true)
    expect(screen.getByRole('button', { name: m.tour.stop })).toHaveAttribute('aria-pressed', 'true')
    act(() => scene.last!.onFlyEnd())
    expect(scene.last!.flying).toBe(false)
  })

  it('reduced motion: no fly-through animation; the route is stepped through as still views', async () => {
    env.reduced = true
    const c = client()
    const user = await openTour(c)
    await screen.findByTestId('tour-scene')
    await user.selectOptions(screen.getByLabelText('To platform or facility'), 'platform_10')
    await screen.findByText(m.tour.reducedMotion)
    expect(screen.queryByRole('button', { name: m.tour.play })).not.toBeInTheDocument()
    const before = scene.last!.pose
    await user.click(screen.getByRole('button', { name: m.tour.nextView }))
    expect(screen.getByText('View 1 of 5 along the route')).toBeInTheDocument()
    expect(scene.last!.pose).not.toBe(before)
    expect(scene.last!.flying).toBe(false)
  })

  it('tapping a place (or choosing it from the list) shows its name, step-free label as returned and nearby facilities', async () => {
    const user = await openTour(client())
    await screen.findByTestId('tour-scene')
    act(() => scene.last!.onSelect('concourse_centre'))
    let card = screen.getByTestId('place-card')
    expect(card).toHaveTextContent('Main Concourse')
    expect(card).toHaveTextContent('Step-free: unknown')
    expect(card).toHaveTextContent(m.tour.facilitiesNearby)
    await user.selectOptions(screen.getByLabelText(m.tour.place), 'toilet_west')
    card = screen.getByTestId('place-card')
    expect(card).toHaveTextContent('Toilet · Open')
    expect(scene.last!.selectedId).toBe('toilet_west')
    expect(within(card).queryByRole('button', { name: /Street View/ })).not.toBeInTheDocument() // no panorama here
  })

  it('level toggle: All levels and each level, as pressed buttons', async () => {
    const user = await openTour(client())
    await screen.findByTestId('tour-scene')
    const group = screen.getByRole('group', { name: m.tour.levels })
    const ground = within(group).getByRole('button', { name: 'Ground level (concourse and platforms)' })
    await user.click(ground)
    expect(ground).toHaveAttribute('aria-pressed', 'true')
    expect(scene.last!.visibleLevel).toBe(0)
    await user.click(within(group).getByRole('button', { name: m.tour.allLevels }))
    expect(scene.last!.visibleLevel).toBe('all')
  })

  it('routing disabled (untraced station): the unavailable notice, no pickers, no route request, no pins', async () => {
    const c = client(untraced())
    await openTour(c, '/tour?station=chennai_egmore')
    const notice = await screen.findByText(m.navigation.routingUnavailable)
    expect(notice).toHaveAttribute('data-code', 'routing_unavailable')
    await screen.findByTestId('tour-scene')
    expect(screen.queryByLabelText('To platform or facility')).not.toBeInTheDocument()
    expect(screen.queryByLabelText(m.tour.place)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: m.tour.play })).not.toBeInTheDocument()
    expect(scene.last!.spec.pins).toEqual([])
    expect(screen.getByText(m.tour.planUnits)).toBeInTheDocument()
    expect(screen.getByTestId('street-view-section')).toHaveTextContent(m.tour.noCoords)
    expect(c.stationRoute).not.toHaveBeenCalled()
  })

  it('no WebGL: the 2D plan instead of the canvas (the 3D chunk is never rendered), with the schematic label', async () => {
    env.webgl = false
    await openTour(client())
    expect(await screen.findByText(m.tour.noWebgl)).toBeInTheDocument()
    expect(await screen.findByRole('img', { name: m.blueprint.mapLabel })).toBeInTheDocument()
    expect(screen.queryByTestId('tour-scene')).not.toBeInTheDocument()
    expect(scene.last).toBeNull()
    expect(screen.getByTestId('schematic-label')).toHaveTextContent('Schematic — not to scale')
    expect(screen.queryByRole('group', { name: m.tour.levels })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: m.tour.openBlueprint })).toBeInTheDocument()
  })

  it('a 3D canvas that fails at runtime falls back to the 2D plan', async () => {
    scene.throws = true
    const quiet = vi.spyOn(console, 'error').mockImplementation(() => undefined) // React reports the caught error
    try {
      await openTour(client())
      expect(await screen.findByText(m.tour.sceneFailed)).toBeInTheDocument()
      expect(screen.getByRole('img', { name: m.blueprint.mapLabel })).toBeInTheDocument()
    } finally {
      quiet.mockRestore()
    }
  })

  it('an unknown station shows the tour as unavailable with the backend reason', async () => {
    const c = client(chennai, undefined, {
      stationTour: vi.fn().mockRejectedValue(new ApiError(404, 'station_not_found', 'Station not found.')),
    })
    await openTour(c, '/tour?station=nowhere')
    const alert = await screen.findByText(/The station model could not be loaded\. Station not found\./)
    expect(alert).toHaveAttribute('data-code', 'station_not_found')
    expect(screen.queryByTestId('tour-scene')).not.toBeInTheDocument()
  })

  it('station list failure with no station in the link: an alert with the reason, not an empty screen', async () => {
    const c = client(chennai, undefined, { stations: vi.fn().mockRejectedValue(new ApiError(503, 'service_unavailable', 'Try again shortly.')) })
    await openTour(c, '/tour')
    const alert = await screen.findByText(/The station list could not be loaded, so no station can be shown\. Try again shortly\./)
    expect(alert).toHaveAttribute('role', 'alert')
    expect(alert).toHaveAttribute('data-code', 'service_unavailable')
    expect(c.stationTour).not.toHaveBeenCalled()
  })

  it('an empty station list says so', async () => {
    const c = client(chennai, undefined, { stations: vi.fn().mockResolvedValue([]) })
    await openTour(c, '/tour')
    expect(await screen.findByText(m.tour.noStations)).toHaveAttribute('data-code', 'no_stations')
  })

  it('station details failure while the tour loads: an alert explains why route pickers and the 2D plan are missing', async () => {
    env.webgl = false
    const c = client(chennai, undefined, { station: vi.fn().mockRejectedValue(new ApiError(500, 'internal_error', 'Server error.')) })
    await openTour(c)
    const alert = await screen.findByText(/The station details could not be loaded, so route planning and the 2D plan are not available\. Server error\./)
    expect(alert).toHaveAttribute('role', 'alert')
    expect(alert).toHaveAttribute('data-code', 'internal_error')
    expect(screen.queryByLabelText('To platform or facility')).not.toBeInTheDocument()
    expect(screen.getByTestId('schematic-label')).toBeInTheDocument()
  })

  it('opens on Chennai Central when the link names no station', async () => {
    const c = client()
    await openTour(c, '/tour')
    await screen.findByTestId('tour-scene')
    expect(c.stationTour).toHaveBeenCalledWith('chennai_central', expect.anything())
  })
})

describe('links into the tour', () => {
  it('the station screen links to the tour for the chosen station', async () => {
    window.location.hash = '/navigation'
    const c = client()
    render(<App client={c} />)
    const link = await screen.findByRole('link', { name: /Explore the station in 3D/ })
    expect(link).toHaveAttribute('href', '#/tour?station=chennai_central')
  })
})
