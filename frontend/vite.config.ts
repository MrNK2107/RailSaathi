/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const BACKEND = process.env.BACKEND_URL ?? 'http://127.0.0.1:8000'
const PROXIED = ['/api']

// HTTPS (needed for microphone access from other devices on the LAN) is opt-in: VITE_HTTPS=1 npm run dev
export default defineConfig(async () => {
  const plugins = [react()]
  if (process.env.VITE_HTTPS) {
    const { default: basicSsl } = await import('@vitejs/plugin-basic-ssl')
    plugins.push(basicSsl())
  }
  return {
    plugins,
    build: {
      // Only the lazy virtual-tour chunk (three.js + @react-three/fiber, ~850 kB raw) is above Vite's 500 kB default;
      // it loads on #/tour and only when WebGL exists. The initial chunk stays far below this limit.
      chunkSizeWarningLimit: 900,
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
      pool: 'threads',
      poolOptions: { threads: { minThreads: 1, maxThreads: 2 } },
    },
  }
})
