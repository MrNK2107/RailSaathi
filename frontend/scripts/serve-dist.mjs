// Serves the production build (dist/) the way nginx/default.conf.template does, for the e2e-dist Playwright suite
// (CSP in a real browser, the service worker, stale chunks) when Docker is not available. It sends the exact headers
// of nginx/security-headers.conf (parsed from the file, so the CSP under test is the deployed one), the same
// Cache-Control per path, 404 for files that do not exist, and proxies /api/* to BACKEND_URL.
//   node scripts/serve-dist.mjs        PORT (default 4173), BACKEND_URL (default http://127.0.0.1:8000)
import { createReadStream, existsSync, readFileSync, statSync } from 'node:fs'
import { createServer, request } from 'node:http'
import { extname, join, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const DIST = resolve(ROOT, 'dist')
const PORT = Number(process.env.PORT ?? 4173)
const BACKEND = new URL(process.env.BACKEND_URL ?? 'http://127.0.0.1:8000')

const SECURITY_HEADERS = readFileSync(join(ROOT, 'nginx', 'security-headers.conf'), 'utf8')
  .split('\n')
  .map((line) => /^add_header (\S+) "(.*)" always;\s*$/.exec(line))
  .filter(Boolean)
  .map(([, name, value]) => [name, value])
if (!SECURITY_HEADERS.some(([name]) => name === 'Content-Security-Policy')) throw new Error('no CSP in security-headers.conf')

const TYPES = {
  '.html': 'text/html; charset=utf-8', '.js': 'application/javascript', '.css': 'text/css', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.webp': 'image/webp', '.json': 'application/json',
  '.webmanifest': 'application/manifest+json', '.woff2': 'font/woff2', '.glb': 'model/gltf-binary',
}

function cacheControl(path) {
  if (path.startsWith('/assets/')) return 'public, max-age=31536000, immutable'
  if (['/', '/index.html', '/sw.js', '/manifest.webmanifest'].includes(path)) return 'no-cache'
  return null
}

function proxy(req, res) {
  const upstream = request({
    host: BACKEND.hostname, port: BACKEND.port, method: req.method, path: req.url,
    headers: { ...req.headers, host: BACKEND.host },
  }, (up) => {
    res.writeHead(up.statusCode ?? 502, up.headers)
    up.pipe(res)
  })
  upstream.on('error', () => { res.writeHead(502); res.end('bad gateway') })
  req.pipe(upstream)
}

createServer((req, res) => {
  for (const [name, value] of SECURITY_HEADERS) res.setHeader(name, value)
  const path = decodeURIComponent(new URL(req.url ?? '/', 'http://x').pathname)
  if (path === '/api' || path.startsWith('/api/')) return proxy(req, res)
  if (path === '/healthz') return res.writeHead(200, { 'Content-Type': 'text/plain' }).end('ok\n')

  const file = resolve(DIST, `.${path === '/' ? '/index.html' : path}`)
  if (!file.startsWith(DIST + sep) || !existsSync(file) || !statSync(file).isFile()) {
    return res.writeHead(404, { 'Content-Type': 'text/plain' }).end('not found')
  }
  const cache = cacheControl(path)
  if (cache) res.setHeader('Cache-Control', cache)
  res.writeHead(200, { 'Content-Type': TYPES[extname(file)] ?? 'application/octet-stream' })
  if (req.method === 'HEAD') return res.end()
  createReadStream(file).pipe(res)
}).listen(PORT, '127.0.0.1', () => console.log(`dist on http://127.0.0.1:${PORT} (API -> ${BACKEND.origin})`))
