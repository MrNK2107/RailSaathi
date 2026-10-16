// The compact wayfinder used by the blueprint modal and the virtual tour: one walking-preference select instead of
// the navigation screen's preference chips. The data layer is the shared useStationNav (station details, the
// auto-rerouting route request with its abort and stale-response guard); this only maps `mobility` to preferences.
import { useEffect, useState } from 'react'
import type { ApiClient } from '../api/client'
import type { RoutePreferencesBody } from '../api/types'
import { accessibilityPrefs, useStationNav } from '../navigation/useStationNav'

export type Mobility = 'wheelchair' | 'avoid_stairs' | 'normal'

export function mobilityPrefs(mobility: Mobility): RoutePreferencesBody {
  return accessibilityPrefs(mobility === 'wheelchair', mobility === 'avoid_stairs')
}

export function useStationWayfinding(client: ApiClient, stationId: string, enabled: boolean, initialDestination = '') {
  const [mobility, setMobility] = useState<Mobility>('normal')
  const nav = useStationNav(client, enabled ? stationId : '', {
    initialPrefs: mobilityPrefs('normal'), initialDestination, extras: false,
  })
  const { setPrefs } = nav
  useEffect(() => setPrefs(mobilityPrefs(mobility)), [mobility, setPrefs])
  return {
    details: nav.details, detailsError: nav.detailsError,
    source: nav.from, setSource: nav.setFrom, destination: nav.to, setDestination: nav.setTo,
    mobility, setMobility, route: nav.route, routeError: nav.routeError, routing: nav.routing,
  }
}
