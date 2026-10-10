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
  await expect(page.getByTestId('source-line')).toContainText('Source:')
  await page.getByRole('button', { name: /View details: D103/ }).click()

  await expect(page.getByRole('heading', { name: 'Journey Details' })).toBeVisible()
  await page.getByRole('button', { name: /Confirm & Continue/ }).click()
  await expect(page.getByText('Journey Plan Ready!')).toBeVisible()
  await expect(page.getByText('This is a journey plan only. No ticket has been booked.')).toBeVisible()
  await page.getByRole('button', { name: /Save to My Trips/ }).click()
  await page.getByRole('button', { name: 'My Trips' }).click()
  await expect(page.getByText(/D103 Demo Nilgiri Night Express/)).toBeVisible()
})

test('popular route starts a real plan; placeholders are labelled', async ({ page }) => {
  await page.goto('/#/home')
  await page.getByRole('button', { name: /Chennai → Madurai/ }).click()
  await expect(page).toHaveURL(/#\/plan/)
  await expect(page.getByRole('region', { name: 'Journey details' }).getByText('Madurai')).toBeVisible()
  await page.goto('/#/navigation')
  await expect(page.getByText(/Preview only/)).toBeVisible()
  await expect(page.getByRole('button', { name: /Start Navigation/ })).toBeDisabled()
})
