/// <reference types="vitest" />
import { fileURLToPath } from 'node:url'
import { coverageConfigDefaults } from 'vitest/config'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { serviceWorker } from './scripts/serviceWorkerPlugin'

const BACKEND = process.env.BACKEND_URL ?? 'http://127.0.0.1:8000'
const PROXIED = ['/api']

// HTTPS (needed for microphone access from other devices on the LAN) is opt-in: VITE_HTTPS=1 npm run dev
export default defineConfig(async () => {
  const plugins = [react(), serviceWorker(fileURLToPath(new URL('./sw/sw.js', import.meta.url)))]
  if (process.env.VITE_HTTPS) {
    const { default: basicSsl } = await import('@vitejs/plugin-basic-ssl')
    plugins.push(basicSsl())
  }
  return {
    plugins,
    build: {
      // Hidden: .map files are emitted for error tooling but the bundles carry no sourceMappingURL comment.
      sourcemap: 'hidden' as const,
      // scripts/check-budget.mjs reads this manifest to enforce the per-chunk gzip budgets.
      manifest: true,
      // Size limits are per chunk, in gzip, in scripts/check-budget.mjs, which `npm run build` runs and which fails the
      // build. Vite's own warning (raw size, one limit for every chunk) is turned off so it cannot drift from them.
      chunkSizeWarningLimit: Number.POSITIVE_INFINITY,
      rollupOptions: {
        output: {
          // React is shared by every screen; three.js is only for the 3D tour. Everything else splits by screen.
          manualChunks(id: string) {
            if (/\/node_modules\/(react|react-dom|scheduler)\//.test(id)) return 'react'
            if (/\/node_modules\/three\//.test(id)) return 'three'
            return undefined
          },
        },
      },
    },
    server: {
      host: '0.0.0.0',
      port: 5173,
      proxy: Object.fromEntries(PROXIED.map((p) => [p, { target: BACKEND, changeOrigin: true }])),
    },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.test.{ts,tsx}'],
      testTimeout: 15000,
      // `npm test` runs with --coverage and fails below 70 % of lines. main.tsx only mounts the app (covered by e2e).
      coverage: {
        provider: 'v8' as const,
        include: ['src/**/*.{ts,tsx}'],
        exclude: [...coverageConfigDefaults.exclude, 'src/test/**', 'src/main.tsx'],
        reporter: ['text-summary', 'lcov'],
        thresholds: { lines: 70 },
      },
      pool: 'threads',
      poolOptions: { threads: { minThreads: 1, maxThreads: 2 } },
    },
  }
})
