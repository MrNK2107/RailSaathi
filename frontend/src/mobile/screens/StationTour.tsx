// Virtual tour: "explore the station before you arrive". A schematic 3D model built from the tour payload
// (buildSceneSpec), the same route API and walking preferences as the wayfinder, and Street View through Google's
// own viewer. Lazy-loaded (App.tsx), and the 3D canvas is a further lazy chunk loaded only when WebGL exists.
// Honesty: the model is schematic and labelled so at all times; step-free labels are shown exactly as returned.
import { Component, lazy, Suspense, useEffect, useMemo, useState, type ReactNode } from 'react'
import { ApiError } from '../../api/client'
import type { ClientConfig, StationSummary, StationTour as Tour, TourPanorama } from '../../api/types'
import { RouteSummary } from '../../components/RouteSteps'
import StationBlueprintModal from '../../components/StationBlueprintModal'
import { StationMap } from '../../components/StationMap'
import { RoutePickers, RouteStatus, StationNotice } from '../../components/WayfinderParts'
import { useStationWayfinding } from '../../hooks/useStationWayfinding'
import { cameraKeyframes, overviewPose, routePanoramaStops, routeToPath, type CameraPose } from '../../tour/cameraPath'
import { hasWebGL, useReducedMotion } from '../../tour/environment'
import { placeLink } from '../../tour/mapsLinks'
import { buildSceneSpec, nearbyFacilities } from '../../tour/sceneSpec'
import StreetViewDialog from '../../tour/StreetViewDialog'
import { MapIcon } from '../icons'
import { useApp } from '../PlannerContext'
import { routeParam } from '../router'
import { AppHeader, Screen } from '../ui'

const TourScene = lazy(() => import('../../tour/TourScene'))

/** The station the tour opens on when the link names none: the one with a traced, opted-in model. */
export const DEFAULT_TOUR_STATION = 'chennai_central'
const NO_CONFIG: ClientConfig = { google_maps_browser_key: null, features: { ar_guidance_stations: [] } }

const BUTTON = 'rounded-xl bg-white px-3 py-2 text-xs font-semibold text-ink-700 ring-1 ring-ink-300 hover:bg-ink-100 disabled:opacity-50'
const SELECT = 'mt-1 w-full rounded-xl border border-ink-300 bg-white px-3 py-2 text-xs font-medium text-ink-900 focus:border-brand-600 focus:outline-none'

/** Falls back to the 2D plan if the 3D canvas throws (lost or refused WebGL context, driver errors). */
class SceneBoundary extends Component<{ onError: () => void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  componentDidCatch() {
    this.props.onError()
  }
  render() {
    return this.state.failed ? null : this.props.children
  }
}


