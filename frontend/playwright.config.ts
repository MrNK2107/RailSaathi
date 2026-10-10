import { defineConfig } from '@playwright/test'

// E2E tests drive the real frontend against the real backend.
// Start both servers first (see README), or let `webServer` start them.
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  use: { baseURL: 'http://localhost:5173', channel: 'chrome', headless: true, screenshot: 'only-on-failure' },
  webServer: [
    { command: 'uv run uvicorn app.main:app --port 8000', cwd: '../backend', url: 'http://localhost:8000/api/health', reuseExistingServer: true },
    { command: 'npx vite --port 5173 --strictPort', url: 'http://localhost:5173', reuseExistingServer: true },
  ],
})
