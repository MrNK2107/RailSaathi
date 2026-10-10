import '@testing-library/jest-dom/vitest'

// jsdom does not implement window.scrollTo (used by the router on navigation).
window.scrollTo = (() => {}) as typeof window.scrollTo
