import { devices, expect, test, type Page } from '@playwright/test'

// The installable app shell on the production build: the manifest, the service worker (app shell only, never /api/*,
// versioned cache), offline start, and recovery from a lazy chunk that disappeared in a deploy.
test.use({ viewport: devices['iPhone 13'].viewport, isMobile: true, hasTouch: true })

const API = /\/api(\/|$)/

async function controlledHome(page: Page) {
  await page.goto('/#/home')
  await expect(page.getByText('Popular Routes')).toBeVisible()
  await page.evaluate(() => navigator.serviceWorker.ready)
  // The first load registers the worker; the next one is served through it.
  await page.reload()
  await expect(page.getByText('Popular Routes')).toBeVisible()
  expect(await page.evaluate(() => !!navigator.serviceWorker.controller)).toBe(true)
}

test('manifest and icons are served and linked from the shell', async ({ page, request }) => {
  await page.goto('/#/home')
  expect(await page.locator('link[rel="manifest"]').getAttribute('href')).toBe('/manifest.webmanifest')
  const res = await request.get('/manifest.webmanifest')
  expect(res.headers()['content-type']).toContain('application/manifest+json')
  const manifest = await res.json()
  expect(manifest).toMatchObject({ short_name: 'RailSaathi', start_url: '/#/home', display: 'standalone', scope: '/' })
  for (const icon of manifest.icons as { src: string; type: string }[]) {
    const r = await request.get(icon.src)
    expect(r.status(), icon.src).toBe(200)
    expect(r.headers()['content-type'], icon.src).toContain(icon.type)
  }
  expect((await request.get('/sw.js')).headers()['cache-control']).toBe('no-cache')
})

test('the service worker caches the app shell and never an /api response', async ({ page }) => {
  const fromWorker: { url: string; worker: boolean }[] = []
  page.on('response', (r) => fromWorker.push({ url: r.url(), worker: r.fromServiceWorker() }))
  await controlledHome(page)

  // Use the API through the worker: a planner turn and a station route.
  await page.goto('/#/plan')
  await page.getByLabel('Type your journey request').fill('Coimbatore to Chennai before 9 AM tomorrow, 2 passengers')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByRole('region', { name: 'Journey details' })).toBeVisible()
  await page.goto('/#/navigation')
  await page.locator('#nav-to').selectOption('platform_10')
  await expect(page.getByTestId('route-line')).toBeVisible()

  const api = fromWorker.filter((r) => API.test(new URL(r.url).pathname))
  expect(api.length).toBeGreaterThan(3)
  expect(api.filter((r) => r.worker), 'API responses served by the worker').toEqual([])
  expect(fromWorker.some((r) => r.worker && r.url.includes('/assets/'))).toBe(true)

  const caches = await page.evaluate(async () => {
    const names = await window.caches.keys()
    const urls = (await Promise.all(names.map(async (n) => (await (await window.caches.open(n)).keys()).map((q) => q.url)))).flat()
    return { names, paths: urls.map((u) => new URL(u).pathname) }
  })
  expect(caches.names).toHaveLength(1)
  expect(caches.names[0]).toMatch(/^railsaathi-shell-[0-9a-f]{12}$/)
  expect(caches.paths).toContain('/index.html')
  expect(caches.paths).toContain('/manifest.webmanifest')
  expect(caches.paths.some((p) => /^\/assets\/index-.*\.js$/.test(p))).toBe(true)
  expect(caches.paths.filter((p) => API.test(p)), 'cached /api entries').toEqual([])
})

test('a cache from an older version is deleted when the worker activates', async ({ page }) => {
  // A previous deploy's cache, written as the page starts: before the load event registers this build's worker.
  await page.addInitScript(() => {
    void window.caches.open('railsaathi-shell-000000000000').then((old) => old.put('/index.html', new Response('old shell')))
  })
  await page.goto('/#/home')
  await page.evaluate(() => navigator.serviceWorker.ready)
  await expect.poll(() => page.evaluate(() => window.caches.keys())).toEqual([expect.stringMatching(/^railsaathi-shell-(?!000000000000)/)])
})

test('the installed shell starts offline', async ({ page, context }) => {
  await controlledHome(page)
  await context.setOffline(true)
  await page.reload()
  await expect(page.getByText('Popular Routes')).toBeVisible()
  await context.setOffline(false)
})

test.describe('stale lazy chunks after a deploy', () => {
  test.use({ serviceWorkers: 'block' })

  test('a missing screen chunk reloads the page once and the screen opens', async ({ page }) => {
    let documents = 0
    page.on('request', (r) => { if (r.resourceType() === 'document') documents += 1 })
    await page.goto('/#/home')
    await expect(page.getByText('Popular Routes')).toBeVisible()
    // The old build's StationNavigation chunk is gone from the server once; after the reload it is served again.
    let missing = true
    await page.route(/\/assets\/StationNavigation-[^/]+\.js$/, (route) => {
      if (!missing) return route.continue()
      missing = false
      return route.fulfill({ status: 404, body: 'gone' })
    })
    await page.getByRole('button', { name: /Station Navigation/ }).first().click()
    await expect(page.getByRole('heading', { level: 1, name: 'Station Navigation' })).toBeVisible()
    expect(documents).toBe(2)
  })

  test('a chunk that keeps failing reloads only once, then shows the reload message', async ({ page }) => {
    let documents = 0
    page.on('request', (r) => { if (r.resourceType() === 'document') documents += 1 })
    await page.route(/\/assets\/TicketingGuidance-[^/]+\.js$/, (route) => route.fulfill({ status: 404, body: 'gone' }))
    await page.goto('/#/ticketing')
    await expect(page.locator('[data-code="screen_load_failed"]')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Reload' })).toBeVisible()
    expect(documents).toBe(2)
  })
})
