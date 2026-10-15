// AR guidance component and its place in the wayfinder. Camera, motion permission and frame capture are mocked
// (src/ar/device.ts, src/ar/frame.ts); everything else (state machine, budget, maths, copy) is the real code.
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import { ApiError, type ApiClient } from '../api/client'
import type { LocalizeResponse, RouteResult, StationDetails } from '../api/types'
import ArGuidance, { resetLocaliseBudget } from '../ar/ArGuidance'
import { MOBILE_STRINGS } from '../mobile/strings'
import { response } from './fixtures'

const dev = vi.hoisted(() => ({
  checkArSupport: vi.fn(async () => ({ ok: true }) as { ok: true } | { ok: false; reason: 'insecure' | 'no_camera' }),
  requestMotionPermission: vi.fn(async () => true),
  openRearCamera: vi.fn(async () => ({ ok: true, stream: { getTracks: () => [] } }) as unknown),
  stopStream: vi.fn(),
  immersiveArSupported: vi.fn(async () => false),
}))
vi.mock('../ar/device', () => dev)
const frame = vi.hoisted(() => ({
  captureFrame: vi.fn(async () => new Blob([new Uint8Array([0xff, 0xd8, 0xff])], { type: 'image/jpeg' })),
  waitForFrame: vi.fn(async () => true),
}))
vi.mock('../ar/frame', async (orig) => ({ ...(await orig<typeof import('../ar/frame')>()), ...frame }))

const m = MOBILE_STRINGS.en
const a = m.ar
const prov = { mode: 'cached' as const, source: 'RailSaathi station catalogue (schematic)', as_of: '2026-10-10T00:00:00+00:00', note: 'Schematic.' }
const live = { mode: 'live' as const, source: 'gemini-vision', as_of: '2026-10-16T10:00:00+00:00', note: 'Approximate: estimated from one camera frame against a schematic, unsurveyed layout.' }

const details = (over: Partial<StationDetails> = {}): StationDetails => ({
  station: {
    station_id: 'chennai_central', station_name: 'Chennai Central', map: { image: 'map.png', width: 1000, height: 1000 },
    nodes: [
      { id: 'ent_a', name: 'Wall Tax Road', type: 'entrance', position: [0.1, 0.5], step_free: 'unknown' },
      { id: 'cj', name: 'Concourse Junction', type: 'junction', position: [0.5, 0.5], step_free: 'unknown' },
      { id: 'platform_10', name: 'Platform 10', type: 'platform', position: [0.5, 0.1], step_free: 'unknown' },
    ],
    edges: [],
  },
  version: 'local', layout_basis: 'schematic', routing_enabled: true, provenance: prov, ...over,
})

const route = (): RouteResult => ({
  status: 'ok', node_ids: ['ent_a', 'cj', 'platform_10'], edge_ids: ['e1', 'e2'], geometry: [],
  segments: [
    { edge_id: 'e1', from_node: 'ent_a', to_node: 'cj', geometry: [[0.1, 0.5], [0.5, 0.5]], level_change: 0, path_type: 'walkway', step_free: 'unknown' },
    { edge_id: 'e2', from_node: 'cj', to_node: 'platform_10', geometry: [[0.5, 0.5], [0.5, 0.1]], level_change: 0, path_type: 'walkway', step_free: 'unknown' },
  ],
  instructions: [
    { step: 1, text: 'Walk east to Concourse Junction', node_id: 'ent_a', edge_id: 'e1', distance_m: 40, distance_is_estimate: true },
    { step: 2, text: 'Turn left at Concourse Junction to Platform 10', node_id: 'cj', edge_id: 'e2', distance_m: 31.4, distance_is_estimate: true },
  ],
  distance_m: null, estimated_distance_m: 71, distance_basis: 'estimated_from_map_scale', estimated_duration_s: null,
  duration_assumption: null, accessibility_confidence: 'unverified', warnings: [], explanation: null, reason: null,
  along_the_way: [], provenance: prov,
})

