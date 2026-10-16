import { defineConfig } from '@playwright/test'
import base from './playwright.config'

// Production-build e2e (e2e-dist/): the CSP in a real browser, the service worker and stale-chunk recovery. These need
// the built dist/ behind nginx's headers, which the Vite dev server does not send. `npm run e2e:dist` builds first.
//   default         scripts/serve-dist.mjs serves dist/ with nginx/security-headers.conf on :4173
//   DIST_BASE_URL   point at a running frontend container instead (docker run ... railsaathi-frontend), which must
//                   proxy /api to a demo backend; only the backend web server is then started here.
const DIST_BASE_URL = process.env.DIST_BASE_URL
const BACKEND_PORT = process.env.E2E_BACKEND_PORT ?? '8000'
const [backend] = Array.isArray(base.webServer) ? base.webServer : []

export default defineConfig({
  ...base,
  testDir: './e2e-dist',
  use: { ...base.use, baseURL: DIST_BASE_URL ?? 'http://127.0.0.1:4173' },
  webServer: DIST_BASE_URL ? [] : [
    backend,
    {
      command: 'node scripts/serve-dist.mjs',
      url: 'http://127.0.0.1:4173/healthz',
      reuseExistingServer: !process.env.CI,
      env: { PORT: '4173', BACKEND_URL: `http://127.0.0.1:${BACKEND_PORT}` },
    },
  ],
})