export default function StationTour() {
  const { planner, m } = useApp()
  const client = planner.client
  const t = m.tour
  const n = m.navigation
  const [stations, setStations] = useState<StationSummary[] | null>(null)
  const [listError, setListError] = useState<ApiError | null>(null)
  const [stationId, setStationId] = useState(() => routeParam('station') ?? '')
  const [tour, setTour] = useState<Tour | null>(null)
  const [tourError, setTourError] = useState<ApiError | null>(null)
  const [config, setConfig] = useState<ClientConfig | null>(null)
  const [webgl] = useState(hasWebGL)
  const [sceneFailed, setSceneFailed] = useState(false)
  const reduced = useReducedMotion()
  const [level, setLevel] = useState<number | 'all'>('all')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [flying, setFlying] = useState(false)
  const [pose, setPose] = useState<CameraPose | null>(null)
  const [step, setStep] = useState(-1)
  const [streetView, setStreetView] = useState<{ stops: TourPanorama[]; index: number } | null>(null)
  const [blueprintOpen, setBlueprintOpen] = useState(false)

  useEffect(() => {
    const ctl = new AbortController()
    client.stations({ signal: ctl.signal }).then(
      (list) => {
        setStations(list)
        setStationId((cur) => cur || (list.find((s) => s.station_id === DEFAULT_TOUR_STATION) ?? list[0])?.station_id || '')
      },
      (e) => {
        if (e instanceof ApiError && e.isAborted) return
        setListError(e instanceof ApiError ? e : new ApiError(0, 'unknown', t.stationsFailed))
      },
    )
    client.clientConfig({ signal: ctl.signal }).then(setConfig, () => { if (!ctl.signal.aborted) setConfig(NO_CONFIG) })
    return () => ctl.abort()
    // t.stationsFailed is only a fallback message; the list is fetched once per client.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client])

  useEffect(() => {
    if (!stationId) return undefined
    const ctl = new AbortController()
    setTour(null)
    setTourError(null)
    setSelectedId(null)
    setLevel('all')
    client.stationTour(stationId, { signal: ctl.signal }).then(setTour, (e) => {
      if (e instanceof ApiError && e.isAborted) return
      setTourError(e instanceof ApiError ? e : new ApiError(0, 'unknown', t.failed))
    })
    return () => ctl.abort()
  }, [client, stationId, t.failed])

  const w = useStationWayfinding(client, stationId, stationId !== '')
  const spec = useMemo(() => (tour ? buildSceneSpec(tour) : null), [tour])
  const route = tour?.routing_enabled && w.route?.status === 'ok' ? w.route : null
  const path = useMemo(() => (route && tour && spec ? routeToPath(route, tour, spec) : null), [route, tour, spec])
  const keyframes = useMemo(() => (path ? cameraKeyframes(path, 5) : []), [path])
  const routeStops = useMemo(() => (route && tour ? routePanoramaStops(route.node_ids, tour.panoramas) : []), [route, tour])

  // A new route: stop any fly-through and frame it from above (a jump, not an animation).
  useEffect(() => {
    setFlying(false)
    setStep(-1)
    setPose(path && path.length > 1 ? overviewPose(path) : null)
  }, [path])
  useEffect(() => { if (reduced) setFlying(false) }, [reduced])

  const show3d = webgl && !sceneFailed
  const nodes = tour?.routing_enabled ? tour.nodes : []
  const selected = nodes.find((x) => x.id === selectedId) ?? null
  const panoFor = (id: string) => tour?.panoramas.find((p) => p.node_id === id) ?? null
  const apiKey = config?.google_maps_browser_key ?? null
  const markers = [
    ...(w.source ? [{ id: w.source, text: m.blueprint.start }] : []),
    ...(w.destination ? [{ id: w.destination, text: m.blueprint.destination }] : []),
  ]
  const openPano = (p: TourPanorama) => {
    const i = routeStops.findIndex((s) => s.pano_id === p.pano_id)
    setStreetView(i >= 0 ? { stops: routeStops, index: i } : { stops: [p], index: 0 })
  }
  const floorUrl = tour && tour.map.url.startsWith('/api/stations/') ? `${client.baseUrl}${tour.map.url}` : ''

  return (
    <Screen>
      <AppHeader />
      <section className="m-4 space-y-3 rounded-2xl bg-white p-4 shadow-card ring-1 ring-ink-100">
        <h1 className="text-lg font-extrabold text-brand-900">{t.title}</h1>
        <p className="text-xs text-ink-500">{t.intro}</p>
        <label htmlFor="tour-station" className="block text-xs font-semibold text-ink-700">
          {n.station}
          <select id="tour-station" value={stationId} onChange={(e) => setStationId(e.target.value)} className={SELECT}>
            {!stations?.length && stationId && <option value={stationId}>{stationId}</option>}
            {(stations ?? []).map((s) => <option key={s.station_id} value={s.station_id}>{s.station_name}</option>)}
          </select>
        </label>
        {listError && (
          <p role="alert" data-code={listError.code} className="rounded-xl bg-red-50 p-3 text-xs text-red-900">{t.stationsFailed} {listError.message}</p>
        )}
        {stations?.length === 0 && !stationId && <p role="alert" data-code="no_stations" className="rounded-xl bg-amber-50 p-3 text-xs text-amber-900">{t.noStations}</p>}
        {!stationId && !stations && !listError && <p role="status" className="text-xs text-ink-500">{t.loading}</p>}
        {stationId && !tour && !tourError && <p role="status" className="text-xs text-ink-500">{t.loading}</p>}
        {tourError && <p role="alert" data-code={tourError.code} className="rounded-xl bg-red-50 p-3 text-xs text-red-900">{t.failed} {tourError.message}</p>}
        {tour && (
          <>
            <StationNotice details={tour} m={n} />
            {w.detailsError && (
              <p role="alert" data-code={w.detailsError.code} className="rounded-xl bg-red-50 p-3 text-xs text-red-900">{t.detailsFailed} {w.detailsError.message}</p>
            )}
            {spec?.frame.units === 'plan_units' && <p className="text-xs text-ink-500">{t.planUnits}</p>}
            {tour.areas.length > 0 && <p className="text-xs text-ink-500">{t.nominalHeights}</p>}
            {!tour.routing_enabled && (
              <p role="alert" data-code="routing_unavailable" className="rounded-xl bg-amber-50 p-3 text-xs text-amber-900">{n.routingUnavailable}</p>
            )}
            {tour.routing_enabled && w.details && (
              <>
                <RoutePickers details={w.details} source={w.source} destination={w.destination} mobility={w.mobility}
                  onSource={w.setSource} onDestination={w.setDestination} onMobility={w.setMobility} idPrefix="tour" m={n} />
                <RouteStatus route={w.route} error={w.routeError} routing={w.routing} destination={w.destination} m={n} />
              </>
            )}
          </>
        )}
      </section>

      {tour && spec && (
        <section aria-label={t.title} className="space-y-3 px-4 pb-4">
          <div className="relative overflow-hidden rounded-2xl bg-ink-100 ring-1 ring-ink-100">
            <p data-testid="schematic-label" className="pointer-events-none absolute left-2 top-2 z-10 rounded-md bg-amber-100/95 px-2 py-1 text-[11px] font-bold text-amber-900">
              {t.schematicLabel}
            </p>
            {show3d ? (
              <div className="h-[360px]">
                <SceneBoundary onError={() => setSceneFailed(true)}>
                  <Suspense fallback={<p role="status" className="p-12 text-center text-xs text-ink-500">{t.sceneLoading}</p>}>
                    <TourScene spec={spec} floorUrl={floorUrl} visibleLevel={level} selectedId={selectedId} onSelect={setSelectedId}
                      markers={markers} path={path} flying={flying && !reduced} onFlyEnd={() => setFlying(false)} pose={pose}
                      label={t.sceneLabel.replace('{station}', tour.station_name)} />
                  </Suspense>
                </SceneBoundary>
              </div>
            ) : (
              <div className="space-y-2 p-2 pt-10">
                <p role="note" className="rounded-xl bg-amber-50 p-3 text-xs text-amber-900">{sceneFailed ? t.sceneFailed : t.noWebgl}</p>
                {w.details && (
                  <StationMap baseUrl={client.baseUrl} details={w.details} route={route} source={w.source} destination={w.destination}
                    label={m.blueprint.mapLabel} startLabel={m.blueprint.start} destinationLabel={m.blueprint.destination} />
                )}
                <button type="button" onClick={() => setBlueprintOpen(true)}
                  className="flex w-full items-center justify-center gap-2 rounded-xl border border-brand-200 bg-brand-50 px-4 py-2.5 text-xs font-bold text-brand-800 hover:bg-brand-100">
                  <MapIcon size={16} /> {t.openBlueprint}
                </button>
              </div>
            )}
          </div>

          {show3d && (
            <div className="flex flex-wrap items-center gap-2">
              <div role="group" aria-label={t.levels} className="flex flex-wrap gap-2">
                <button type="button" aria-pressed={level === 'all'} onClick={() => setLevel('all')} className={levelClass(level === 'all')}>{t.allLevels}</button>
                {spec.levels.map((l) => (
                  <button key={l.level} type="button" aria-pressed={level === l.level} onClick={() => setLevel(l.level)} className={levelClass(level === l.level)}>
                    {l.name ?? t.levelN.replace('{n}', String(l.level))}
                  </button>
                ))}
              </div>
              <button type="button" onClick={() => { setFlying(false); setStep(-1); setPose({ ...spec.camera }) }} className={BUTTON}>{t.resetView}</button>
            </div>
          )}

          {show3d && path && path.length > 1 && (
            <div role="group" aria-label={t.route} className="space-y-2 rounded-2xl bg-white p-3 shadow-card ring-1 ring-ink-100">
              <p className="text-xs font-bold text-brand-900">{t.route}</p>
              {reduced ? (
                <>
                  <p role="note" className="text-xs text-ink-500">{t.reducedMotion}</p>
                  <div className="flex items-center justify-between gap-2">
                    <button type="button" className={BUTTON} disabled={step <= 0}
                      onClick={() => { const i = step - 1; setStep(i); setPose(keyframes[i]) }}>{t.prevView}</button>
                    <p aria-live="polite" className="text-xs text-ink-700">
                      {step >= 0 ? t.viewOf.replace('{i}', String(step + 1)).replace('{n}', String(keyframes.length)) : ''}
                    </p>
                    <button type="button" className={BUTTON} disabled={step >= keyframes.length - 1}
                      onClick={() => { const i = step + 1; setStep(i); setPose(keyframes[i]) }}>{t.nextView}</button>
                  </div>
                </>
              ) : (
                <button type="button" onClick={() => setFlying((f) => !f)} aria-pressed={flying} className={BUTTON}>
                  {flying ? t.stop : t.play}
                </button>
              )}
              <button type="button" className={BUTTON} onClick={() => { setFlying(false); setStep(-1); setPose(overviewPose(path)) }}>{t.showRoute}</button>
              {route && <RouteSummary route={route} m={n} />}
            </div>
          )}

          {nodes.length > 0 && (
            <div className="space-y-2 rounded-2xl bg-white p-3 shadow-card ring-1 ring-ink-100">
              <label htmlFor="tour-place" className="block text-xs font-semibold text-ink-700">
                {t.place}
                <select id="tour-place" value={selectedId ?? ''} onChange={(e) => setSelectedId(e.target.value || null)} className={SELECT}>
                  <option value="">{t.choosePlace}</option>
                  {nodes.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
                </select>
              </label>
              {selected && (
                <div data-testid="place-card" aria-live="polite" className="space-y-1 text-xs">
                  <p className="text-sm font-bold text-brand-900">{selected.name}</p>
                  <p className="text-ink-500">{t.nodeType[selected.type] ?? selected.type.replace(/_/g, ' ')} · {t.status[selected.status]}</p>
                  <p className="font-semibold text-ink-700">{n.stepFree[selected.step_free]}</p>
                  <p className="pt-1 font-semibold text-ink-700">{t.facilitiesNearby}</p>
                  {(() => {
                    const near = tour ? nearbyFacilities(tour, selected.id) : []
                    return near.length > 0
                      ? <ul className="list-inside list-disc text-ink-700">{near.map((f) => <li key={f.id}>{f.name}</li>)}</ul>
                      : <p className="text-ink-500">{t.noFacilities}</p>
                  })()}
                  {panoFor(selected.id) && (
                    <button type="button" className={BUTTON} aria-label={t.seeItLabel.replace('{place}', selected.name)}
                      onClick={() => openPano(panoFor(selected.id)!)}>{t.seeIt}</button>
                  )}
                </div>
              )}
            </div>
          )}

          <StreetViewSection tour={tour} apiKey={apiKey} configLoaded={config !== null} routeStops={routeStops}
            onOpen={openPano} onWalkRoute={() => setStreetView({ stops: routeStops, index: 0 })} m={t} />
        </section>
      )}

      {tour && streetView && (
        <StreetViewDialog open onClose={() => setStreetView(null)} tour={tour} apiKey={apiKey} stops={streetView.stops}
          index={streetView.index} onIndex={(i) => setStreetView((s) => (s ? { ...s, index: i } : s))} m={t} />
      )}
      <StationBlueprintModal isOpen={blueprintOpen} onClose={() => setBlueprintOpen(false)} client={client} m={m} stationId={stationId} />
    </Screen>
  )
}

function levelClass(active: boolean): string {
  return `rounded-xl px-3 py-2 text-xs font-semibold ${active ? 'bg-brand-600 text-white' : 'bg-white text-ink-700 ring-1 ring-ink-300'}`
}

function StreetViewSection({ tour, apiKey, configLoaded, routeStops, onOpen, onWalkRoute, m }: {
  tour: Tour; apiKey: string | null; configLoaded: boolean; routeStops: TourPanorama[]
  onOpen: (p: TourPanorama) => void; onWalkRoute: () => void; m: ReturnType<typeof useApp>['m']['tour']
}) {
  const place = placeLink(tour)
  const name = (id: string) => tour.nodes.find((x) => x.id === id)?.name ?? id
  return (
    <div data-testid="street-view-section" className="space-y-2 rounded-2xl bg-white p-3 text-xs shadow-card ring-1 ring-ink-100">
      <h2 className="text-sm font-bold text-brand-900">{m.streetView}</h2>
      {configLoaded && !apiKey && <p role="note" data-code="no_maps_key" className="text-ink-700">{m.noKeyShort}</p>}
      {tour.panoramas.length === 0 ? (
        <p data-code="no_panoramas" className="text-ink-700">{m.noPanoramas}</p>
      ) : (
        <>
          <p className="font-semibold text-ink-700">{m.placesWithPanoramas}</p>
          <ul className="space-y-1">
            {tour.panoramas.map((p) => (
              <li key={p.pano_id} className="flex items-center justify-between gap-2">
                <span>{name(p.node_id)}</span>
                <button type="button" className={BUTTON} aria-label={m.seeItLabel.replace('{place}', name(p.node_id))} onClick={() => onOpen(p)}>{m.seeIt}</button>
              </li>
            ))}
          </ul>
          {routeStops.length > 0 && <button type="button" className={BUTTON} onClick={onWalkRoute}>{m.walkRoutePanos}</button>}
        </>
      )}
      <p>
        <a href={place.url} target="_blank" rel="noopener noreferrer" className="font-bold text-brand-700 underline">{m.openStationInMaps}</a>
      </p>
      <p className="text-ink-500">{place.approximate_m !== null ? m.coordsApprox.replace('{m}', String(place.approximate_m)) : m.noCoords}</p>
      <p className="text-[11px] text-ink-500">{m.streetViewNote}</p>
    </div>
  )
}
