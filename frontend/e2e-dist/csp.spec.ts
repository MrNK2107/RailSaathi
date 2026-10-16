import { devices, expect, test, type Page } from '@playwright/test'

// The production build under the deployed Content-Security-Policy (nginx/security-headers.conf), in a real browser.
// Every `securitypolicyviolation` event and every console CSP report is collected while the main screens run,
// including the lazy 3D tour (three.js, WebGL through SwiftShader), the station map and AR camera guidance (Chromium's
// fake camera). Any violation fails the test.
test.use({
  viewport: devices['iPhone 13'].viewport, isMobile: true, hasTouch: true,
  serviceWorkers: 'block', // the worker is covered by pwa.spec.ts; here every request goes to the server
  permissions: ['camera'],
  launchOptions: { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist',
    '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] },
})

async function watchCsp(page: Page) {
  const reports: string[] = []
  await page.addInitScript(() => {
    document.addEventListener('securitypolicyviolation', (e) => {
      const w = window as unknown as { __csp?: string[] }
      ;(w.__csp ??= []).push(`${e.violatedDirective} blocked ${e.blockedURI || '(inline)'} at ${e.sourceFile}:${e.lineNumber}`)
    })
  })
  page.on('console', (msg) => { if (/Content[- ]Security[- ]Policy/i.test(msg.text())) reports.push(msg.text()) })
  page.on('pageerror', (err) => reports.push(`pageerror: ${err.message}`))
  return async () => [...reports, ...await page.evaluate(() => (window as unknown as { __csp?: string[] }).__csp ?? [])]
}

test('the deployed CSP header is sent with the shell', async ({ request }) => {
  const res = await request.get('/')
  expect(res.headers()['content-security-policy']).toContain("script-src 'self'")
  expect(res.headers()['content-security-policy']).toContain("frame-ancestors 'none'")
})

test('home, planner chat, station navigation and the 3D tour run without a CSP violation', async ({ page }) => {
  const violations = await watchCsp(page)

  await page.goto('/#/home')
  await expect(page.getByText('Popular Routes')).toBeVisible()

  await page.getByRole('button', { name: /Plan Your Journey/ }).click()
  await expect(page.getByTestId('voice-hero')).toBeVisible()
  await page.getByLabel('Type your journey request').fill('I need to reach Chennai before 9 AM tomorrow from Coimbatore, 2 passengers, cheapest')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByText('Journey options ready')).toBeVisible()
  expect(await violations(), 'home and plan').toEqual([])

  await page.goto('/#/navigation')
  await expect(page.getByRole('heading', { name: 'Station Navigation' })).toBeVisible()
  await page.locator('#nav-to').selectOption('platform_10')
  await expect(page.getByTestId('route-line')).toBeVisible()
  // The floor plan image is same-origin /api/stations/{id}/map.
  await expect.poll(() => page.getByTestId('station-map').locator('img').first().evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0)
  expect(await violations(), 'navigation').toEqual([])

  await page.goto('/#/tour?station=chennai_central')
  await page.reload()
  const scene = page.getByRole('img', { name: /3D schematic model of Chennai Central/ })
  await expect(scene.locator('canvas')).toBeVisible()
  await page.getByLabel('To platform or facility').selectOption('platform_10')
  await page.getByRole('button', { name: 'Play the route fly-through' }).click()
  await expect(page.getByRole('button', { name: 'Stop the fly-through' })).toBeVisible()
  expect(await violations(), 'tour').toEqual([])
})

test('AR camera guidance (camera stream, frame upload, arrow) runs without a CSP violation', async ({ page }) => {
  const violations = await watchCsp(page)
  // Same scripted backend answers as e2e/ar.spec.ts: AR enabled for Chennai Central and one position fix.
  await page.route('**/api/client-config', (route) => route.fulfill({ json: {
    google_maps_browser_key: null, features: { ar_guidance_stations: ['chennai_central'], simulate_closures: true } } }))
  await page.route('**/api/navigation/localize', (route) => route.fulfill({ json: {
    status: 'fix', station_id: 'chennai_central',
    fix: { node_id: 'cj_north', node_name: 'Concourse North Junction', level: 0, position: [0.49039, 0.31944], confidence: 0.81,
      facing_bearing_deg: 180, matched_cues: [] },
    candidates: [], confidence_threshold: 0.6, latency_ms: 950, message: null, session_token: 'e2e-token',
    provenance: { mode: 'live', source: 'gemini-vision', as_of: '2026-10-16T10:00:00Z', note: 'Approximate.' },
  } }))
  await page.goto('/#/navigation')
  await page.locator('#nav-to').selectOption('platform_10')
  await page.getByRole('tab', { name: 'AR' }).click()
  await page.getByRole('button', { name: 'Start camera' }).click()
  await expect(page.getByTestId('ar-arrow')).toBeVisible()
  await expect(page.getByText(/Near Concourse North Junction/)).toBeVisible()
  expect(await violations(), 'AR guidance').toEqual([])
})
