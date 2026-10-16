// Recovers from a lazy screen chunk that can no longer be fetched. After a deploy the old hashed chunk names are gone
// (from the server and, once the new service worker activates, from its cache), so a tab still running the old build
// fails to open a screen it has not loaded yet. Vite dispatches `vite:preloadError` for that failure; the page then
// reloads once, which fetches the new shell and its chunk names. If the chunk still fails within RETRY_WINDOW_MS
// (offline, or the server is broken) it does not reload again: the error reaches ScreenBoundary, which explains it
// and offers a Reload button.
const KEY = 'railsaathi:chunk-reload-at'
export const RETRY_WINDOW_MS = 10_000

export interface StaleChunkOptions {
  win?: Window
  now?: () => number
  reload?: () => void
}

export function installStaleChunkReload({ win = window, now = Date.now, reload = () => win.location.reload() }: StaleChunkOptions = {}): () => void {
  const onPreloadError = () => {
    let last = 0
    try {
      last = Number(win.sessionStorage.getItem(KEY)) || 0
    } catch {
      return // without storage there is no loop guard, so leave recovery to ScreenBoundary's button
    }
    if (now() - last < RETRY_WINDOW_MS) return
    try {
      win.sessionStorage.setItem(KEY, String(now()))
    } catch {
      return
    }
    reload()
  }
  win.addEventListener('vite:preloadError', onPreloadError)
  return () => win.removeEventListener('vite:preloadError', onPreloadError)
}
