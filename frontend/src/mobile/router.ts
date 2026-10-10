// Minimal hash router (no extra dependency). URLs look like  #/plan,  #/options.
import { useCallback, useEffect, useState } from 'react'

export const ROUTES = [
  'home', 'plan', 'options', 'navigation', 'details', 'help', 'confirmation',
  'trips', 'alerts', 'profile', 'classic',
] as const
export type Route = (typeof ROUTES)[number]

export function parseRoute(hash: string): Route {
  const name = hash.replace(/^#\/?/, '').split('?')[0]
  return (ROUTES as readonly string[]).includes(name) ? (name as Route) : 'home'
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
