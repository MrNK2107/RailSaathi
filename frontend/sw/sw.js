// RailSaathi app-shell service worker. Template: the build (scripts/serviceWorkerPlugin.ts) writes dist/sw.js from
// this file, filling in VERSION (a hash of every emitted file name, so each deploy that changes any chunk is a new
// worker with a new cache) and SHELL_ASSETS (the entry chunk, its static imports and its CSS). It is only registered
// in production builds (src/pwa.ts).
//
// What it handles (same-origin GET only):
//   - navigations (the HTML shell; the app uses hash routes, so every navigation is '/'): NETWORK FIRST. A deploy is
//     picked up on the next load and the cached shell is used only when the network fails, so a stale index.html is
//     never served while the network works and the hashed chunk names it references exist on the server.
//   - /assets/*: hashed, immutable build files, cache first. Lazy screen chunks are cached the first time they load.
//   - the manifest and icons: precached on install.
// What it never touches: /api/* (journey data, /api/client-config, POST /api/navigation/localize camera frames),
// every non-GET request, and every cross-origin request (Google Maps / Street View, fonts). For those it does not call
// respondWith, so the browser goes straight to the network and nothing is stored.
//
// After a deploy the new worker activates at once and deletes the previous version's cache. A tab still running the
// old build then cannot fetch an old lazy chunk (gone from the server and the cache); src/staleChunks.ts reloads the
// page once in that case, which fetches the new shell.
const VERSION = '__BUILD_VERSION__'
const CACHE = `railsaathi-shell-${VERSION}`
const SHELL = '/index.html'
const SHELL_ASSETS = [/* __SHELL_ASSETS__ */]
const STATIC = ['/manifest.webmanifest', '/favicon.svg', '/icon-192.png', '/icon-512.png']

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll([SHELL, ...SHELL_ASSETS, ...STATIC].map((url) => new Request(url, { cache: 'reload' }))))
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith('railsaathi-shell-') && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  )
})

async function networkFirstShell(request) {
  const cache = await caches.open(CACHE)
  try {
    const response = await fetch(request)
    if (response.ok) await cache.put(SHELL, response.clone())
    return response
  } catch (err) {
    const cached = await cache.match(SHELL)
    if (cached) return cached
    throw err
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(CACHE)
  const cached = await cache.match(request)
  if (cached) return cached
  const response = await fetch(request)
  if (response.ok && response.type === 'basic') await cache.put(request, response.clone())
  return response
}

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return
  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return
  if (url.pathname === '/api' || url.pathname.startsWith('/api/')) return
  if (request.mode === 'navigate') event.respondWith(networkFirstShell(request))
  else if (url.pathname.startsWith('/assets/') || STATIC.includes(url.pathname)) event.respondWith(cacheFirst(request))
})