const fixAt = (node_id: string, facing: number | null, over: Partial<LocalizeResponse> = {}): LocalizeResponse => ({
  status: 'fix', station_id: 'chennai_central',
  fix: { node_id, node_name: node_id === 'cj' ? 'Concourse Junction' : 'Platform 10', level: 0, position: [0.5, 0.5], confidence: 0.82,
    facing_bearing_deg: facing, matched_cues: [] },
  candidates: [], confidence_threshold: 0.6, latency_ms: 900, message: null, session_token: 'tok', provenance: live, ...over,
})

let clock = 0
function setup(localize: ReturnType<typeof vi.fn>, r: RouteResult | null = route()) {
  const onExit = vi.fn()
  const c = { localize } as unknown as ApiClient
  const user = userEvent.setup()
  const view = render(<ArGuidance client={c} stationId="chennai_central" details={details()} route={r} m={a} onExit={onExit} now={() => clock} />)
  return { onExit, user, unmount: view.unmount }
}

function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => { resolve = r })
  return { promise, resolve }
}

function orient(alpha: number) {
  const e = new Event('deviceorientation')
  Object.assign(e, { alpha, beta: 90, gamma: 0, absolute: false })
  act(() => { window.dispatchEvent(e) })
}

beforeAll(() => {
  HTMLMediaElement.prototype.play = vi.fn(() => Promise.resolve())
})
beforeEach(() => {
  clock = 0
  resetLocaliseBudget()
  vi.clearAllMocks()
  dev.openRearCamera.mockResolvedValue({ ok: true, stream: { getTracks: () => [] } })
  dev.requestMotionPermission.mockResolvedValue(true)
})

