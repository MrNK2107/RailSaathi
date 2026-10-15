// Station plan image with the route drawn over it. Positions are normalised image coordinates.
import type { Point, RouteResult, StationDetails } from '../api/types'

export interface StationMapProps {
  baseUrl: string
  details: StationDetails
  route: RouteResult | null
  source: string
  destination: string
  label: string
  startLabel: string
  destinationLabel: string
}

export function StationMap({ baseUrl, details, route, source, destination, label, startLabel, destinationLabel }: StationMapProps) {
  const { station } = details
  const w = station.map.width
  const h = station.map.height
  const px = (p: Point): [number, number] => [p[0] * w, p[1] * h]
  const path = (pts: Point[]) => pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${px(p)[0].toFixed(1)} ${px(p)[1].toFixed(1)}`).join(' ')
  // Pathways and markers are drawn only for traced layouts; an untraced schematic shows the plan image alone.
  const traced = details.routing_enabled
  const marker = (id: string, text: string, fill: string) => {
    const node = station.nodes.find((n) => n.id === id)
    if (!node) return null
    const [cx, cy] = px(node.position)
    return (
      <g key={id} transform={`translate(${cx}, ${cy})`}>
        <circle r={12} fill={fill} stroke="#fff" strokeWidth={2} />
        <text y={-18} textAnchor="middle" fontSize={22} fontWeight={800} fill="#0b1f4d" stroke="#fff" strokeWidth={4} paintOrder="stroke">
          {text}: {node.name}
        </text>
      </g>
    )
  }
  return (
    <svg role="img" aria-label={label} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="xMidYMid meet"
      className="h-auto w-full rounded-xl bg-ink-100 ring-1 ring-ink-100">
      <image href={`${baseUrl}/api/stations/${encodeURIComponent(station.station_id)}/map`} width={w} height={h} />
      {traced && station.edges.map((e) => (
        <path key={e.id} d={path(e.geometry)} fill="none" stroke="rgba(11,31,77,0.25)" strokeWidth={2}
          strokeDasharray={e.path_type === 'stairs' ? '4 4' : undefined} />
      ))}
      {traced && route?.status === 'ok' && route.geometry.length > 1 && (
        <path d={path(route.geometry)} fill="none" stroke="#1a56db" strokeWidth={8} strokeLinecap="round" strokeLinejoin="round" />
      )}
      {traced && source && marker(source, startLabel, '#10b981')}
      {traced && destination && marker(destination, destinationLabel, '#f59e0b')}
    </svg>
  )
}
