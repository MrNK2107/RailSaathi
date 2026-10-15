import '@testing-library/jest-dom/vitest'

// jsdom does not implement window.scrollTo (used by the router on navigation).
window.scrollTo = (() => {}) as typeof window.scrollTo

// The planner keeps its session and language in sessionStorage; tests must not leak them into each other.
afterEach(() => {
  window.sessionStorage.clear()
})
