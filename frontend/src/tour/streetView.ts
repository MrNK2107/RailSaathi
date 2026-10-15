// Loads the Maps JavaScript API's Street View library once, with the public browser key from /api/client-config.
// Street View imagery is only ever shown in Google's own StreetViewPanorama; it is never read into our 3D model
// (Google Maps Platform terms).
import { importLibrary, setOptions } from '@googlemaps/js-api-loader'

let loaded: { key: string; lib: Promise<google.maps.StreetViewLibrary> } | null = null
const authListeners = new Set<() => void>()

declare global {
  interface Window {
    /** Called by the Maps JavaScript API when the key is rejected (wrong referrer, API not enabled, billing). */
    gm_authFailure?: () => void
  }
}

/**
 * The Street View library. The API can be configured only once per page, so a second key is refused rather than
 * silently ignored. A failed load stays failed for the page's lifetime (the tour then links out to Google Maps).
 */
export function loadStreetView(key: string): Promise<google.maps.StreetViewLibrary> {
  if (loaded) {
    return loaded.key === key ? loaded.lib : Promise.reject(new Error('The Maps API is already configured with another key.'))
  }
  window.gm_authFailure = () => authListeners.forEach((fn) => fn())
  setOptions({ key, v: 'weekly' })
  loaded = { key, lib: importLibrary('streetView') }
  return loaded.lib
}

/** Subscribes to key rejections reported by the Maps API after it loaded. Returns the unsubscribe function. */
export function onMapsAuthFailure(fn: () => void): () => void {
  authListeners.add(fn)
  return () => { authListeners.delete(fn) }
}

/** Tests only: forget the loaded library and listeners. */
export function resetStreetViewLoaderForTests(): void {
  loaded = null
  authListeners.clear()
  delete window.gm_authFailure
}
