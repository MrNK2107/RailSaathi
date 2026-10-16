// Walking time, distance and route status for the route the engine returned. Every figure comes from the backend;
// estimates are labelled as such, and the step-free confidence and warnings are shown as returned.
import type { RoutePreferencesBody, RouteResult } from '../../../api/types'
import { formatMetres, formatMinutes, routeDistance } from '../../../navigation/format'
import { NAV_SUMMARY_ICONS, type Sprite } from '../../navAssets'
import { useApp } from '../../PlannerContext'

interface Props {
  route: RouteResult
  prefs: RoutePreferencesBody
  nodeName: (id: string) => string
}

function Tile({ icon, label, value, hint }: { icon: Sprite; label: string; value: string; hint?: string }) {
  return (
    <div className="flex min-w-0 flex-col items-center rounded-xl bg-brand-50/60 px-1 py-2 text-center">
      <img src={icon.src} alt="" width={icon.width} height={icon.height} className="h-9 w-9" />
      <span className="mt-1 text-sm font-bold leading-tight text-brand-900">{value}</span>
      <span className="text-[10px] font-medium text-ink-500">{label}{hint ? ` (${hint})` : ''}</span>
    </div>
  )
}

export function RouteSummary({ route, prefs, nodeName }: Props) {
  const { m } = useApp()
  const n = m.navigation
  const distance = routeDistance(route)
  const minutes = formatMinutes(route.estimated_duration_s)
  const isEstimate = route.distance_basis === 'estimated_from_map_scale'
  const anyPref = prefs.avoid_stairs || prefs.wheelchair || prefs.require_verified_accessibility
  const blocked = route.previous_route_blocked === true
  // The "previous route blocked" warning is shown once as a friendly notice (the raw one lists edge ids).
  const warnings = route.warnings.filter((w) => !(blocked && /previous route is blocked/i.test(w)))
  const first = route.node_ids[0]
  const last = route.node_ids[route.node_ids.length - 1]
  return (
    <section className="rounded-2xl bg-white p-3 shadow-card ring-1 ring-ink-100" aria-label={n.summary}>
      {blocked && <p className="mb-2 rounded-lg bg-red-50 px-2 py-1 text-xs font-semibold text-red-800">{n.previousBlocked}</p>}
      <div className="grid grid-cols-3 gap-2">
        <Tile icon={NAV_SUMMARY_ICONS.walkTime} label={n.walkTime} hint={isEstimate && minutes !== null ? n.estimate : undefined}
          value={minutes !== null ? `${minutes} ${n.min}` : n.noDistance} />
        <Tile icon={NAV_SUMMARY_ICONS.walk} label={n.distance} hint={isEstimate && distance !== null ? n.estimate : undefined}
          value={distance !== null ? formatMetres(distance)! : n.noDistance} />
        <Tile icon={NAV_SUMMARY_ICONS.route} label={n.routeStatus} value={anyPref ? n.shortestPrefs : n.shortest} />
      </div>
      {first && last && <p className="mt-2 text-xs text-ink-700">{nodeName(first)} → {nodeName(last)}</p>}
      {route.duration_assumption && <p className="text-[11px] text-ink-500">{route.duration_assumption}</p>}
      <p className="mt-1 text-xs font-medium text-ink-700" data-confidence={route.accessibility_confidence}>
        {n.routeStepFree[route.accessibility_confidence]}
      </p>
      {warnings.length > 0 && (
        <ul className="mt-2 space-y-1">
          {warnings.map((w) => <li key={w} className="rounded-lg bg-amber-50 px-2 py-1 text-xs text-amber-900"><span aria-hidden="true">⚠ </span>{w}</li>)}
        </ul>
      )}
    </section>
  )
}
