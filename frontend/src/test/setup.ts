import '@testing-library/jest-dom/vitest'
import { configure } from '@testing-library/react'

// Screens are lazy-loaded; on a cold module graph under the full parallel run the first import can exceed the default
// 1 s findBy/waitFor budget, which made a different handful of tests fail each run. Give async queries more headroom.
configure({ asyncUtilTimeout: 5000 })

// jsdom reports errors that React rethrows inside an error boundary ("Error: Uncaught [...]") on its virtual console,
// which Vitest 4 wires to the runner's own console. Route them through the test's console.error instead, so tests that
// expect a caught error and silence console.error silence these reports too (anything else is still printed).
type JsdomVirtualConsole = { removeAllListeners(event: string): void; on(event: string, cb: (e: Error & { detail?: unknown }) => void): void }
const virtualConsole = (window as unknown as { _virtualConsole?: JsdomVirtualConsole })._virtualConsole
if (virtualConsole) {
  virtualConsole.removeAllListeners('jsdomError')
  virtualConsole.on('jsdomError', (e) => console.error(e.stack, e.detail))
}

// jsdom does not implement window.scrollTo (used by the router on navigation).
window.scrollTo = (() => {}) as typeof window.scrollTo

// The planner keeps its session and language in sessionStorage; tests must not leak them into each other.
afterEach(() => {
  window.sessionStorage.clear()
})
