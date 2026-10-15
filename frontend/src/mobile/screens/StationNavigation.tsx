// Station wayfinder. Everything shown comes from the navigation API: the station list, the route steps, the
// step-free labels and the schematic notice. Nothing is estimated or invented on the client.
import { useEffect, useState } from 'react'
import type { StationSummary } from '../../api/types'
import { RouteSteps, RouteSummary } from '../../components/RouteSteps'
import { StationMap } from '../../components/StationMap'
import StationBlueprintModal from '../../components/StationBlueprintModal'
import { RoutePickers, RouteStatus, StationNotice } from '../../components/WayfinderParts'
import { useStationWayfinding } from '../../hooks/useStationWayfinding'
import { formatDay, formatTime } from '../../utils/format'
import { MapIcon, StepsIcon, TrainIcon } from '../icons'
import { useApp } from '../PlannerContext'
import { AppHeader, Screen, selectedRecommendation } from '../ui'
import CoachPosition from './CoachPosition'

type View = 'map' | 'steps'

export default function StationNavigation() {
  const { planner, m } = useApp()
  const client = planner.client
  const n = m.navigation
  const [stations, setStations] = useState<StationSummary[]>([])
  const [listError, setListError] = useState<string | null>(null)
  const [stationId, setStationId] = useState('')
  const [view, setView] = useState<View>('map')
  const [blueprintOpen, setBlueprintOpen] = useState(false)

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

  const views: [View, string, typeof MapIcon][] = [['map', n.mapView, MapIcon], ['steps', n.steps, StepsIcon]]
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
            <RoutePickers details={w.details} source={w.source} destination={w.destination} mobility={w.mobility}
              onSource={w.setSource} onDestination={w.setDestination} onMobility={w.setMobility} idPrefix="nav" m={n} />
            <RouteStatus route={w.route} error={w.routeError} routing={w.routing} destination={w.destination} m={n} />
          </>
        )}
      </section>

      {/* Guidance modes: Map and Step-by-Step today. A camera (AR) mode is added here as a third tab by a later task. */}
      {w.details && (
        <>
          <div role="tablist" aria-label={n.title} className="mx-4 flex gap-2">
            {views.map(([key, label, Icon]) => (
              <button key={key} type="button" role="tab" aria-selected={view === key} onClick={() => setView(key)}
                className={`flex flex-1 items-center justify-center gap-1.5 rounded-xl py-2 text-sm font-semibold ${view === key ? 'bg-brand-600 text-white' : 'bg-white text-ink-700 ring-1 ring-ink-300'}`}>
                <Icon size={16} /> {label}
              </button>
            ))}
          </div>
          <section role="tabpanel" className="space-y-3 p-4">
            {view === 'map' ? (
              <StationMap baseUrl={client.baseUrl} details={w.details} route={route} source={w.source} destination={w.destination}
                label={m.blueprint.mapLabel} startLabel={m.blueprint.start} destinationLabel={m.blueprint.destination} />
            ) : route ? <RouteSteps route={route} m={n} /> : <p className="text-sm text-ink-500">{n.chooseHint}</p>}
            {route && <RouteSummary route={route} m={n} />}
            <button type="button" onClick={() => setBlueprintOpen(true)}
              className="flex w-full items-center justify-center gap-2 rounded-xl border border-brand-200 bg-brand-50 px-4 py-2.5 text-xs font-bold text-brand-800 hover:bg-brand-100">
              <MapIcon size={16} /> {n.openBlueprint}
            </button>
          </section>
        </>
      )}

      <CoachPosition client={client} m={n} />

      <StationBlueprintModal isOpen={blueprintOpen} onClose={() => setBlueprintOpen(false)} client={client} m={m} stationId={stationId} />
    </Screen>
  )
}
