import { devices, expect, test, type Route } from '@playwright/test'
import { expectNoAxeViolations } from './axe'

// AR guidance end to end: Chromium's fake camera (a generated test pattern), the real backend for stations and the
// route, and route interception for /api/client-config (AR on for Chennai Central; the demo backend runs without a
// vision model) and /api/navigation/localize (a scripted fix). Checks the consent, the multipart frame upload, the
// arrow, the always-visible safety copy and the way back to the text steps.
test.use({
  viewport: devices['iPhone 13'].viewport, isMobile: true, hasTouch: true,
  permissions: ['camera'],
  launchOptions: { args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] },
})

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
}

async function fulfilJson(route: Route, body: unknown) {
  if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers: CORS })
  return route.fulfill({ status: 200, headers: { ...CORS, 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
}

test('camera guidance: consent, a fix from the fake camera, the arrow, and back to the steps', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  const uploads: { contentType: string; size: number; hasJpeg: boolean }[] = []

  await page.route('**/api/client-config', (route) =>
    fulfilJson(route, { google_maps_browser_key: null, features: { ar_guidance_stations: ['chennai_central'] } }))
  await page.route('**/api/navigation/localize', async (route) => {
    const req = route.request()
    if (req.method() === 'POST') {
      const body = req.postDataBuffer() ?? Buffer.alloc(0)
      uploads.push({ contentType: req.headers()['content-type'] ?? '', size: body.length,
        hasJpeg: body.includes(Buffer.from([0xff, 0xd8, 0xff])) })
    }
    return fulfilJson(route, {
      status: 'fix', station_id: 'chennai_central',
      fix: { node_id: 'cj_north', node_name: 'Concourse North Junction', level: 0, position: [0.49039, 0.31944], confidence: 0.81,
        facing_bearing_deg: 180, matched_cues: [] },
      candidates: [], confidence_threshold: 0.6, latency_ms: 950, message: null, session_token: 'e2e-token',
      provenance: { mode: 'live', source: 'gemini-vision', as_of: '2026-10-16T10:00:00Z',
        note: 'Approximate: estimated from one camera frame against a schematic, unsurveyed layout. Check the station signs and ask staff if unsure.' },
    })
  })

  await page.goto('/#/navigation')
  await page.locator('#nav-station').selectOption('chennai_central')
  await page.getByLabel('To', { exact: true }).selectOption('platform_10')
  await page.getByRole('tab', { name: 'Camera (AR)' }).click()

  await expect(page.getByRole('heading', { name: 'Use your camera to find your way?' })).toBeVisible()
  await expect(page.getByText('Watch your step, look up at platform edges and stairs.')).toBeVisible()
  await expect(page.getByTestId('ar-approximate')).toHaveText('Approximate — confirm with station signs.')
  await expectNoAxeViolations(page, 'AR consent')
  await page.getByRole('button', { name: 'Start camera' }).click()

  const arrow = page.getByTestId('ar-arrow')
  await expect(arrow).toBeVisible()
  await expect(page.getByText(/Near Concourse North Junction/)).toBeVisible()
  await expectNoAxeViolations(page, 'AR guidance (arrow over the camera view)')
  await expect(page.getByText('Watch your step, look up at platform edges and stairs.')).toBeVisible()
  expect(uploads.length).toBeGreaterThanOrEqual(1)
  expect(uploads[0].contentType).toContain('multipart/form-data')
  expect(uploads[0].hasJpeg).toBe(true)
  expect(uploads[0].size).toBeLessThan(1_500_000)
  // The frame was not kept anywhere in the page's storage: only the planner's per-tab session entry exists.
  const stored = await page.evaluate(() => ({
    local: localStorage.length,
    session: Object.keys(sessionStorage).map((k) => [k, (sessionStorage.getItem(k) ?? '').length] as const),
  }))
  expect(stored.local).toBe(0)
  expect(stored.session.map(([k]) => k).filter((k) => k !== 'railsaathi.session.v1')).toEqual([])
  expect(stored.session.every(([, size]) => size < 2_000)).toBe(true)

  await page.getByRole('button', { name: 'Exit camera and show steps' }).click()
  await expect(page.getByRole('tab', { name: 'Step-by-Step' })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByText(/Start at Main Entrance/).first()).toBeVisible()
  expect(errors).toEqual([])
})

test('camera guidance is not offered when client-config lists no AR station', async ({ page }) => {
  await page.route('**/api/client-config', (route) =>
    fulfilJson(route, { google_maps_browser_key: null, features: { ar_guidance_stations: [] } }))
  await page.goto('/#/navigation')
  await page.locator('#nav-station').selectOption('chennai_central')
  await expect(page.getByRole('tab', { name: 'Step-by-Step' })).toBeVisible()
  await expect(page.getByRole('tab', { name: 'Camera (AR)' })).toHaveCount(0)
})

test('camera guidance against the real /localize: the demo backend has no vision model, so it falls back to the steps', async ({ page }) => {
  // Only client-config is mocked. The real endpoint parses the browser's multipart frame (type sniffing, size and
  // Content-Length checks) and answers `unavailable`, which must land on the step list with the reason.
  await page.route('**/api/client-config', (route) =>
    fulfilJson(route, { google_maps_browser_key: null, features: { ar_guidance_stations: ['chennai_central'] } }))
  const statuses: number[] = []
  page.on('response', (r) => { if (r.url().endsWith('/api/navigation/localize') && r.request().method() === 'POST') statuses.push(r.status()) })
  await page.goto('/#/navigation')
  await page.locator('#nav-station').selectOption('chennai_central')
  await page.getByLabel('To', { exact: true }).selectOption('platform_10')
  await page.getByRole('tab', { name: 'Camera (AR)' }).click()
  await page.getByRole('button', { name: 'Start camera' }).click()
  await expect(page.getByText('Camera positioning is unavailable right now. Follow the steps below.')).toBeVisible()
  await expect(page.getByRole('tab', { name: 'Step-by-Step' })).toHaveAttribute('aria-selected', 'true')
  expect(statuses).toEqual([200])
})
