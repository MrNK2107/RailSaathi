// Minimal hash router (no extra dependency). URLs look like  #/plan,  #/options.
import { useCallback, useEffect, useState } from 'react'

export const ROUTES = [
  'home', 'plan', 'options', 'navigation', 'details', 'help', 'confirmation',
  'trips', 'alerts', 'profile', 'goal', 'ticketing', 'tour',
] as const
export type Route = (typeof ROUTES)[number]

/** Unknown or retired routes (e.g. the removed  #/classic  desktop view) fall back to home. */
export function parseRoute(hash: string): Route {
  const name = hash.replace(/^#\/?/, '').split('?')[0]
  return (ROUTES as readonly string[]).includes(name) ? (name as Route) : 'home'
}

/** A query parameter of the current hash route, e.g. `station` in  #/tour?station=chennai_central. */
export function routeParam(name: string, hash: string = window.location.hash): string | null {
  const query = hash.split('?')[1]
  return query ? new URLSearchParams(query).get(name) : null
}

/** The hash for a route with query parameters, for links such as  #/tour?station=chennai_central. */
export function routeHref(route: Route, params: Record<string, string> = {}): string {
  const query = new URLSearchParams(params).toString()
  return `#/${route}${query ? `?${query}` : ''}`
}

export function useRoute(): [Route, (route: Route) => void, () => void] {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash))

  useEffect(() => {
    const onChange = () => {
      setRoute(parseRoute(window.location.hash))
      window.scrollTo({ top: 0 })
    }
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])

  const go = useCallback((next: Route) => {
    if (parseRoute(window.location.hash) === next) return
    window.location.hash = `/${next}`
  }, [])

  const back = useCallback(() => {
    if (window.history.length > 1) window.history.back()
    else window.location.hash = '/home'
  }, [])

  return [route, go, back]
}
