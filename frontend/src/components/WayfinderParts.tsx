// Pieces shared by the station screen and the blueprint modal: the schematic notice, the route pickers and the
// route status (loading, routing_unavailable, no route, warnings).
import type { ApiError } from '../api/client'
import type { RouteResult, StationDetails } from '../api/types'
import type { Mobility } from '../hooks/useStationWayfinding'
import type { MobileStrings } from '../mobile/strings'
import { ProvenanceBadge } from './ProvenanceBadge'

type Nav = MobileStrings['navigation']

const SELECT = 'mt-1 w-full rounded-xl border border-ink-300 bg-white px-3 py-2 text-xs font-medium text-ink-900 focus:border-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-600/30'

/** The schematic notice (when the layout is not surveyed) and the provenance badge. */
export function StationNotice({ details, note, m }: {
  details: Pick<StationDetails, 'layout_basis' | 'provenance'>; note?: string | null; m: Nav
}) {
  const schematic = details.layout_basis === 'schematic'
  return (
    <div className="space-y-2">
      {schematic && (
        <p role="note" className="rounded-xl bg-amber-50 p-3 text-xs text-amber-900">
          <span className="font-bold">{m.schematicTitle}. </span>{note || m.schematicFallback}
        </p>
      )}
      <ProvenanceBadge provenance={details.provenance} variant="full" />
    </div>
  )
}

export interface PickerProps {
  details: StationDetails
  source: string
  destination: string
  mobility: Mobility
  onSource: (id: string) => void
  onDestination: (id: string) => void
  onMobility: (m: Mobility) => void
  idPrefix: string
  m: Nav
}

export const FACILITY_TYPES = ['toilet', 'ticket_counter', 'information_desk', 'shop']

export function RoutePickers({ details, source, destination, mobility, onSource, onDestination, onMobility, idPrefix, m }: PickerProps) {
  const nodes = details.station.nodes
  const entrances = nodes.filter((n) => n.type === 'entrance')
  const platforms = nodes.filter((n) => n.type === 'platform')
  const facilities = nodes.filter((n) => FACILITY_TYPES.includes(n.type))
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <label htmlFor={`${idPrefix}-from`} className="block text-xs font-semibold text-ink-700">
          {m.from}
          <select id={`${idPrefix}-from`} value={source} onChange={(e) => onSource(e.target.value)} className={SELECT}>
            {entrances.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
          </select>
        </label>
        <label htmlFor={`${idPrefix}-to`} className="block text-xs font-semibold text-ink-700">
          {m.to}
          <select id={`${idPrefix}-to`} value={destination} onChange={(e) => onDestination(e.target.value)} className={SELECT}>
            <option value="">{m.choose}</option>
            <optgroup label={m.platforms}>
              {platforms.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
            </optgroup>
            {facilities.length > 0 && (
              <optgroup label={m.facilities}>
                {facilities.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
              </optgroup>
            )}
          </select>
        </label>
      </div>
      <label htmlFor={`${idPrefix}-mobility`} className="block text-xs font-semibold text-ink-700">
        {m.mobility}
        <select id={`${idPrefix}-mobility`} value={mobility} onChange={(e) => onMobility(e.target.value as Mobility)} className={SELECT}>
          <option value="wheelchair">{m.mobilityWheelchair}</option>
          <option value="avoid_stairs">{m.mobilityAvoidStairs}</option>
          <option value="normal">{m.mobilityNormal}</option>
        </select>
      </label>
    </div>
  )
}

/** Loading, refusal and warnings for a route request. Renders nothing when there is a usable route. */
export function RouteStatus({ route, error, routing, destination, m }: {
  route: RouteResult | null; error: ApiError | null; routing: boolean; destination: string; m: Nav
}) {
  if (!destination) return <p className="text-xs text-ink-500">{m.chooseHint}</p>
  if (routing) return <p role="status" className="text-xs text-ink-500">{m.routing}</p>
  if (error) {
    return (
      <p role="alert" data-code={error.code} className="rounded-xl bg-amber-50 p-3 text-xs text-amber-900">
        {error.code === 'routing_unavailable' ? error.message : `${m.routeFailed} ${error.message}`}
      </p>
    )
  }
  if (route?.status === 'no_route') {
    return (
      <div role="alert" className="rounded-xl bg-red-50 p-3 text-xs text-red-900">
        <p className="font-bold">{m.noRoute}</p>
        <p>{route.explanation || route.reason}</p>
      </div>
    )
  }
  if (route && route.warnings.length > 0) {
    return (
      <ul className="space-y-1 rounded-xl bg-amber-50 p-3 text-xs text-amber-900">
        {route.warnings.map((w) => <li key={w}>{w}</li>)}
      </ul>
    )
  }
  return null
}
