// Station navigation over the backend's indoor routing (POST /api/navigation/route on the traced walkway graph).
// Routes, instructions, distances and closures all come from the API; the map and the step list render the same
// route object, so the two views never disagree. Untraced stations (`routing_enabled: false`) show the plan and the
// routing-unavailable notice only: no pickers and no route requests.
// The camera (AR) tab is offered only for a traced station that client-config lists for AR, in a secure context with
// a camera; its code (camera, motion, WebXR) is a lazy chunk under src/ar/. Leaving AR always lands on the steps.
import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import type { RoutePreferencesBody, StationSummary } from '../../api/types'
import type { FallbackReason } from '../../ar/machine'
import { ScreenBoundary } from '../../components/ScreenBoundary'
import StationBlueprintModal from '../../components/StationBlueprintModal'
import { StationNotice } from '../../components/WayfinderParts'
import { RouteMap } from '../../navigation/RouteMap'
import { NO_PREFS, useStationNav } from '../../navigation/useStationNav'
import { formatDay, formatTime } from '../../utils/format'
import { AlertIcon, ArrowRight, CameraIcon, CompassIcon, HomeIcon, InfoIcon, MapIcon, StepsIcon, TrainIcon } from '../icons'
import { useApp } from '../PlannerContext'
import { routeHref } from '../router'
import { fill } from '../strings'
import { AppHeader, PrimaryButton, Screen, SecondaryButton, selectedRecommendation } from '../ui'
import CoachPosition from './CoachPosition'
import { ActiveClosures } from './navigation/ActiveClosures'
import { ClosureSimulator } from './navigation/ClosureSimulator'
import { EndpointPicker } from './navigation/EndpointPicker'
import { NavBanner } from './navigation/NavBanner'
import { PreferenceChips, preferenceLabels, type PrefKey } from './navigation/PreferenceChips'
import { RouteSummary } from './navigation/RouteSummary'
import { StepList } from './navigation/StepList'

const ArGuidance = lazy(() => import('../../ar/ArGuidance'))

type View = 'map' | 'steps' | 'ar'

