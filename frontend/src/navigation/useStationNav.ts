// Station-navigation state: one station's details, its active closures and the route between two of its places.
// All routing happens on the backend (POST /api/navigation/route over the traced walkway graph); this hook only
// calls the API client and holds results.
//
// The route is recalculated automatically whenever the start, destination, preferences or simulated closures change.
// Each request carries an AbortSignal and a sequence number, so a slow, superseded response never replaces a newer
// one and the map and the step list always show the route the engine last returned for the current inputs.
// Untraced stations (`routing_enabled: false`) never send a route request.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, type ApiClient } from '../api/client'
import type { Point, RoutePreferencesBody, RouteResult, StationDetails, StationDisruption, StationNode } from '../api/types'

/** Node types a passenger can pick as a start or destination (junctions and corridors are hidden). */
const SELECTABLE_TYPES = new Set(['entrance', 'platform', 'platform_access', 'ticket_counter', 'toilet',
  'information_desk', 'shop', 'other_facility', 'concourse'])

export const NO_PREFS: RoutePreferencesBody = { avoid_stairs: false, wheelchair: false, require_verified_accessibility: false }

/** null for a cancelled request (the effect was replaced), so stale results never show an error. */
function asApiError(e: unknown): ApiError | null {
  if (e instanceof ApiError) return e.isAborted ? null : e
  return new ApiError(0, 'unknown', 'Something went wrong.')
}

export interface StationNavOptions {
  initialPrefs?: RoutePreferencesBody
  /** Destination to keep when the station loads (when it is one of its nodes). */
  initialDestination?: string
  /** Also load the station's info (layout note) and active closures. Off for the compact blueprint / tour views. */
  extras?: boolean
}

