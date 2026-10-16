// Active closures from GET /api/disruptions/{station_id}: the pathways and facilities the route already avoids.
// A failed lookup (503 `disruptions_unavailable`) says so explicitly instead of implying there are none.
import type { ApiError } from '../../../api/client'
import type { StationDetails, StationDisruption } from '../../../api/types'
import { useApp } from '../../PlannerContext'

interface Props {
  details: StationDetails
  disruptions: StationDisruption[]
  error: ApiError | null
  nodeName: (id: string) => string
}

export function ActiveClosures({ details, disruptions, error, nodeName }: Props) {
  const { m } = useApp()
  const n = m.navigation
  if (error) {
    return <p role="status" data-code={error.code} className="rounded-xl bg-amber-50 p-3 text-xs text-amber-900">{n.closuresUnavailable}</p>
  }
  if (disruptions.length === 0) return null
  const target = (d: StationDisruption) => {
    if (d.target_type === 'node') return nodeName(d.target_id)
    const edge = details.station.edges.find((e) => e.id === d.target_id)
    return edge ? `${nodeName(edge.from)} → ${nodeName(edge.to)}` : d.target_id
  }
  return (
    <section aria-labelledby="nav-closures" className="rounded-2xl bg-red-50 p-3 text-xs text-red-900">
      <h2 id="nav-closures" className="text-sm font-bold">{n.activeClosures}</h2>
      <ul className="mt-1 space-y-1">
        {disruptions.map((d) => (
          <li key={d.id}>
            <span className="font-semibold">{d.simulated ? n.closedSimulated : n.closed}:</span> {target(d)} — {d.reason}
          </li>
        ))}
      </ul>
    </section>
  )
}
