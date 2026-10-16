// Directions from the route API, each step labelled with the step-free status the backend returned.
import type { RouteResult, StepFree } from '../api/types'
import type { MobileStrings } from '../mobile/strings'

const TONE: Record<StepFree, string> = {
  verified: 'bg-match-50 text-match-700',
  reported: 'bg-amber-50 text-amber-800',
  unknown: 'bg-ink-100 text-ink-700',
}

export function RouteSteps({ route, m }: { route: RouteResult; m: MobileStrings['navigation'] }) {
  const byEdge = new Map(route.segments.map((s) => [s.edge_id, s]))
  if (route.instructions.length === 0) return <p className="text-sm text-ink-500">{m.noSteps}</p>
  return (
    <ol className="space-y-2">
      {route.instructions.map((ins) => {
        const seg = ins.edge_id ? byEdge.get(ins.edge_id) : undefined
        return (
          <li key={ins.step} className="flex items-start gap-3 rounded-xl bg-white p-3 text-sm shadow-card ring-1 ring-ink-100">
            <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-brand-50 text-xs font-bold text-brand-700">{ins.step}</span>
            <span className="flex-1">
              <span className="block text-ink-900">{ins.text}</span>
              {ins.distance_m != null && (
                <span className="block text-xs text-ink-500">
                  {ins.distance_is_estimate ? `${m.approx} ` : ''}{Math.round(ins.distance_m)} m
                </span>
              )}
            </span>
            {seg && (
              <span data-step-free={seg.step_free} className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold ${TONE[seg.step_free]}`}>
                {m.stepFree[seg.step_free]}
              </span>
            )}
          </li>
        )
      })}
    </ol>
  )
}

/** Distance, time and the overall step-free confidence, exactly as returned (nothing is filled in). */
export function RouteSummary({ route, m }: { route: RouteResult; m: MobileStrings['navigation'] }) {
  const metres = route.distance_m ?? route.estimated_distance_m
  const estimated = route.distance_basis !== 'measured'
  return (
    <div className="space-y-1 rounded-xl bg-ink-100/60 p-3 text-xs text-ink-700">
      <p>
        <span className="font-semibold">{m.distance}:</span>{' '}
        {metres == null ? m.walkTimeUnknown : `${estimated ? `${m.approx} ` : ''}${Math.round(metres)} m`}
        {' · '}
        <span className="font-semibold">{m.walkTime}:</span>{' '}
        {route.estimated_duration_s == null ? m.walkTimeUnknown : `${m.approx} ${Math.max(1, Math.ceil(route.estimated_duration_s / 60))} min`}
      </p>
      {route.duration_assumption && <p>{route.duration_assumption}</p>}
      <p>{m.routeStepFree[route.accessibility_confidence]}</p>
    </div>
  )
}
