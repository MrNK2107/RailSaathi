// Loads one station and its route for the chosen entrance, destination and walking preference.
import { useEffect, useState } from 'react'
import { ApiError, type ApiClient } from '../api/client'
import type { RouteResult, StationDetails } from '../api/types'

export type Mobility = 'wheelchair' | 'avoid_stairs' | 'normal'

/** null for a cancelled request (the effect was replaced), so stale results never show an error. */
function asApiError(e: unknown): ApiError | null {
  if (e instanceof ApiError) return e.isAborted ? null : e
  return new ApiError(0, 'unknown', 'Something went wrong.')
}

export function useStationWayfinding(client: ApiClient, stationId: string, enabled: boolean, initialDestination = '') {
  const [details, setDetails] = useState<StationDetails | null>(null)
  const [detailsError, setDetailsError] = useState<ApiError | null>(null)
  const [source, setSource] = useState('')
  const [destination, setDestination] = useState(initialDestination)
  const [mobility, setMobility] = useState<Mobility>('normal')
  const [route, setRoute] = useState<RouteResult | null>(null)
  const [routeError, setRouteError] = useState<ApiError | null>(null)
  const [routing, setRouting] = useState(false)

  useEffect(() => {
    if (!enabled || !stationId) return undefined
    const ctl = new AbortController()
    setDetails(null)
    setDetailsError(null)
    setSource('')
    setRoute(null)
    setRouteError(null)
    client.station(stationId, { signal: ctl.signal }).then(
      (d) => {
        setDetails(d)
        const entrance = d.station.nodes.find((n) => n.type === 'entrance')
        setSource(entrance?.id ?? '')
        setDestination((cur) => (d.station.nodes.some((n) => n.id === cur) ? cur : ''))
      },
      (e) => setDetailsError(asApiError(e)),
    )
    return () => ctl.abort()
  }, [client, stationId, enabled])

  useEffect(() => {
    if (!enabled || !details || !details.routing_enabled || !source || !destination) {
      setRoute(null)
      setRouteError(null)
      setRouting(false)
      return undefined
    }
    const ctl = new AbortController()
    setRouting(true)
    setRouteError(null)
    client.stationRoute({
      station_id: stationId,
      source,
      destination,
      preferences: {
        wheelchair: mobility === 'wheelchair',
        avoid_stairs: mobility !== 'normal',
        require_verified_accessibility: mobility === 'wheelchair',
      },
      apply_disruptions: true,
    }, { signal: ctl.signal }).then(
      (r) => { setRoute(r); setRouting(false) },
      (e) => {
        const err = asApiError(e)
        if (err) { setRoute(null); setRouteError(err); setRouting(false) }
      },
    )
    return () => ctl.abort()
  }, [client, stationId, enabled, details, source, destination, mobility])

  return {
    details, detailsError, source, setSource, destination, setDestination, mobility, setMobility,
    route, routeError, routing,
  }
}
