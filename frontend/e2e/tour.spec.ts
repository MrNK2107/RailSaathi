import { devices, expect, test } from '@playwright/test'

// Virtual tour smoke test against the real backend: the lazy tour chunk loads, three.js renders into a WebGL
// canvas (headless Chromium through SwiftShader), and the honest labels and empty states are shown.
test.use({
  viewport: devices['iPhone 13'].viewport, isMobile: true, hasTouch: true,
  launchOptions: { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] },
})

test('tour route: schematic 3D model of Chennai Central with a route fly-through', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  await page.goto('/#/tour?station=chennai_central')

  await expect(page.getByRole('heading', { name: 'Explore the station' })).toBeVisible()
  await expect(page.getByTestId('schematic-label')).toHaveText('Schematic — not to scale')
  await expect(page.getByTestId('osm-attribution')).toHaveText('© OpenStreetMap contributors')
  await expect(page.getByTestId('world-note')).toContainText('within about 6 m')
  const scene = page.getByRole('img', { name: /3D schematic model of Chennai Central/ })
  await expect(scene.locator('canvas')).toBeVisible()
  expect(await scene.locator('canvas').evaluate((c: HTMLCanvasElement) => !!(c.getContext('webgl2') || c.getContext('webgl')))).toBe(true)
  await expect(page.getByText(/WebGL is not available/)).toHaveCount(0)

  // Chennai Central has no authored panoramas yet: an explanation and a link-out, no "See it" buttons.
  await expect(page.getByText(/No Street View panoramas are linked/)).toBeVisible()
  await expect(page.getByRole('button', { name: /in Street View$/ })).toHaveCount(0)

  await page.getByLabel('To platform or facility').selectOption('platform_10')
  await expect(page.getByRole('button', { name: 'Play the route fly-through' })).toBeVisible()
  await page.getByRole('button', { name: 'Play the route fly-through' }).click()
  await expect(page.getByRole('button', { name: 'Stop the fly-through' })).toBeVisible()
  expect(errors).toEqual([])
})

test('tour route: an untraced station shows the routing notice and no route controls', async ({ page }) => {
  await page.goto('/#/tour?station=chennai_egmore')
  await expect(page.getByText(/Step-by-step directions are not available for this station/)).toBeVisible()
  await expect(page.getByTestId('schematic-label')).toBeVisible()
  await expect(page.getByLabel('To platform or facility')).toHaveCount(0)
})