describe('AR guidance', () => {
  it('asks for consent first, with the safety and approximate copy always on screen', () => {
    setup(vi.fn())
    expect(screen.getByRole('heading', { name: a.consentTitle })).toBeInTheDocument()
    expect(screen.getByText(/Google Vertex AI \(Gemini\)/)).toBeInTheDocument()
    expect(screen.getByText(/not stored by RailSaathi/)).toBeInTheDocument()
    expect(screen.getByRole('note')).toHaveTextContent('Watch your step, look up at platform edges and stairs.')
    expect(screen.getByTestId('ar-approximate')).toHaveTextContent('Approximate — confirm with station signs.')
    expect(dev.openRearCamera).not.toHaveBeenCalled() // nothing opens before consent
  })

  it('a fix points the arrow from the fixed node to the next waypoint, relative to the facing bearing', async () => {
    const localize = vi.fn().mockResolvedValue(fixAt('cj', 90))
    const { user } = setup(localize)
    await user.click(screen.getByRole('button', { name: a.accept }))
    expect(dev.requestMotionPermission).toHaveBeenCalled()
    // cj → platform_10 is plan-up (0°); the camera faces east (90°): the waypoint is 90° to the left.
    const arrow = await screen.findByTestId('ar-arrow')
    expect(arrow).toHaveAttribute('data-angle', '-90')
    expect(arrow).toHaveAccessibleName('Direction: Turn left')
    expect(screen.getByText('Turn left at Concourse Junction to Platform 10')).toBeInTheDocument()
    expect(screen.getByText('about 31 m (approximate)')).toBeInTheDocument()
    expect(screen.getByText(/Near Concourse Junction · 82% sure/)).toBeInTheDocument()
    expect(screen.getByTestId('provenance-badge')).toHaveAttribute('data-mode', 'live')
    expect(screen.getByRole('note')).toBeInTheDocument()
    const req = localize.mock.calls[0][0]
    expect(req).toMatchObject({ station_id: 'chennai_central', route_node_ids: ['ent_a', 'cj', 'platform_10'], previous_node_id: null })
    expect(req.image).toBeInstanceOf(Blob)
    expect(req.image.type).toBe('image/jpeg')
  })

  it('the gyro turns the arrow between fixes, from the yaw recorded at the fix', async () => {
    const localize = vi.fn().mockResolvedValueOnce(fixAt('cj', 90)).mockResolvedValueOnce(fixAt('cj', 0))
    const { user } = setup(localize)
    await user.click(screen.getByRole('button', { name: a.accept }))
    await screen.findByTestId('ar-arrow')
    orient(0) // yaw 0 when the next frame is taken
    await user.click(screen.getByRole('button', { name: a.rescan }))
    await waitFor(() => expect(screen.getByTestId('ar-arrow')).toHaveAttribute('data-angle', '0'))
    expect(localize.mock.calls[1][0].previous_node_id).toBe('cj') // the last fix is the prior
    orient(90) // turned 90° left since the fix (alpha grows anticlockwise): the waypoint is now to the right
    await waitFor(() => expect(screen.getByTestId('ar-arrow')).toHaveAttribute('data-angle', '90'))
    expect(screen.getByTestId('ar-arrow')).toHaveAccessibleName('Direction: Turn right')
    orient(359) // wrap-around: 1° to the right of the fix
    await waitFor(() => expect(screen.getByTestId('ar-arrow')).toHaveAttribute('data-angle', '-1'))
  })

  it('a large turn re-localises early, but not within 8 s of the last frame', async () => {
    const localize = vi.fn().mockResolvedValue(fixAt('cj', 0))
    const { user } = setup(localize)
    await user.click(screen.getByRole('button', { name: a.accept }))
    await screen.findByTestId('ar-arrow')
    orient(0)
    clock = 9_000
    await user.click(screen.getByRole('button', { name: a.rescan })) // fix with yaw 0 at t = 9 s
    await waitFor(() => expect(localize).toHaveBeenCalledTimes(2))
    await screen.findByTestId('ar-arrow')
    orient(90) // a 90° turn 0 s after the fix: too soon
    await waitFor(() => expect(screen.getByTestId('ar-arrow')).toHaveAttribute('data-angle', '90'))
    expect(localize).toHaveBeenCalledTimes(2)
    clock = 17_000
    orient(80) // still turned 80°, now 8 s later
    await waitFor(() => expect(localize).toHaveBeenCalledTimes(3))
    expect(localize.mock.calls[2][0].previous_node_id).toBe('cj')
  })

  it('without motion permission the arrow stays put and says so', async () => {
    dev.requestMotionPermission.mockResolvedValue(false)
    const { user } = setup(vi.fn().mockResolvedValue(fixAt('cj', 90)))
    await user.click(screen.getByRole('button', { name: a.accept }))
    await screen.findByTestId('ar-arrow')
    orient(90)
    expect(screen.getByTestId('ar-arrow')).toHaveAttribute('data-angle', '-90')
    expect(screen.getByText(a.noMotion)).toBeInTheDocument()
  })

  it('declining or a denied camera returns to the steps with the reason', async () => {
    const first = setup(vi.fn())
    await first.user.click(screen.getByRole('button', { name: a.decline }))
    expect(first.onExit).toHaveBeenCalledWith('declined', null)
    first.onExit.mockClear()

    dev.openRearCamera.mockResolvedValue({ ok: false, reason: 'camera_denied' })
    document.body.innerHTML = ''
    const second = setup(vi.fn())
    await second.user.click(screen.getAllByRole('button', { name: a.accept })[0])
    await waitFor(() => expect(second.onExit).toHaveBeenCalledWith('camera_denied', null))
  })

  it('low confidence asks "Are you near…?"; the pick becomes the fix', async () => {
    const localize = vi.fn().mockResolvedValue({
      ...fixAt('cj', null), status: 'low_confidence', fix: null, message: 'Not sure where you are.',
      candidates: [{ node_id: 'cj', node_name: 'Concourse Junction', confidence: 0.41 }, { node_id: 'ent_a', node_name: 'Wall Tax Road', confidence: 0.2 }],
    })
    const { user } = setup(localize)
    await user.click(screen.getByRole('button', { name: a.accept }))
    const list = await screen.findByRole('region', { name: a.chooseTitle })
    await user.click(within(list).getByRole('button', { name: /Concourse Junction/ }))
    expect(await screen.findByText(a.noFacing)).toBeInTheDocument() // a pick has no facing bearing: no arrow
    expect(screen.queryByTestId('ar-arrow')).not.toBeInTheDocument()
    expect(screen.getByText('Near Concourse Junction')).toBeInTheDocument()
    expect(screen.getByText('Turn left at Concourse Junction to Platform 10')).toBeInTheDocument()
  })

  it('"unavailable" before any fix falls back to the steps with the reason', async () => {
    const msg = 'Camera positioning is unavailable right now. Use the map to pick your position.'
    const localize = vi.fn().mockResolvedValue({ ...fixAt('cj', null), status: 'unavailable', fix: null, message: msg,
      provenance: { ...live, mode: 'unavailable', note: msg } })
    const { onExit, user } = setup(localize)
    await user.click(screen.getByRole('button', { name: a.accept }))
    await waitFor(() => expect(onExit).toHaveBeenCalledWith('unavailable', msg))
  })

  it('a 429 shows the reason and blocks further sends until Retry-After', async () => {
    const localize = vi.fn().mockRejectedValue(new ApiError(429, 'rate_limited', 'Too many camera fixes.', {}, null, 120))
    const { user } = setup(localize)
    await user.click(screen.getByRole('button', { name: a.accept }))
    expect(await screen.findByRole('alert')).toHaveTextContent(a.error.rate_limited)
    await user.click(screen.getByRole('button', { name: a.retry }))
    expect(await screen.findByRole('alert')).toHaveTextContent(a.error.rate_limited)
    expect(localize).toHaveBeenCalledTimes(1) // the retry did not reach the server
  })

  it('AR switched off for the station (404) falls back', async () => {
    const localize = vi.fn().mockRejectedValue(new ApiError(404, 'ar_guidance_unavailable', 'AR guidance is not available for this station.'))
    const { onExit, user } = setup(localize)
    await user.click(screen.getByRole('button', { name: a.accept }))
    await waitFor(() => expect(onExit).toHaveBeenCalledWith('ar_off', null))
  })

  it('arrival at the destination', async () => {
    const { user } = setup(vi.fn().mockResolvedValue(fixAt('platform_10', 0)))
    await user.click(screen.getByRole('button', { name: a.accept }))
    expect(await screen.findByText('You have reached Platform 10.')).toBeInTheDocument()
  })

  it('exit is always reachable and keyboard-operable; frames are never stored or logged', async () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    const log = vi.spyOn(console, 'log')
    const { onExit, user } = setup(vi.fn().mockResolvedValue(fixAt('cj', 90)))
    await user.click(screen.getByRole('button', { name: a.accept }))
    await screen.findByTestId('ar-arrow')
    screen.getByRole('button', { name: a.exit }).focus()
    await user.keyboard('{Enter}')
    expect(onExit).toHaveBeenCalledWith(null, null)
    expect(setItem).not.toHaveBeenCalled()
    expect(log).not.toHaveBeenCalled()
    setItem.mockRestore()
    log.mockRestore()
  })

  it('the camera is stopped on exit and on unmount', async () => {
    const stream = { getTracks: () => [] }
    dev.openRearCamera.mockResolvedValue({ ok: true, stream })
    const first = setup(vi.fn().mockResolvedValue(fixAt('cj', 90)))
    await first.user.click(screen.getByRole('button', { name: a.accept }))
    await screen.findByTestId('ar-arrow')
    expect(dev.stopStream).not.toHaveBeenCalledWith(stream)
    await first.user.click(screen.getByRole('button', { name: a.exit }))
    await waitFor(() => expect(dev.stopStream).toHaveBeenCalledWith(stream))
    first.unmount()

    dev.stopStream.mockClear()
    const second = setup(vi.fn().mockResolvedValue(fixAt('cj', 90)))
    await second.user.click(screen.getByRole('button', { name: a.accept }))
    await screen.findByTestId('ar-arrow')
    second.unmount()
    expect(dev.stopStream).toHaveBeenCalledWith(stream)
  })

  it('a camera granted after AR was left is stopped at once and never used', async () => {
    const stream = { getTracks: () => [] }
    const pending = deferred<unknown>()
    dev.openRearCamera.mockReturnValue(pending.promise)
    const localize = vi.fn()
    const { user, unmount } = setup(localize)
    await user.click(screen.getByRole('button', { name: a.accept }))
    unmount() // e.g. the user switched tab while the permission prompt was open
    await act(async () => { pending.resolve({ ok: true, stream }) })
    expect(dev.stopStream).toHaveBeenCalledWith(stream)
    expect(frame.captureFrame).not.toHaveBeenCalled()
    expect(localize).not.toHaveBeenCalled()
  })

  it('no frame is captured or uploaded when AR is left while waiting for the video', async () => {
    const ready = deferred<boolean>()
    frame.waitForFrame.mockReturnValueOnce(ready.promise)
    const localize = vi.fn()
    const { user, unmount } = setup(localize)
    await user.click(screen.getByRole('button', { name: a.accept }))
    await waitFor(() => expect(frame.waitForFrame).toHaveBeenCalled())
    unmount()
    await act(async () => { ready.resolve(true) })
    expect(frame.captureFrame).not.toHaveBeenCalled()
    expect(localize).not.toHaveBeenCalled()
  })

  it('a refused request (4xx) ends AR with the server message instead of retrying as a network error', async () => {
    const localize = vi.fn().mockRejectedValue(new ApiError(415, 'unsupported_image_type', 'The image must be JPEG or WebP.'))
    const { onExit, user } = setup(localize)
    await user.click(screen.getByRole('button', { name: a.accept }))
    await waitFor(() => expect(onExit).toHaveBeenCalledWith('rejected', 'The image must be JPEG or WebP.'))
    expect(localize).toHaveBeenCalledTimes(1)
    expect(screen.queryByText(a.error.network)).not.toBeInTheDocument()
  })

  it('a stale session token is dropped and the frame retried once with a new session', async () => {
    const stale = new ApiError(401, 'invalid_session_token', 'A valid session token is required.')
    const localize = vi.fn().mockRejectedValueOnce(stale).mockResolvedValueOnce(fixAt('cj', 90))
    const { user } = setup(localize)
    await user.click(screen.getByRole('button', { name: a.accept }))
    await screen.findByTestId('ar-arrow')
    expect(localize).toHaveBeenCalledTimes(2)
    expect(localize.mock.calls[0][1]).toMatchObject({ freshSession: false })
    expect(localize.mock.calls[1][1]).toMatchObject({ freshSession: true })
  })

  it('a token still refused after the fresh retry ends AR (no endless retries)', async () => {
    const stale = new ApiError(401, 'invalid_session_token', 'A valid session token is required.')
    const localize = vi.fn().mockRejectedValue(stale)
    const { onExit, user } = setup(localize)
    await user.click(screen.getByRole('button', { name: a.accept }))
    await waitFor(() => expect(onExit).toHaveBeenCalledWith('rejected', 'A valid session token is required.'))
    expect(localize).toHaveBeenCalledTimes(2)
  })

  it('without a route it asks for one instead of opening the camera', () => {
    setup(vi.fn(), null)
    expect(screen.getByText(a.needsRoute)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: a.accept })).not.toBeInTheDocument()
    expect(screen.getByRole('note')).toBeInTheDocument()
  })
})

