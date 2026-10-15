// Station blueprint: the plan image with the route from the navigation API drawn on it, directions and facilities
// along the way. Every number and label comes from the API response; nothing is filled in when it is missing.
import { useState } from 'react'
import type { ApiClient } from '../api/client'
import { useStationWayfinding } from '../hooks/useStationWayfinding'
import { CloseIcon } from '../mobile/icons'
import type { MobileStrings } from '../mobile/strings'
import { Modal } from './Modal'
import { RouteSteps, RouteSummary } from './RouteSteps'
import { StationMap } from './StationMap'
import { RoutePickers, RouteStatus, StationNotice } from './WayfinderParts'

export interface StationBlueprintModalProps {
  isOpen: boolean
  onClose: () => void
  client: ApiClient
  m: MobileStrings
  stationId: string
  /** Node id of the platform to preselect, if the caller knows it. */
  initialDestination?: string
}

type Tab = 'map' | 'steps' | 'along'
const TITLE_ID = 'blueprint-title'

export default function StationBlueprintModal({ isOpen, onClose, client, m, stationId, initialDestination }: StationBlueprintModalProps) {
  const w = useStationWayfinding(client, stationId, isOpen, initialDestination)
  const [tab, setTab] = useState<Tab>('map')
  const b = m.blueprint
  const tabs: [Tab, string][] = [['map', b.mapTab], ['steps', b.stepsTab], ['along', b.alongTab]]
  const route = w.route?.status === 'ok' ? w.route : null

  return (
    <Modal open={isOpen} onClose={onClose} titleId={TITLE_ID} className="h-[92vh]">
      <header className="flex items-start justify-between gap-2 border-b border-ink-100 p-4">
        <h2 id={TITLE_ID} className="text-base font-bold text-brand-900">
          {b.title}{w.details ? ` — ${w.details.station.station_name}` : ''}
        </h2>
        <button type="button" onClick={onClose} aria-label={b.close} className="rounded-full p-1.5 text-ink-700 hover:bg-ink-100">
          <CloseIcon size={20} />
        </button>
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {w.detailsError && <p role="alert" className="rounded-xl bg-red-50 p-3 text-xs text-red-900">{m.navigation.stationFailed} {w.detailsError.message}</p>}
        {!w.details && !w.detailsError && <p role="status" className="text-sm text-ink-500">{m.navigation.loading}</p>}
        {w.details && (
          <>
            <StationNotice details={w.details} m={m.navigation} />
            {!w.details.routing_enabled && (
              <p role="alert" data-code="routing_unavailable" className="rounded-xl bg-amber-50 p-3 text-xs text-amber-900">{m.navigation.routingUnavailable}</p>
            )}
            {w.details.routing_enabled && <RoutePickers details={w.details} source={w.source} destination={w.destination} mobility={w.mobility}
              onSource={w.setSource} onDestination={w.setDestination} onMobility={w.setMobility} idPrefix="blueprint" m={m.navigation} />}
            {w.details.routing_enabled && <RouteStatus route={w.route} error={w.routeError} routing={w.routing} destination={w.destination} m={m.navigation} />}

            <div role="tablist" aria-label={b.tabs} className="flex gap-1 border-b border-ink-100">
              {tabs.map(([key, label]) => (
                <button key={key} type="button" role="tab" id={`blueprint-tab-${key}`} aria-selected={tab === key}
                  aria-controls={`blueprint-panel-${key}`} onClick={() => setTab(key)}
                  className={`flex-1 border-b-2 px-2 py-2 text-xs font-semibold ${tab === key ? 'border-brand-600 text-brand-700' : 'border-transparent text-ink-500'}`}>
                  {label}
                </button>
              ))}
            </div>

            <div role="tabpanel" id={`blueprint-panel-${tab}`} aria-labelledby={`blueprint-tab-${tab}`} className="space-y-3">
              {tab === 'map' && (
                <>
                  <StationMap baseUrl={client.baseUrl} details={w.details} route={route} source={w.source} destination={w.destination}
                    label={b.mapLabel} startLabel={b.start} destinationLabel={b.destination} />
                  {route && <RouteSummary route={route} m={m.navigation} />}
                </>
              )}
              {tab === 'steps' && (route ? <RouteSteps route={route} m={m.navigation} /> : <p className="text-sm text-ink-500">{w.details.routing_enabled ? m.navigation.chooseHint : m.navigation.routingUnavailable}</p>)}
              {tab === 'along' && (
                route && route.along_the_way.length > 0 ? (
                  <ul className="space-y-2">
                    {route.along_the_way.map((it) => (
                      <li key={it.node_id} className="flex items-center justify-between rounded-xl bg-white p-3 text-sm shadow-card ring-1 ring-ink-100">
                        <span>{it.name}</span>
                        <span className="text-[11px] font-semibold text-ink-500">{it.on_route ? b.onRoute : b.nearby}</span>
                      </li>
                    ))}
                  </ul>
                ) : <p className="text-sm text-ink-500">{b.noAlong}</p>
              )}
            </div>
          </>
        )}
      </div>
    </Modal>
  )
}
