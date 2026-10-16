// Registers the app-shell service worker (dist/sw.js, built from sw/sw.js) in production builds only: in dev it would
// cache Vite's unhashed modules. Needs a secure context (https, or http on localhost); anywhere else the app simply
// runs without it. Registration waits for the load event so it never competes with the first screen for bandwidth.
export interface RegisterOptions {
  production?: boolean
  win?: Window
}

export function registerServiceWorker({ production = import.meta.env.PROD, win = window }: RegisterOptions = {}): void {
  if (!production || !('serviceWorker' in win.navigator) || !win.isSecureContext) return
  const register = () => {
    win.navigator.serviceWorker.register('/sw.js').catch(() => {
      // The offline shell is an enhancement; a failed registration must not affect the app.
    })
  }
  if (win.document.readyState === 'complete') register()
  else win.addEventListener('load', register, { once: true })
}
