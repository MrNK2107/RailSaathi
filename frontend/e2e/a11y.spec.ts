import { devices, expect, test } from '@playwright/test'
import { expectNoAxeViolations } from './axe'

// axe-core on every screen of the mobile app, in the states a passenger actually sees them: the planner flow from the
// home screen to a saved trip, station navigation routed (map, steps, turn-by-turn, a simulated closure) and untraced,
// the tab pages, the help / goal / ticketing screens, Tamil, and the 3D tour. Real backend in demo mode.
// SwiftShader gives headless Chromium WebGL for the tour (launch options are per file, not per describe).
test.use({
  viewport: devices['iPhone 13'].viewport, isMobile: true, hasTouch: true,
  launchOptions: { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] },
})

test('planner flow: home, voice hero, chat, options, details, confirmation and the tab pages', async ({ page }) => {
  await page.goto('/#/home')
  await expect(page.getByText('Popular Routes')).toBeVisible()
  await expectNoAxeViolations(page, 'home')

  await page.getByRole('button', { name: /Plan Your Journey/ }).click()
  await expect(page.getByTestId('voice-hero')).toBeVisible()
  await expectNoAxeViolations(page, 'plan (voice hero)')

  await page.getByLabel('Type your journey request').fill('I need to reach Chennai before 9 AM tomorrow from Coimbatore, 2 passengers, cheapest')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByText('Journey options ready')).toBeVisible()
  await expectNoAxeViolations(page, 'plan (chat with journey card)')

  await page.getByRole('button', { name: 'View journey options' }).click()
  await expect(page.getByRole('tab', { name: 'Best Match' })).toBeVisible()
  await expectNoAxeViolations(page, 'options')

  await page.getByRole('button', { name: /View details: D103/ }).click()
  await expect(page.getByRole('heading', { name: 'Journey Details' })).toBeVisible()
  await expectNoAxeViolations(page, 'details')

  await page.getByRole('button', { name: /Confirm & Continue/ }).click()
  await expect(page.getByText('Journey Plan Ready!')).toBeVisible()
  await expectNoAxeViolations(page, 'confirmation')

  await page.getByRole('button', { name: /Save to My Trips/ }).click()
  await page.getByRole('button', { name: 'My Trips' }).click()
  await expect(page.getByText(/D103 Nilgiri Night Express/)).toBeVisible()
  await expectNoAxeViolations(page, 'trips (one saved trip)')

  await page.getByRole('button', { name: 'Alerts' }).click()
  await expect(page).toHaveURL(/#\/alerts/)
  await expectNoAxeViolations(page, 'alerts (plan confirmed)')

  await page.getByRole('button', { name: 'Profile' }).click()
  await expect(page).toHaveURL(/#\/profile/)
  await expectNoAxeViolations(page, 'profile')
})

test('empty tab pages, help, goal and ticketing', async ({ page }) => {
  for (const [route, heading] of [['trips', 'My Trips'], ['alerts', 'Alerts'], ['help', 'Help & Assistance'],
    ['goal', null], ['ticketing', null]] as const) {
    await page.goto(`/#/${route}`)
    await expect(page).toHaveURL(new RegExp(`#/${route}`))
    if (heading) await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible()
    else await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await expectNoAxeViolations(page, route)
  }
  // The emergency dialog opened from the help screen.
  await page.goto('/#/help')
  await page.getByRole('button', { name: /Station SOS/ }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expectNoAxeViolations(page, 'help (emergency dialog)')
})

test('station navigation: routed with map, steps, turn-by-turn and a simulated closure; untraced station', async ({ page }) => {
  await page.goto('/#/navigation')
  await expect(page.getByRole('heading', { name: 'Station Navigation' })).toBeVisible()
  await expect(page.locator('#nav-to')).toBeVisible()
  await expectNoAxeViolations(page, 'navigation (no destination)')

  await page.locator('#nav-to').selectOption({ label: 'Platform 10' })
  await expect(page.getByTestId('route-line')).toBeVisible()
  await expectNoAxeViolations(page, 'navigation (routed, map)')

  await page.getByRole('tab', { name: 'Steps' }).click()
  await expect(page.getByRole('list', { name: 'Step-by-Step' })).toBeVisible()
  await expectNoAxeViolations(page, 'navigation (step list)')

  await page.getByRole('button', { name: /Start Navigation/ }).click()
  await expect(page.getByTestId('current-step')).toContainText('Step 1 of')
  await expectNoAxeViolations(page, 'navigation (turn-by-turn)')
  await page.getByRole('button', { name: 'Exit navigation' }).click()

  // The demo backend accepts what-if closures, so the simulator is shown: close the first segment and reroute.
  const simulator = page.getByTestId('closure-simulator')
  await expect(simulator).toBeVisible()
  await page.locator('#nav-closure').selectOption({ index: 1 })
  await simulator.getByRole('button', { name: 'Close pathway (simulated)' }).click()
  await expect(simulator.getByRole('button', { name: 'Reopen all' })).toBeVisible()
  await expectNoAxeViolations(page, 'navigation (simulated closure)')

  await page.getByRole('button', { name: 'Open station blueprint' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expectNoAxeViolations(page, 'navigation (station blueprint dialog)')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)

  await page.locator('#nav-station').selectOption('chennai_egmore')
  await expect(page.locator('[data-code="routing_unavailable"]')).toBeVisible()
  await expectNoAxeViolations(page, 'navigation (untraced station)')
})

test('Tamil: home, plan and station navigation', async ({ page }) => {
  await page.goto('/#/home')
  await page.getByRole('button', { name: 'தமிழ்' }).click()
  await expect(page.getByRole('heading', { level: 2, name: 'பிரபல வழித்தடங்கள்' })).toBeVisible()
  await expectNoAxeViolations(page, 'home (ta)')
  await page.goto('/#/plan')
  await expect(page.getByTestId('voice-hero')).toBeVisible()
  await expectNoAxeViolations(page, 'plan (ta)')
  await page.goto('/#/navigation')
  await page.locator('#nav-to').selectOption('platform_10')
  await expect(page.getByTestId('route-line')).toBeVisible()
  await expectNoAxeViolations(page, 'navigation (ta, routed)')
})

test.describe('3D tour', () => {
  test('tour of Chennai Central with a route, and an untraced station', async ({ page }) => {
    await page.goto('/#/tour?station=chennai_central')
    await expect(page.getByRole('heading', { name: 'Explore the station' })).toBeVisible()
    await expect(page.getByRole('img', { name: /3D schematic model of Chennai Central/ }).locator('canvas')).toBeVisible()
    await page.getByLabel('To platform or facility').selectOption('platform_10')
    await expect(page.getByRole('button', { name: 'Play the route fly-through' })).toBeVisible()
    await expectNoAxeViolations(page, 'tour (Chennai Central, routed)')

    await page.goto('/#/tour?station=chennai_egmore')
    await page.reload() // the station is read when the tour mounts; a hash change alone keeps the same screen
    await expect(page.getByText(/Step-by-step directions are not available for this station/)).toBeVisible()
    await expectNoAxeViolations(page, 'tour (untraced station)')
  })
})
