/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    testTimeout: 15000,
    // Threads use far less memory than forked processes (forks ran out of memory on the dev machine).
    pool: 'threads',
    poolOptions: { threads: { minThreads: 1, maxThreads: 2 } },
  },
})
