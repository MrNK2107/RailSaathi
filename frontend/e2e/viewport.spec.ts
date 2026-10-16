import { devices, expect, test, type Page } from '@playwright/test'

// Phone-width layout checks: no horizontal scroll at 320 px, and optional Pixel 7 screenshots
// (set SCREENSHOT_DIR to save them; nothing is written otherwise).
const SHOTS = process.env.SCREENSHOT_DIR

const noHorizontalScroll = (page: Page) =>
  page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)

async function openPlan(page: Page, lang: 'en' | 'ta') {
  await page.goto('/#/home')
  if (lang === 'ta') await page.getByRole('button', { name: 'தமிழ்' }).click()
  await expect(page.getByRole('heading', { level: 2, name: lang === 'ta' ? 'பிரபல வழித்தடங்கள்' : 'Popular Routes' })).toBeVisible()
}

for (const lang of ['en', 'ta'] as const) {
  test.describe(`Pixel 7 (${lang})`, () => {
    test.use({ viewport: { width: 412, height: 915 }, isMobile: true, hasTouch: true, userAgent: devices['Pixel 7'].userAgent })

    test('home and plan screens fit the viewport', async ({ page }) => {
      await openPlan(page, lang)
      expect(await noHorizontalScroll(page)).toBe(true)
      if (SHOTS) await page.screenshot({ path: `${SHOTS}/home-${lang}.png`, fullPage: true })
      await page.getByRole('button', { name: /^(Plan Your Journey|பயணத்தைத் திட்டமிடுங்கள்)/ }).click()
      await expect(page).toHaveURL(/#\/plan/)
      await expect(page.getByTestId('voice-hero')).toBeVisible()
      expect(await noHorizontalScroll(page)).toBe(true)
      if (SHOTS) await page.screenshot({ path: `${SHOTS}/plan-${lang}.png`, fullPage: true })
    })
  })
}

test.describe('320 px width', () => {
  test.use({ viewport: { width: 320, height: 640 }, isMobile: true, hasTouch: true })

  test('home, plan and a started conversation do not scroll horizontally', async ({ page }) => {
    await page.goto('/#/home')
    await page.getByRole('button', { name: 'View All' }).click()
    expect(await noHorizontalScroll(page)).toBe(true)
    await page.getByRole('button', { name: /Plan Your Journey/ }).click()
    await expect(page.getByTestId('voice-hero')).toBeVisible()
    expect(await noHorizontalScroll(page)).toBe(true)
    await page.getByLabel('Type your journey request').fill('Coimbatore to Chennai before 9 AM tomorrow, 2 passengers')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(page.getByTestId('voice-strip')).toBeVisible()
    await expect(page.getByRole('region', { name: 'Journey details' })).toBeVisible()
    expect(await noHorizontalScroll(page)).toBe(true)
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/plan-started-320.png`, fullPage: true })
  })
})