export default function StationNavigation() {
  const { planner, go, m } = useApp()
  const client = planner.client
  const n = m.navigation
  const [stations, setStations] = useState<StationSummary[]>([])
  const [listError, setListError] = useState<string | null>(null)
  const [picked, setPicked] = useState<string | null>(null)
  const [view, setView] = useState<View>('map')
  const [blueprintOpen, setBlueprintOpen] = useState(false)
  const [arStations, setArStations] = useState<string[]>([])
  const [canSimulate, setCanSimulate] = useState(false)
  const [arCapable, setArCapable] = useState(false)
  const [arExit, setArExit] = useState<{ reason: FallbackReason; message: string | null } | null>(null)

  // Feature flags. A failure only means no AR tab and no closure simulator; navigation works without them.
  useEffect(() => {
    const ctl = new AbortController()
    Promise.resolve().then(() => client.clientConfig({ signal: ctl.signal })).then(
      (cfg) => { setArStations(cfg?.features?.ar_guidance_stations ?? []); setCanSimulate(cfg?.features?.simulate_closures === true) },
      () => { setArStations([]); setCanSimulate(false) },
    )
    return () => ctl.abort()
  }, [client])

  useEffect(() => {
    const ctl = new AbortController()
    client.stations({ signal: ctl.signal }).then(
      setStations,
      (e) => { if (!ctl.signal.aborted) setListError(e instanceof Error ? e.message : n.stationFailed) },
    )
    return () => ctl.abort()
  }, [client, n.stationFailed])

  const rec = selectedRecommendation(planner.state)
  const legs = rec?.option.legs
  const leg = legs?.[0]
  // The journey's boarding (else final) station, looked up by railway code in the catalogue. Without a journey the
  // first catalogue station is shown; with a journey whose stations have no floor plan, none is preselected.
  const codesKey = legs ? [legs[0].from_code, legs[legs.length - 1].to_code].join(',').toUpperCase() : ''
  const journeyStation = useMemo(() => {
    for (const code of codesKey.split(',').filter(Boolean)) {
      const hit = stations.find((s) => s.station_code?.toUpperCase() === code)
      if (hit) return hit
    }
    return null
  }, [stations, codesKey])
  const stationId = picked ?? journeyStation?.station_id ?? (leg ? '' : stations[0]?.station_id ?? '')

  const needs = planner.state?.journey.passenger_needs ?? []
  // Keyed on the needs' contents: `needs` is a new [] each render while no session is loaded.
  const needsKey = [...needs].sort().join(',')
  const needPrefs = useMemo<RoutePreferencesBody>(() => {
    const has = (need: string) => needsKey.split(',').includes(need)
    return { ...NO_PREFS, wheelchair: has('wheelchair'), avoid_stairs: has('wheelchair') || has('reduced_walking') }
  }, [needsKey])
  const nav = useStationNav(client, stationId, { initialPrefs: needPrefs })
  // Apply the planner's passenger needs when they arrive (the session may load after this screen), but never
  // override toggles the passenger has changed here.
  const [prefsTouched, setPrefsTouched] = useState(false)
  const { setPrefs } = nav
  useEffect(() => {
    if (!prefsTouched) setPrefs(needPrefs)
  }, [needPrefs, prefsTouched, setPrefs])
  const togglePref = (key: PrefKey) => {
    setPrefsTouched(true)
    setPrefs({ ...nav.prefs, [key]: !nav.prefs[key] })
  }
  const activePrefs = preferenceLabels(n).filter(([key]) => nav.prefs[key])

  const details = nav.details
  const routed = !!details?.routing_enabled
  const route = nav.route
  const ok = route?.status === 'ok' ? route : null
  const navigating = nav.navStep !== null && ok !== null
  const currentInstruction = navigating ? ok.instructions[nav.navStep!] : null
  const lastStep = navigating && nav.navStep === nav.stepCount - 1

  const arStation = routed && arStations.includes(stationId)
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
  const leaveAr = useCallback((reason: FallbackReason | null, message: string | null) => {
    setArExit(reason ? { reason, message } : null)
    setView('steps')
  }, [])

  const closedEdges = [
    ...nav.disruptions.filter((d) => d.target_type === 'edge').map((d) => ({ id: d.target_id, simulated: d.simulated })),
    ...nav.simulated.map((id) => ({ id, simulated: true })),
  ]
  const stationName = details?.station.station_name ?? stations.find((s) => s.station_id === stationId)?.station_name ?? null
  const views: [View, string, typeof MapIcon][] = [['map', n.mapView, MapIcon], ['steps', n.steps, StepsIcon],
    ...(arOffered ? [['ar', m.ar.tab, CameraIcon] as [View, string, typeof MapIcon]] : [])]

  const footer = routed ? (
    navigating ? (
      <div className="flex gap-2">
        <div className="w-2/5"><SecondaryButton onClick={nav.exitNavigation}>{n.exitNav}</SecondaryButton></div>
        <div className="min-w-0 flex-1">
          <PrimaryButton onClick={lastStep ? nav.exitNavigation : nav.nextStep}>
            {lastStep ? n.finish : n.nextStep} <ArrowRight size={20} />
          </PrimaryButton>
        </div>
      </div>
    ) : ok ? (
      <PrimaryButton onClick={() => { nav.startNavigation(); setView('map') }}>{n.startNav} <ArrowRight size={20} /></PrimaryButton>
    ) : (
      <PrimaryButton disabled>{nav.routing ? n.calculating : n.chooseDestination}</PrimaryButton>
    )
  ) : undefined

  return (
    <Screen footer={footer} header={(
      <AppHeader right={(
        <button type="button" onClick={() => go('home')} aria-label={n.home} title={n.home} className="grid h-11 w-11 place-items-center rounded-full text-brand-900 hover:bg-ink-100">
          <HomeIcon size={22} />
        </button>
      )} />
    )}>

      <NavBanner stationId={stationId} stationName={stationName} />

      <section className="mx-4 mt-3 flex items-start gap-3 rounded-2xl bg-white p-3 shadow-card ring-1 ring-ink-100">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand-50 text-brand-600"><TrainIcon size={22} /></span>
        {leg ? (
          <div className="min-w-0 text-sm">
            <p className="font-bold text-brand-900">{leg.train_no} {leg.train_name}</p>
            <p className="text-ink-500">{n.platformUnknown}</p>
            <p className="text-ink-500">{n.departs} {formatTime(leg.departure)} ({formatDay(leg.departure)}) · {leg.from_name}</p>
          </div>
        ) : <p className="text-sm text-ink-500">{n.noTrain}</p>}
      </section>

      <section className="mx-4 mt-3 space-y-3 rounded-2xl bg-white p-3 shadow-card ring-1 ring-ink-100">
        {listError && <p role="alert" className="text-xs text-red-900">{n.stationFailed} {listError}</p>}
        {leg && !journeyStation && !picked && stations.length > 0 && (
          <p className="rounded-xl bg-ink-100 p-3 text-xs text-ink-700">{fill(n.noPlanForJourney, { station: leg.from_name })}</p>
        )}
        <div>
          <label htmlFor="nav-station" className="block text-xs font-semibold text-ink-700">{n.station}</label>
          <select id="nav-station" value={stationId} onChange={(e) => setPicked(e.target.value)}
            className="mt-1 min-h-[44px] w-full rounded-xl border border-ink-300 bg-white px-3 py-2 text-sm font-medium text-ink-900 focus:border-brand-600 focus:outline-none">
            {!stationId && <option value="">{n.chooseStation}</option>}
            {stations.map((s) => <option key={s.station_id} value={s.station_id}>{s.station_name}</option>)}
          </select>
        </div>
        {stationId && !details && !nav.detailsError && <p role="status" className="text-xs text-ink-500">{n.loading}</p>}
        {nav.detailsError && <p role="alert" className="text-xs text-red-900">{n.stationFailed} {nav.detailsError.message}</p>}
        {/* The station's own layout note is English-only data; Tamil shows the translated generic notice. */}
        {details && <StationNotice details={details} note={planner.language === 'en' ? nav.layoutNote : null} m={n} />}
        {details && !routed && (
          <p role="alert" data-code="routing_unavailable" className="rounded-xl bg-amber-50 p-3 text-xs text-amber-900">{n.routingUnavailable}</p>
        )}
      </section>

      {details && (
        <div className="space-y-3 px-4 pb-4 pt-3">
          {routed && (
            <>
              <EndpointPicker places={nav.places} from={nav.from} to={nav.to} sameEndpoints={nav.sameEndpoints}
                onFrom={nav.setFrom} onTo={nav.setTo} onSwap={nav.swap} />
              <PreferenceChips prefs={nav.prefs} onToggle={togglePref} />
            </>
          )}

          {nav.routeError && (
            <p role="alert" data-code={nav.routeError.code} className="flex items-start gap-2 rounded-xl bg-red-50 p-3 text-sm text-red-800">
              <AlertIcon size={18} className="mt-0.5 shrink-0" />
              {nav.routeError.code === 'routing_unavailable' ? nav.routeError.message : `${n.routeFailed} ${nav.routeError.message}`}
            </p>
          )}

          {/* Guidance modes: Map, Step-by-Step and, where offered, Camera (AR). */}
          <div role="tablist" aria-label={n.title} className={`grid gap-2 ${views.length === 3 ? 'grid-cols-3' : 'grid-cols-2'}`}>
            {views.map(([key, text, Icon]) => (
              <button key={key} type="button" role="tab" aria-selected={view === key}
                onClick={() => { setView(key); if (key === 'ar') setArExit(null) }}
                className={`flex min-h-[44px] min-w-0 items-center justify-center gap-1.5 rounded-full px-2 py-2 text-sm font-bold ring-2 ${view === key ? 'bg-brand-600 text-white ring-brand-600' : 'bg-white text-brand-700 ring-brand-600'}`}>
                <Icon size={18} /> <span className="truncate">{text}</span>
              </button>
            ))}
          </div>

          <section role="tabpanel" aria-label={views.find(([key]) => key === view)?.[1]} className="space-y-3">
            {view === 'ar' ? (
              <ScreenBoundary message={m.ar.loadFailed} reloadLabel={m.errors.reload}>
                <Suspense fallback={<p role="status" className="text-sm text-ink-500">{m.ar.loading}</p>}>
                  <ArGuidance client={client} stationId={stationId} details={details} route={ok} m={m.ar} onExit={leaveAr} />
                </Suspense>
              </ScreenBoundary>
            ) : view === 'map' ? (
              <RouteMap station={details.station} imageUrl={`${client.baseUrl}/api/stations/${encodeURIComponent(details.station.station_id)}/map`}
                route={routed ? route : null} previousGeometry={nav.previousGeometry} closedEdges={closedEdges}
                currentNodeId={nav.currentNodeId} loading={nav.routing}
                labels={{
                  map: ok ? fill(n.mapRouteLabel, { from: nav.nodeName(ok.node_ids[0]), to: nav.nodeName(ok.node_ids[ok.node_ids.length - 1]) })
                    : fill(n.mapLabel, { station: details.station.station_name }),
                  zoomIn: n.zoomIn, zoomOut: n.zoomOut, locate: n.locate, north: n.north,
                  start: m.blueprint.start, destination: m.blueprint.destination, currentStep: n.selectedStep, loading: n.calculating,
                  empty: !routed ? null : nav.sameEndpoints ? n.sameEndpoints : n.emptyMap,
                  closed: n.closed, closedSimulated: n.closedSimulated, scroll: n.mapScroll,
                }} />
            ) : (
              <>
                {arExit && (
                  <div role="status" data-code={`ar_${arExit.reason}`} className="flex items-start gap-2 rounded-xl bg-amber-50 p-3 text-xs text-amber-900">
                    <p className="flex-1">{m.ar.fallback[arExit.reason]}{arExit.reason === 'rejected' && arExit.message ? ` (${arExit.message})` : ''}</p>
                    <button type="button" onClick={() => setArExit(null)} className="font-semibold underline">{m.ar.dismiss}</button>
                  </div>
                )}
                <StepList route={ok} activeStep={nav.navStep}
                  emptyText={!routed ? n.routingUnavailable : nav.routing ? n.calculating : ok ? n.noSteps : n.emptySteps} />
              </>
            )}
          </section>

          {currentInstruction && (
            <section role="status" aria-live="polite" className="rounded-2xl bg-brand-50 p-3 ring-2 ring-brand-500" data-testid="current-step">
              <p className="text-[11px] font-bold uppercase tracking-wide text-brand-700">
                {fill(n.stepOf, { n: nav.navStep! + 1, total: nav.stepCount })}
              </p>
              <p className="mt-1 text-sm font-semibold text-ink-900">{currentInstruction.text}</p>
              <div className="mt-2 flex items-center justify-between gap-2">
                <button type="button" onClick={nav.prevStep} disabled={nav.navStep === 0}
                  className="min-h-[44px] shrink-0 text-xs font-semibold text-brand-700 underline disabled:opacity-40">{n.prevStep}</button>
                <p className="flex items-start gap-1 text-[11px] text-ink-500"><InfoIcon size={14} className="mt-0.5 shrink-0" /> {n.positionNote}</p>
              </div>
            </section>
          )}

          {ok && <RouteSummary route={ok} prefs={nav.prefs} nodeName={nav.nodeName} />}

          {route?.status === 'no_route' && (
            <section role="alert" className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-900">
              <h2 className="font-bold">{n.noRoute}</h2>
              <p className="mt-1">{route.explanation || route.reason}</p>
              {route.reason === 'accessibility_constraints' && activePrefs.length > 0 && (
                <div className="mt-3">
                  <p className="text-xs font-semibold">{n.relaxHint}</p>
                  <div className="mt-1 flex flex-wrap gap-2">
                    {activePrefs.map(([key, text]) => (
                      <button key={key} type="button" onClick={() => togglePref(key)} aria-label={fill(n.relaxOff, { pref: text })}
                        className="min-h-[44px] rounded-full bg-white px-3 py-1 text-xs font-semibold text-red-900 ring-1 ring-red-300">
                        <span aria-hidden="true">✕ </span>{text}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </section>
          )}

          {ok && ok.along_the_way.length > 0 && (
            <section aria-labelledby="nav-along" className="rounded-2xl bg-white p-4 shadow-card ring-1 ring-ink-100">
              <h2 id="nav-along" className="text-sm font-bold text-brand-900">{n.alongWay}</h2>
              <ul className="mt-2 space-y-1.5">
                {ok.along_the_way.map((a) => (
                  <li key={a.node_id} className="flex items-center gap-2 text-sm">
                    <span className="min-w-0 flex-1 text-ink-900">{a.name}
                      {a.distance_from_route_m != null && !a.on_route && (
                        <span className="text-xs text-ink-500"> · {fill(n.offRoute, { metres: Math.round(a.distance_from_route_m) })}</span>
                      )}
                    </span>
                    {a.node_id !== nav.to && (
                      <button type="button" onClick={() => nav.setTo(a.node_id)}
                        className="min-h-[44px] shrink-0 rounded-full bg-brand-50 px-3 text-xs font-semibold text-brand-700">{n.goHere}</button>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {routed && <ActiveClosures details={details} disruptions={nav.disruptions} error={nav.disruptionsError} nodeName={nav.nodeName} />}

          {routed && (
            <p className="flex items-start gap-2 rounded-xl bg-amber-50 p-3 text-xs text-amber-900">
              <InfoIcon size={16} className="mt-0.5 shrink-0" /> {n.unverified}
            </p>
          )}

          {routed && canSimulate && (ok || nav.simulated.length > 0) && (
            <ClosureSimulator route={ok} simulated={nav.simulated} busy={nav.routing} nodeName={nav.nodeName}
              onClose={nav.closePathway} onReopenAll={nav.reopenAll} />
          )}

          <button type="button" onClick={() => setBlueprintOpen(true)}
            className="flex min-h-[44px] w-full items-center justify-center gap-2 rounded-xl border border-brand-200 bg-brand-50 px-4 py-2.5 text-xs font-bold text-brand-800 hover:bg-brand-100">
            <MapIcon size={16} /> {n.openBlueprint}
          </button>
          <a href={routeHref('tour', { station: stationId })}
            className="flex min-h-[44px] w-full items-center justify-center gap-2 rounded-xl border border-brand-200 bg-white px-4 py-2.5 text-xs font-bold text-brand-800 hover:bg-brand-50">
            <CompassIcon size={16} /> {n.openTour}
          </a>
        </div>
      )}

      <CoachPosition client={client} m={n} />

      <StationBlueprintModal isOpen={blueprintOpen} onClose={() => setBlueprintOpen(false)} client={client} m={m} stationId={stationId} />
    </Screen>
  )
}
