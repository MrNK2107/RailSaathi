import { devices, expect, test } from '@playwright/test'

// Mobile-first flow at phone size against the real backend (run the backend with RAILWAY_DATA_MODE=demo).
test.use({ viewport: devices['iPhone 13'].viewport, isMobile: true, hasTouch: true })

test('dashboard → AI planner → options → details → confirm → save trip', async ({ page }) => {
  await page.goto('/#/home')
  await expect(page.getByText('Popular Routes')).toBeVisible()
  await page.getByRole('button', { name: /Plan Your Journey/ }).click()
  await expect(page.getByText('Plan with AI')).toBeVisible()

  await page.getByLabel('Type your journey request').fill('I need to reach Chennai before 9 AM tomorrow from Coimbatore, 2 passengers, cheapest')
  await page.getByRole('button', { name: 'Send' }).click()
  const details = page.getByRole('region', { name: 'Journey details' })
  await expect(details.getByText('Coimbatore')).toBeVisible()
  await expect(page.getByText('Journey options ready')).toBeVisible()

  await page.getByRole('button', { name: 'View journey options' }).click()
  await expect(page.getByRole('tab', { name: 'Best Match' })).toBeVisible()
  // Demo data (local/dev only) is not labelled: no source line, DEMO pill or "Demo data" disclaimer.
  await expect(page.getByTestId('source-line')).toHaveCount(0)
  await expect(page.locator('body')).not.toContainText(/demo/i)
  await page.getByRole('button', { name: /View details: D103/ }).click()

  await expect(page.getByRole('heading', { name: 'Journey Details' })).toBeVisible()
  await page.getByRole('button', { name: /Confirm & Continue/ }).click()
  await expect(page.getByText('Journey Plan Ready!')).toBeVisible()
  await expect(page.getByText('This is a journey plan only. No ticket has been booked.')).toBeVisible()
  await page.getByRole('button', { name: /Save to My Trips/ }).click()
  await page.getByRole('button', { name: 'My Trips' }).click()
  await expect(page.getByText(/D103 Nilgiri Night Express/)).toBeVisible()
})

test('the home screen carries no demo wording, and an old #/classic link opens home', async ({ page }) => {
  await page.goto('/#/home')
  await expect(page.getByText('Popular Routes')).toBeVisible()
  await expect(page.getByTestId('provenance-badge')).toHaveCount(0)
  await expect(page.locator('body')).not.toContainText(/demo/i)
  await page.goto('/#/classic')
  await expect(page.getByText('Popular Routes')).toBeVisible()
  await page.getByRole('button', { name: 'Profile' }).click()
  await expect(page.getByRole('heading', { name: 'Profile' })).toBeVisible()
  await expect(page.locator('body')).not.toContainText(/classic|demo/i)
})

test('popular route starts a real plan; the journey card waits for every detail; station navigation routes to Platform 10', async ({ page }) => {
  await page.goto('/#/home')
  await page.getByRole('button', { name: /Chennai → Madurai/ }).click()
  await expect(page).toHaveURL(/#\/plan/)
  // The chat shows the request and the planner's next question; the journey card stays hidden
  // until every mandatory detail (date, passengers) has been collected.
  const thread = page.getByTestId('chat-thread')
  await expect(thread.getByText('from Chennai to Madurai')).toBeVisible()
  await expect(thread.getByTestId('bubble').filter({ hasText: /\?/ }).last()).toBeVisible()
  await expect(page.getByRole('region', { name: 'Journey details' })).toHaveCount(0)
  // Answer the planner's questions one at a time, as a passenger would.
  for (const answer of ['tomorrow', '1 passenger', 'no preference']) {
    await page.getByLabel('Type your journey request').fill(answer)
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(thread.getByText(answer, { exact: true })).toBeVisible()
  }
  await expect(page.getByRole('region', { name: 'Journey details' }).getByText('Madurai')).toBeVisible()

  // Station navigation: real routing on the Chennai Central floor plan (POST /api/navigation/route).
  await page.goto('/#/navigation')
  await expect(page.getByRole('heading', { name: 'Station Navigation' })).toBeVisible()
  await expect(page.locator('#nav-station')).toHaveValue('chennai_central')
  await page.getByLabel('To', { exact: true }).selectOption({ label: 'Platform 10' })
  // The route is calculated as soon as the destination is chosen (no separate button).
  await expect(page.getByTestId('route-line')).toBeVisible()
  const summary = page.getByLabel('Route summary')
  await expect(summary).toContainText('Recommended route')
  await expect(summary).toContainText('→ Platform 10')
  // Step-by-step shows the same route; turn-by-turn advances in order and can be exited.
  await page.getByRole('tab', { name: 'Steps' }).click()
  const steps = page.getByRole('list', { name: 'Step-by-Step' }).getByRole('listitem')
  await expect(steps.first()).toContainText('Start at')
  await expect(steps.last()).toContainText('Platform 10')
  await page.getByRole('button', { name: /Start Navigation/ }).click()
  await expect(page.getByTestId('current-step')).toContainText('Step 1 of')
  await page.getByRole('button', { name: /Next step/ }).click()
  await expect(page.getByTestId('current-step')).toContainText('Step 2 of')
  await page.getByRole('button', { name: 'Exit navigation' }).click()
  await expect(page.getByRole('button', { name: /Start Navigation/ })).toBeVisible()
  // An untraced station keeps the plan and says routing is unavailable; nothing is requested.
  await page.locator('#nav-station').selectOption('chennai_egmore')
  await expect(page.locator('[data-code="routing_unavailable"]')).toBeVisible()
  await expect(page.getByLabel('To', { exact: true })).toHaveCount(0)
})
