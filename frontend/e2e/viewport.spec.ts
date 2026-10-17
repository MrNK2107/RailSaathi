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
      await page.locator('#voice-input').fill(lang === 'ta' ? 'நாளை காலை 9 மணிக்குள் கோவையிலிருந்து சென்னைக்கு, 2 பேர்' : 'Coimbatore to Chennai before 9 AM tomorrow, 2 passengers')
      await page.getByRole('button', { name: lang === 'ta' ? 'அனுப்பு' : 'Send' }).click()
      await expect(page.getByTestId('voice-strip')).toBeVisible()
      expect(await noHorizontalScroll(page)).toBe(true)
      if (SHOTS) await page.screenshot({ path: `${SHOTS}/plan-started-${lang}.png`, fullPage: true })
    })

    test('profile fits the viewport and has no classic view link', async ({ page }) => {
      await openPlan(page, lang)
      await page.goto('/#/profile')
      await expect(page.getByRole('button', { name: 'English' })).toBeVisible()
      await expect(page.locator('body')).not.toContainText(/classic|demo/i)
      expect(await noHorizontalScroll(page)).toBe(true)
      if (SHOTS) await page.screenshot({ path: `${SHOTS}/profile-${lang}.png`, fullPage: true })
    })

    test('station navigation fits the viewport: Chennai Central routed, Egmore routing disabled', async ({ page }) => {
      await openNavigation(page, lang)
      await page.locator('#nav-to').selectOption({ label: 'Platform 10' })
      await expect(page.getByTestId('route-line')).toBeVisible()
      await expect(page.getByTestId('station-map')).toBeVisible()
      // The demo backend has no Gemini vision service: Chennai Central's AR tab is shown disabled, with the reason.
      await expect(page.getByRole('tab', { name: 'AR' })).toHaveAttribute('aria-disabled', 'true')
      await expect(page.locator('[data-code="ar_not_switched_on"]')).toContainText('Gemini')
      await expect(page.locator('[data-code="ar_not_switched_on"]')).toHaveAttribute('data-reason', 'vision_unavailable')
      const clipped = await page.getByRole('tablist').locator('[role=tab] span').evaluateAll((spans) =>
        spans.filter((el) => el.scrollWidth > el.clientWidth + 0.5).map((el) => el.textContent))
      expect(clipped).toEqual([])  // short labels: nothing truncated at 412 px either
      await expect(page.getByTestId('station-explore')).toBeVisible()
      expect(await noHorizontalScroll(page)).toBe(true)
      if (SHOTS) await page.screenshot({ path: `${SHOTS}/navigation-chennai-central-${lang}.png`, fullPage: true })
      await page.locator('#nav-station').selectOption('chennai_egmore')
      await expect(page.locator('[data-code="routing_unavailable"]')).toBeVisible()
      await expect(page.locator('#nav-to')).toHaveCount(0)
      expect(await noHorizontalScroll(page)).toBe(true)
      if (SHOTS) await page.screenshot({ path: `${SHOTS}/navigation-egmore-${lang}.png`, fullPage: true })
    })
  })
}

async function openNavigation(page: Page, lang: 'en' | 'ta') {
  await openPlan(page, lang)
  await page.goto('/#/navigation')
  await expect(page.getByRole('heading', { level: 1, name: lang === 'ta' ? 'நிலைய வழிகாட்டி' : 'Station Navigation' })).toBeVisible()
  await expect(page.locator('#nav-to')).toBeVisible()
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

  for (const lang of ['en', 'ta'] as const) {
    test(`the empty composer placeholder stays on one line, with no scrollbar (${lang})`, async ({ page }) => {
      await openPlan(page, lang)
      await page.goto('/#/plan')
      const box = page.locator('#voice-input')
      await expect(box).toHaveAttribute('placeholder', lang === 'ta' ? 'எங்கே செல்ல வேண்டும்?' : 'Where do you want to go?')
      const fit = await box.evaluate((el) => {
        const s = getComputedStyle(el)
        const line = parseFloat(s.lineHeight) || parseFloat(s.fontSize) * 1.5
        const content = el.clientHeight - parseFloat(s.paddingTop) - parseFloat(s.paddingBottom)
        return { oneLine: content < line * 2, noScroll: el.scrollHeight <= el.clientHeight + 1, overflow: s.overflowY, wrap: s.whiteSpace }
      })
      expect(fit).toEqual({ oneLine: true, noScroll: true, overflow: 'hidden', wrap: 'nowrap' })
      // The send button sits inside the box, and the text area (where the placeholder and its ellipsis are drawn)
      // ends before the button: the placeholder never runs under it.
      const send = await page.getByRole('button', { name: lang === 'ta' ? 'அனுப்பு' : 'Send' }).boundingBox()
      const frame = await page.getByTestId('composer-box').boundingBox()
      const textRight = await box.evaluate((el) => el.getBoundingClientRect().right - parseFloat(getComputedStyle(el).paddingRight))
      expect(send && frame).toBeTruthy()
      expect(send!.x).toBeGreaterThanOrEqual(frame!.x)
      expect(send!.x + send!.width).toBeLessThanOrEqual(frame!.x + frame!.width)
      expect(textRight).toBeLessThanOrEqual(send!.x)
    })

    test(`the composer grows to show long text pasted into the empty box (${lang})`, async ({ page }) => {
      await openPlan(page, lang)
      await page.goto('/#/plan')
      const box = page.locator('#voice-input')
      await box.fill('Coimbatore to Chennai before 9 AM tomorrow, 2 passengers, window seats please, an AC chair car train')
      const fit = await box.evaluate((el) => ({ grown: el.clientHeight > 60, noScroll: el.scrollHeight <= el.clientHeight + 1 }))
      expect(fit).toEqual({ grown: true, noScroll: true })
    })

    test(`the Map / Steps / AR guidance tabs fit without truncation (${lang})`, async ({ page }) => {
      await openNavigation(page, lang)
      const tabs = page.getByRole('tablist').getByRole('tab')
      await expect(tabs).toHaveCount(3)
      expect((await tabs.allTextContents()).map((t) => t.trim())).toEqual(lang === 'ta' ? ['வரைபடம்', 'படிகள்', 'AR'] : ['Map', 'Steps', 'AR'])
      const clipped = await page.getByRole('tablist').locator('[role=tab] span').evaluateAll((spans) =>
        spans.filter((el) => el.scrollWidth > el.clientWidth + 0.5).map((el) => el.textContent))
      expect(clipped).toEqual([])
      expect(await noHorizontalScroll(page)).toBe(true)
      if (SHOTS) await page.screenshot({ path: `${SHOTS}/navigation-tabs-320-${lang}.png` })
    })
  }

  test('station navigation does not scroll horizontally, routed or routing disabled', async ({ page }) => {
    await openNavigation(page, 'en')
    await page.locator('#nav-to').selectOption({ label: 'Platform 10' })
    await expect(page.getByTestId('route-line')).toBeVisible()
    expect(await noHorizontalScroll(page)).toBe(true)
    await page.getByRole('tab', { name: 'Steps' }).click()
    await expect(page.getByRole('list', { name: 'Step-by-Step' })).toBeVisible()
    expect(await noHorizontalScroll(page)).toBe(true)
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/navigation-chennai-central-320.png`, fullPage: true })
    await page.locator('#nav-station').selectOption('chennai_egmore')
    await expect(page.locator('[data-code="routing_unavailable"]')).toBeVisible()
    expect(await noHorizontalScroll(page)).toBe(true)
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/navigation-egmore-320.png`, fullPage: true })
  })
})