export function useStationNav(client: ApiClient, stationId: string, options: StationNavOptions = {}) {
  const { initialPrefs = NO_PREFS, initialDestination = '', extras = true } = options
  const [details, setDetails] = useState<StationDetails | null>(null)
  const [detailsError, setDetailsError] = useState<ApiError | null>(null)
  const [layoutNote, setLayoutNote] = useState<string | null>(null)
  const [disruptions, setDisruptions] = useState<StationDisruption[]>([])
  const [disruptionsError, setDisruptionsError] = useState<ApiError | null>(null)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState(initialDestination)
  const [prefs, setPrefs] = useState<RoutePreferencesBody>(initialPrefs)
  const [route, setRoute] = useState<RouteResult | null>(null)
  const [routeError, setRouteError] = useState<ApiError | null>(null)
  const [routing, setRouting] = useState(false)
  // What-if closures sent with each route request (`simulate_closures`); nothing is stored on the server.
  const [simulated, setSimulated] = useState<string[]>([])
  const [previousGeometry, setPreviousGeometry] = useState<Point[]>([])
  // Index of the instruction the passenger has stepped to (manual turn-by-turn), or null when not navigating.
  const [navStep, setNavStep] = useState<number | null>(null)
  const requestSeq = useRef(0)
  // Edge ids of the route shown before a closure, sent once with the reroute so the response can explain it.
  const previousEdgeIds = useRef<string[]>([])

  useEffect(() => {
    setDetails(null); setDetailsError(null); setLayoutNote(null); setDisruptions([]); setDisruptionsError(null)
    setFrom(''); setRoute(null); setRouteError(null); setSimulated([]); setPreviousGeometry([]); setNavStep(null)
    previousEdgeIds.current = []
    if (!stationId) return undefined
    const ctl = new AbortController()
    client.station(stationId, { signal: ctl.signal }).then(
      (d) => {
        setDetails(d)
        const entrance = d.station.nodes.find((n) => n.type === 'entrance')
        setFrom(entrance?.id ?? '')
        setTo((cur) => (d.station.nodes.some((n) => n.id === cur) ? cur : ''))
        if (!extras) return
        // The layout note only refines the schematic notice; without it the generic text is shown.
        Promise.resolve().then(() => client.stationInfo(stationId, { signal: ctl.signal })).then(
          (info) => setLayoutNote(info?.layout_note ?? null), () => setLayoutNote(null))
        if (d.routing_enabled) {
          Promise.resolve().then(() => client.disruptions(stationId, { signal: ctl.signal })).then(
            setDisruptions,
            (e) => { const err = asApiError(e); if (err) setDisruptionsError(err) },
          )
        }
      },
      (e) => setDetailsError(asApiError(e)),
    )
    return () => ctl.abort()
  }, [client, stationId, extras])

  const routable = !!details && details.routing_enabled && details.station.station_id === stationId
  useEffect(() => {
    if (!routable || !from || !to || from === to) {
      requestSeq.current += 1 // drops any response still in flight
      setRoute(null); setRouteError(null); setRouting(false); setNavStep(null)
      return undefined
    }
    const ctl = new AbortController()
    const seq = ++requestSeq.current
    const previous = previousEdgeIds.current // sent until a response for it arrives
    setRouting(true)
    setRouteError(null)
    client.stationRoute({
      station_id: stationId, source: from, destination: to, preferences: prefs, apply_disruptions: true,
      ...(previous.length > 0 ? { previous_edge_ids: previous } : {}),
      ...(simulated.length > 0 ? { simulate_closures: simulated } : {}),
    }, { signal: ctl.signal }).then(
      (r) => {
        if (seq !== requestSeq.current) return
        if (previousEdgeIds.current === previous) previousEdgeIds.current = []
        setRoute(r); setNavStep(null); setRouting(false)
      },
      (e) => {
        const err = asApiError(e)
        if (!err || seq !== requestSeq.current) return
        setRoute(null); setRouteError(err); setRouting(false)
      },
    )
    return () => ctl.abort()
  }, [client, stationId, routable, from, to, prefs, simulated])

  const nodes = details?.station.nodes
  const places = useMemo<StationNode[]>(() => (nodes ?? []).filter((n) => SELECTABLE_TYPES.has(n.type)), [nodes])
  const nodeName = useCallback((id: string) => nodes?.find((n) => n.id === id)?.name ?? id, [nodes])
  const sameEndpoints = Boolean(from && to && from === to)

  const swap = useCallback(() => {
    if (!to) return
    setFrom(to)
    setTo(from)
  }, [from, to])

  /** Close one pathway of the shown route (simulated, this request only) and reroute around it. */
  const closePathway = useCallback((edgeId: string) => {
    if (!route || route.status !== 'ok' || simulated.includes(edgeId)) return
    previousEdgeIds.current = route.edge_ids
    setPreviousGeometry(route.geometry)
    setSimulated((cur) => [...cur, edgeId])
  }, [route, simulated])

  const reopenAll = useCallback(() => {
    previousEdgeIds.current = []
    setPreviousGeometry([])
    setSimulated([])
  }, [])

  // Manual turn-by-turn: the passenger advances the instructions in order. There is no indoor positioning source,
  // so the "current position" is the node of the selected step, not a real fix.
  const stepCount = route?.status === 'ok' ? route.instructions.length : 0
  const startNavigation = useCallback(() => { if (stepCount > 0) setNavStep(0) }, [stepCount])
  const nextStep = useCallback(() => setNavStep((s) => (s === null ? null : Math.min(stepCount - 1, s + 1))), [stepCount])
  const prevStep = useCallback(() => setNavStep((s) => (s === null ? null : Math.max(0, s - 1))), [])
  const exitNavigation = useCallback(() => setNavStep(null), [])
  const currentNodeId = navStep !== null && route?.status === 'ok' ? route.instructions[navStep]?.node_id ?? null : null

  return {
    details, detailsError, layoutNote, disruptions, disruptionsError, places, nodeName,
    from, setFrom, to, setTo, swap, sameEndpoints, prefs, setPrefs,
    route, routeError, routing, simulated, previousGeometry, closePathway, reopenAll,
    navStep, stepCount, currentNodeId, startNavigation, nextStep, prevStep, exitNavigation,
  }
}

export type StationNav = ReturnType<typeof useStationNav>
