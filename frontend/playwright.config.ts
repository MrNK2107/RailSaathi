import { defineConfig } from '@playwright/test'

// E2E tests drive the real frontend (Vite dev server over plain HTTP) against the real backend in demo mode.
// Locally, running servers are reused; in CI both are started fresh.
// Set E2E_BACKEND_PORT when port 8000 is taken by something else on your machine.
const CI = !!process.env.CI
const BACKEND_PORT = process.env.E2E_BACKEND_PORT ?? '8000'
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: CI ? 1 : 0,
  reporter: CI ? [['github'], ['html', { open: 'never' }]] : 'list',
  use: { baseURL: 'http://127.0.0.1:5173', headless: true, screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  webServer: [
    {
      command: `uv run python -m uvicorn app.main:app --port ${BACKEND_PORT}`,
      cwd: '../backend',
      url: `${BACKEND_URL}/api/health`,
      reuseExistingServer: !CI,
      // Frozen clock (same instant as backend/tests/conftest.py) so 'tomorrow before 9 AM' is deterministic.
      env: { RAILWAY_DATA_MODE: 'demo', LLM_PROVIDER: 'none', FIXED_NOW: '2026-10-10T10:00:00+05:30' },
    },
    {
      command: 'npx vite --port 5173 --strictPort',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: !CI,
      env: { VITE_API_BASE_URL: BACKEND_URL, BACKEND_URL },
    },
  ],
})
