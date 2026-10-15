// Station wayfinder. Everything shown comes from the navigation API: the station list, the route steps, the
// step-free labels and the schematic notice. Nothing is estimated or invented on the client.
// The camera (AR) tab is offered only for a traced station that client-config lists for AR, in a secure context with
// a camera; its code (camera, motion, WebXR) is a lazy chunk under src/ar/. Leaving AR always lands on the steps.
import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import type { StationSummary } from '../../api/types'
import type { FallbackReason } from '../../ar/machine'
import { ScreenBoundary } from '../../components/ScreenBoundary'
import { RouteSteps, RouteSummary } from '../../components/RouteSteps'
import { StationMap } from '../../components/StationMap'
import StationBlueprintModal from '../../components/StationBlueprintModal'
import { RoutePickers, RouteStatus, StationNotice } from '../../components/WayfinderParts'
import { useStationWayfinding } from '../../hooks/useStationWayfinding'
import { formatDay, formatTime } from '../../utils/format'
import { CameraIcon, CompassIcon, MapIcon, StepsIcon, TrainIcon } from '../icons'
import { useApp } from '../PlannerContext'
import { routeHref } from '../router'
import { AppHeader, Screen, selectedRecommendation } from '../ui'
import CoachPosition from './CoachPosition'

const ArGuidance = lazy(() => import('../../ar/ArGuidance'))

type View = 'map' | 'steps' | 'ar'

