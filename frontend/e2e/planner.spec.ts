import { expect, test } from '@playwright/test'

test('plan, select, confirm and reassess a journey end to end', async ({ page }) => {
  await page.goto('/#/classic')
  await expect(page.getByRole('note')).toContainText('DEMO DATA')
  await expect(page.getByText('Planner online')).toBeVisible()

  const input = page.getByLabel('Type your travel request')
  await input.fill('I need to reach Chennai before 9 AM tomorrow.')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByText('Where will you be travelling from?')).toBeVisible()

  await input.fill('Coimbatore')
  await page.getByRole('button', { name: 'Send' }).click()
  await input.fill('2 passengers, cheapest please')
  await page.getByRole('button', { name: 'Send' }).click()

  const cheapest = page.getByRole('article').filter({ hasText: 'Lowest cost' })
  await expect(cheapest).toContainText('D103')
  await cheapest.getByRole('button', { name: 'Select this option' }).click()
  await expect(page.getByText(/No ticket will be booked/).first()).toBeVisible()
  await page.getByRole('button', { name: 'Confirm plan for handoff' }).click()
  await expect(page.getByRole('heading', { name: /Plan confirmed for handoff/ })).toBeVisible()

  await page.getByLabel('Event').selectOption('SIM-DELAY-D103')
  await page.getByRole('button', { name: 'Reassess with event' }).click()
  await expect(page.getByText(/no longer meets your requirements/).first()).toBeVisible()
  await expect(page.getByText('SIMULATED', { exact: true })).toBeVisible()
  await page.screenshot({ path: 'e2e-results/reassessed.png', fullPage: true })
})

test('Tamil language keeps session state', async ({ page }) => {
  await page.goto('/#/classic')
  await page.getByLabel('Language').selectOption('ta')
  const input = page.getByLabel('உங்கள் பயணக் கோரிக்கையைத் தட்டச்சு செய்யவும்')
  await input.fill('நாளை காலை 9 மணிக்குள் கோவையிலிருந்து சென்னைக்கு, அம்மா உடன்')
  await page.getByRole('button', { name: 'அனுப்பு' }).click()
  await expect(page.getByRole('article').first()).toBeVisible()
  await expect(page.getByText(/பரிந்துரைகள் இதோ/)).toBeVisible()
})