describe('AR tab in the wayfinder', () => {
  function client(over: Record<string, unknown> = {}): ApiClient {
    return {
      baseUrl: 'http://test',
      station: vi.fn().mockResolvedValue(details()),
      stationRoute: vi.fn().mockResolvedValue(route()),
      stations: vi.fn().mockResolvedValue([{ station_id: 'chennai_central', station_name: 'Chennai Central', city: 'Chennai' }]),
      clientConfig: vi.fn().mockResolvedValue({ google_maps_browser_key: null, features: { ar_guidance_stations: ['chennai_central'] } }),
      localize: vi.fn().mockResolvedValue(fixAt('cj', 90)),
      rakePosition: vi.fn(),
      health: vi.fn().mockResolvedValue({ status: 'ok', api_version: '1', data_mode: 'demo', data_provider: { requested: 'demo', active: 'demo', reason: null }, ai: {} }),
      reference: vi.fn().mockResolvedValue({ places: [], classes: [], passenger_needs: [], budget_priorities: [], transfer_preferences: [], disruption_events: [], data_notice: '' }),
      createSession: vi.fn().mockResolvedValue(response({}, 'Hello')),
      ...over,
    } as unknown as ApiClient
  }

  async function open(c: ApiClient, ready: () => Promise<unknown> = () => screen.findByLabelText(m.navigation.to)) {
    window.location.hash = '/navigation'
    const user = userEvent.setup()
    render(<App client={c} />)
    await ready()
    return user
  }

  it('is offered for an AR station; leaving returns to the text steps', async () => {
    const c = client()
    const user = await open(c)
    const tab = await screen.findByRole('tab', { name: a.tab })
    await user.selectOptions(screen.getByLabelText(m.navigation.to), 'platform_10')
    await user.click(tab)
    await user.click(await screen.findByRole('button', { name: a.accept }))
    await screen.findByTestId('ar-arrow')
    await user.click(screen.getByRole('button', { name: a.exit }))
    expect(screen.getByRole('tab', { name: m.navigation.steps })).toHaveAttribute('aria-selected', 'true')
    expect(await screen.findByText('Turn left at Concourse Junction to Platform 10')).toBeInTheDocument() // the step list
  })

  it('a denied camera lands on the steps with the reason shown', async () => {
    dev.openRearCamera.mockResolvedValue({ ok: false, reason: 'camera_denied' })
    const user = await open(client())
    await user.selectOptions(screen.getByLabelText(m.navigation.to), 'platform_10')
    await user.click(await screen.findByRole('tab', { name: a.tab }))
    await user.click(await screen.findByRole('button', { name: a.accept }))
    expect(await screen.findByText(a.fallback.camera_denied)).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: m.navigation.steps })).toHaveAttribute('aria-selected', 'true')
  })

  it('is not offered when client-config does not list the station, for an untraced station, or without a camera', async () => {
    await open(client({ clientConfig: vi.fn().mockResolvedValue({ google_maps_browser_key: null, features: { ar_guidance_stations: [] } }) }))
    await screen.findByRole('tab', { name: m.navigation.steps })
    expect(screen.queryByRole('tab', { name: a.tab })).not.toBeInTheDocument()
    document.body.innerHTML = ''

    const untraced = client({ station: vi.fn().mockResolvedValue(details({ routing_enabled: false })) })
    await open(untraced, () => screen.findByText(m.navigation.routingUnavailable))
    await waitFor(() => expect(untraced.clientConfig).toHaveBeenCalled())
    expect(screen.queryByRole('tab', { name: a.tab })).not.toBeInTheDocument()
    document.body.innerHTML = ''

    dev.checkArSupport.mockResolvedValueOnce({ ok: false, reason: 'no_camera' })
    const c = client()
    await open(c)
    await waitFor(() => expect(dev.checkArSupport).toHaveBeenCalled())
    expect(screen.queryByRole('tab', { name: a.tab })).not.toBeInTheDocument()
  })
})