export default function StationNavigation() {
  const { planner, m } = useApp()
  const client = planner.client
  const n = m.navigation
  const [stations, setStations] = useState<StationSummary[]>([])
  const [listError, setListError] = useState<string | null>(null)
  const [stationId, setStationId] = useState('')
  const [view, setView] = useState<View>('map')
  const [blueprintOpen, setBlueprintOpen] = useState(false)
  const [arStations, setArStations] = useState<string[]>([])
  const [arCapable, setArCapable] = useState(false)
  const [arExit, setArExit] = useState<FallbackReason | null>(null)

  // Per-station AR flag. A failure only means no AR tab; the wayfinder works without it.
  useEffect(() => {
    const ctl = new AbortController()
    Promise.resolve().then(() => client.clientConfig({ signal: ctl.signal })).then(
      (cfg) => setArStations(cfg?.features?.ar_guidance_stations ?? []),
      () => setArStations([]),
    )
    return () => ctl.abort()
  }, [client])

  useEffect(() => {
    const ctl = new AbortController()
    client.stations({ signal: ctl.signal }).then(
      (list) => { setStations(list); setStationId((cur) => cur || list[0]?.station_id || '') },
      (e) => { if (!ctl.signal.aborted) setListError(e instanceof Error ? e.message : n.stationFailed) },
    )
    return () => ctl.abort()
  }, [client, n.stationFailed])

  const w = useStationWayfinding(client, stationId, stationId !== '')
  const rec = selectedRecommendation(planner.state)
  const leg = rec?.option.legs[0]
  const route = w.route?.status === 'ok' ? w.route : null

  const arStation = !!w.details?.routing_enabled && arStations.includes(stationId)
  // Secure context and a camera; checked (without prompting) only for an AR station, from the lazy AR chunk.
  useEffect(() => {
    if (!arStation) return undefined
    let live = true
    import('../../ar/device').then((d) => d.checkArSupport()).then(
      (r) => { if (live) setArCapable(r.ok) },
      () => { if (live) setArCapable(false) },
    )
    return () => { live = false }
  }, [arStation])
  const arOffered = arStation && arCapable
  useEffect(() => {
    if (!arOffered && view === 'ar') setView('steps')
  }, [arOffered, view])
  const leaveAr = useCallback((reason: FallbackReason | null) => {
    setArExit(reason)
    setView('steps')
  }, [])

  const views: [View, string, typeof MapIcon][] = [['map', n.mapView, MapIcon], ['steps', n.steps, StepsIcon],
    ...(arOffered ? [['ar', m.ar.tab, CameraIcon] as [View, string, typeof MapIcon]] : [])]
  return (
    <Screen>
      <AppHeader />

      <section className="m-4 flex items-start gap-3 rounded-2xl bg-white p-4 shadow-card ring-1 ring-ink-100">
        <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand-50 text-brand-600"><TrainIcon size={22} /></span>
        {leg ? (
          <div className="text-sm">
            <p className="font-bold text-brand-900">{leg.train_no} {leg.train_name}</p>
            <p className="text-ink-500">{n.platform}: — · {formatTime(leg.departure)} ({formatDay(leg.departure)})</p>
          </div>
        ) : <p className="text-sm text-ink-500">{n.noTrain}</p>}
      </section>

      <section className="mx-4 mb-3 space-y-3 rounded-2xl bg-white p-4 shadow-card ring-1 ring-ink-100">
        {listError && <p role="alert" className="text-xs text-red-900">{n.stationFailed} {listError}</p>}
        <label htmlFor="nav-station" className="block text-xs font-semibold text-ink-700">
          {n.station}
          <select id="nav-station" value={stationId} onChange={(e) => setStationId(e.target.value)}
            className="mt-1 w-full rounded-xl border border-ink-300 bg-white px-3 py-2 text-xs font-medium text-ink-900 focus:border-brand-600 focus:outline-none">
            {stations.map((s) => <option key={s.station_id} value={s.station_id}>{s.station_name}</option>)}
          </select>
        </label>
        {stationId && !w.details && !w.detailsError && <p role="status" className="text-xs text-ink-500">{n.loading}</p>}
        {w.detailsError && <p role="alert" className="text-xs text-red-900">{n.stationFailed} {w.detailsError.message}</p>}
        {w.details && (
          <>
            <StationNotice details={w.details} m={n} />
            {!w.details.routing_enabled && (
              <p role="alert" data-code="routing_unavailable" className="rounded-xl bg-amber-50 p-3 text-xs text-amber-900">{n.routingUnavailable}</p>
            )}
            {w.details.routing_enabled && <RoutePickers details={w.details} source={w.source} destination={w.destination} mobility={w.mobility}
              onSource={w.setSource} onDestination={w.setDestination} onMobility={w.setMobility} idPrefix="nav" m={n} />}
            {w.details.routing_enabled && <RouteStatus route={w.route} error={w.routeError} routing={w.routing} destination={w.destination} m={n} />}
          </>
        )}
      </section>

      {/* Guidance modes: Map, Step-by-Step and, where offered, Camera (AR). */}
      {w.details && (
        <>
          <div role="tablist" aria-label={n.title} className="mx-4 flex gap-2">
            {views.map(([key, label, Icon]) => (
              <button key={key} type="button" role="tab" aria-selected={view === key} onClick={() => { setView(key); if (key === 'ar') setArExit(null) }}
                className={`flex flex-1 items-center justify-center gap-1.5 rounded-xl py-2 text-sm font-semibold ${view === key ? 'bg-brand-600 text-white' : 'bg-white text-ink-700 ring-1 ring-ink-300'}`}>
                <Icon size={16} /> {label}
              </button>
            ))}
          </div>
          <section role="tabpanel" className="space-y-3 p-4">
            {view === 'ar' ? (
              <ScreenBoundary message={m.ar.loadFailed} reloadLabel={m.errors.reload}>
                <Suspense fallback={<p role="status" className="text-sm text-ink-500">{m.ar.loading}</p>}>
                  <ArGuidance client={client} stationId={stationId} details={w.details} route={route} m={m.ar} onExit={leaveAr} />
                </Suspense>
              </ScreenBoundary>
            ) : view === 'map' ? (
              <StationMap baseUrl={client.baseUrl} details={w.details} route={route} source={w.source} destination={w.destination}
                label={m.blueprint.mapLabel} startLabel={m.blueprint.start} destinationLabel={m.blueprint.destination} />
            ) : (
              <>
                {arExit && (
                  <div role="status" data-code={`ar_${arExit}`} className="flex items-start gap-2 rounded-xl bg-amber-50 p-3 text-xs text-amber-900">
                    <p className="flex-1">{m.ar.fallback[arExit]}</p>
                    <button type="button" onClick={() => setArExit(null)} className="font-semibold underline">{m.ar.dismiss}</button>
                  </div>
                )}
                {route ? <RouteSteps route={route} m={n} /> : <p className="text-sm text-ink-500">{w.details.routing_enabled ? n.chooseHint : n.routingUnavailable}</p>}
              </>
            )}
            {route && <RouteSummary route={route} m={n} />}
            <button type="button" onClick={() => setBlueprintOpen(true)}
              className="flex w-full items-center justify-center gap-2 rounded-xl border border-brand-200 bg-brand-50 px-4 py-2.5 text-xs font-bold text-brand-800 hover:bg-brand-100">
              <MapIcon size={16} /> {n.openBlueprint}
            </button>
            <a href={routeHref('tour', { station: stationId })}
              className="flex w-full items-center justify-center gap-2 rounded-xl border border-brand-200 bg-white px-4 py-2.5 text-xs font-bold text-brand-800 hover:bg-brand-50">
              <CompassIcon size={16} /> {n.openTour}
            </a>
          </section>
        </>
      )}

      <CoachPosition client={client} m={n} />

      <StationBlueprintModal isOpen={blueprintOpen} onClose={() => setBlueprintOpen(false)} client={client} m={m} stationId={stationId} />
    </Screen>
  )
}
