// Floor-plan map with an SVG overlay in image-pixel space. Draws only geometry returned by the backend (stored
// walkway polylines); it never connects points with its own straight lines. The overlay shares the image's viewBox,
// so markers and the route stay aligned at every zoom level.
import { useCallback, useEffect, useRef, useState } from 'react'
import type { Point, RouteResult, StationGraph } from '../api/types'
import { NAV_CONTROLS, NAV_PINS, type Sprite } from '../mobile/navAssets'
import { bounds } from './format'

export interface RouteMapLabels {
  map: string
  zoomIn: string
  zoomOut: string
  locate: string
  north: string
  start: string
  destination: string
  currentStep: string
  loading: string
  /** Overlay text while there is no route; null shows none (an untraced station). */
  empty: string | null
  closed: string
  closedSimulated: string
}

interface Props {
  station: StationGraph
  imageUrl: string
  route: RouteResult | null
  previousGeometry: Point[]
  closedEdges: { id: string; simulated: boolean }[]
  /** Node of the turn-by-turn step the passenger selected (not a real position fix). */
  currentNodeId: string | null
  loading: boolean
  labels: RouteMapLabels
}

export const ZOOMS = [1, 1.6, 2.4, 3.2]
const DEFAULT_ZOOM = 1
const MAP_HEIGHT = 340
const ROUTE_COLOUR = '#1a56db'

export function RouteMap({ station, imageUrl, route, previousGeometry, closedEdges, currentNodeId, loading, labels }: Props) {
  const [zoomIndex, setZoomIndex] = useState(DEFAULT_ZOOM)
  const scroller = useRef<HTMLDivElement>(null)
  const { width: W, height: H } = station.map
  const px = (p: Point) => `${p[0] * W},${p[1] * H}`
  const line = (pts: Point[]) => pts.map(px).join(' ')
  const stroke = W * 0.005
  const ok = route?.status === 'ok' ? route : null
  const node = (id: string | null | undefined) => (id ? station.nodes.find((n) => n.id === id) : undefined)
  const src = node(ok?.node_ids[0])
  const dst = node(ok?.node_ids[ok.node_ids.length - 1])
  const current = node(currentNodeId)
  const closed = closedEdges.flatMap((c) => {
    const edge = station.edges.find((e) => e.id === c.id)
    return edge && edge.geometry.length > 1 ? [{ edge, simulated: c.simulated }] : []
  })

  /** Scrolls so that normalized point (x, y) sits at the centre of the viewport. */
  const centreOn = useCallback((x: number, y: number, zoomIdx: number) => {
    const el = scroller.current
    if (!el || el.clientWidth === 0) return
    const mapWidth = el.clientWidth * ZOOMS[zoomIdx]
    const mapHeight = mapWidth * (H / W)
    el.scrollTo?.({ left: x * mapWidth - el.clientWidth / 2, top: y * mapHeight - el.clientHeight / 2 })
  }, [W, H])

  const zoomTo = (idx: number) => {
    const el = scroller.current
    const next = Math.max(0, Math.min(ZOOMS.length - 1, idx))
    if (el && el.clientWidth > 0) {
      // Keep the point at the viewport centre fixed while zooming.
      const mapWidth = el.clientWidth * ZOOMS[zoomIndex]
      const cx = (el.scrollLeft + el.clientWidth / 2) / mapWidth
      const cy = (el.scrollTop + el.clientHeight / 2) / (mapWidth * (H / W))
      setZoomIndex(next)
      requestAnimationFrame(() => centreOn(cx, cy, next))
    } else {
      setZoomIndex(next)
    }
  }

  // Fit the route into view whenever a new route arrives.
  useEffect(() => {
    const el = scroller.current
    const box = ok ? bounds(ok.geometry) : null
    if (!el || el.clientWidth === 0 || !box) return
    const pad = 0.06
    const spanX = Math.max(box.maxX - box.minX + pad * 2, 0.05)
    const spanY = Math.max(box.maxY - box.minY + pad * 2, 0.05)
    const fits = (z: number) => spanX * el.clientWidth * z <= el.clientWidth && spanY * el.clientWidth * z * (H / W) <= el.clientHeight
    let idx = ZOOMS.length - 1
    while (idx > 0 && !fits(ZOOMS[idx])) idx--
    setZoomIndex(idx)
    requestAnimationFrame(() => centreOn((box.minX + box.maxX) / 2, (box.minY + box.maxY) / 2, idx))
  }, [ok, W, H, centreOn])

  const locate = () => {
    const target = current ?? src
    centreOn(target ? target.position[0] : 0.5, target ? target.position[1] : 0.5, zoomIndex)
  }

  const pin = (p: Point, sprite: Sprite, testId: string) => {
    const h = W * 0.075
    const w = h * (sprite.width / sprite.height)
    return <image href={sprite.src} x={p[0] * W - w / 2} y={p[1] * H - h} width={w} height={h} data-testid={testId} />
  }
  const label = (p: Point, text: string, colour: string, below = false) => (
    <text x={p[0] * W} y={p[1] * H + (below ? W * 0.025 : -W * 0.08)} textAnchor="middle" fontSize={W * 0.016} fontWeight={700}
      fill={colour} stroke="white" strokeWidth={W * 0.004} paintOrder="stroke">{text}</text>
  )
  const control = (sprite: Sprite, text: string, onClick: () => void, disabled = false) => (
    <button type="button" aria-label={text} title={text} onClick={onClick} disabled={disabled}
      className="h-11 w-11 overflow-hidden rounded-xl shadow-card disabled:opacity-40">
      <img src={sprite.src} alt="" width={sprite.width} height={sprite.height} className="h-full w-full object-cover" />
    </button>
  )

  return (
    <div className="relative overflow-hidden rounded-2xl bg-ink-100 ring-1 ring-ink-100">
      <div ref={scroller} className="overflow-auto overscroll-contain" style={{ height: MAP_HEIGHT }} data-testid="station-map" data-zoom={ZOOMS[zoomIndex]}>
        <div className="relative" style={{ width: `${ZOOMS[zoomIndex] * 100}%` }}>
          <img src={imageUrl} alt="" width={W} height={H} className="block h-auto w-full" draggable={false} />
          <svg viewBox={`0 0 ${W} ${H}`} className="absolute inset-0 h-full w-full" role="img" aria-label={labels.map}>
            {previousGeometry.length > 1 && (
              <polyline points={line(previousGeometry)} fill="none" stroke="#64708a" strokeWidth={stroke}
                strokeDasharray={`${stroke} ${stroke * 2}`} strokeLinecap="round" data-testid="previous-route" />
            )}
            {closed.map(({ edge, simulated }) => {
              const mid = edge.geometry[Math.floor(edge.geometry.length / 2)]
              return (
                <g key={edge.id} data-testid="closed-edge" data-simulated={simulated}>
                  <polyline points={line(edge.geometry)} fill="none" stroke="#dc2626" strokeWidth={stroke * 1.2}
                    strokeDasharray={`${stroke * 2} ${stroke}`} />
                  <text x={mid[0] * W} y={mid[1] * H} fontSize={W * 0.02} fontWeight={800} fill="#dc2626"
                    textAnchor="middle" stroke="white" strokeWidth={W * 0.003} paintOrder="stroke">
                    ✕ {simulated ? labels.closedSimulated : labels.closed}
                  </text>
                </g>
              )
            })}
            {ok && ok.geometry.length > 1 && (
              <>
                <polyline points={line(ok.geometry)} fill="none" stroke="white" strokeWidth={stroke * 2.8} strokeLinejoin="round" strokeLinecap="round" />
                <polyline points={line(ok.geometry)} fill="none" stroke={ROUTE_COLOUR} strokeWidth={stroke * 1.7}
                  strokeLinejoin="round" strokeLinecap="round" data-testid="route-line" />
                {ok.geometry.slice(1, -1).map((p, i) => (
                  <circle key={i} cx={p[0] * W} cy={p[1] * H} r={stroke * 0.9} fill="white" stroke={ROUTE_COLOUR} strokeWidth={stroke * 0.5} />
                ))}
              </>
            )}
            {src && (
              <g data-testid="source-marker">
                {pin(src.position, NAV_PINS.start, 'source-pin')}
                {label(src.position, `${labels.start}: ${src.name}`, '#166534')}
              </g>
            )}
            {dst && (
              <g data-testid="destination-marker">
                {pin(dst.position, NAV_PINS.destination, 'destination-pin')}
                {label(dst.position, `${labels.destination}: ${dst.name}`, '#991b1b')}
              </g>
            )}
            {current && (
              <g data-testid="current-step-marker">
                <image href={NAV_PINS.navigate.src} x={current.position[0] * W - W * 0.03} y={current.position[1] * H - W * 0.03}
                  width={W * 0.06} height={W * 0.06} />
                {label(current.position, labels.currentStep, '#0f2a6b', true)}
              </g>
            )}
          </svg>
        </div>
      </div>

      <div className="pointer-events-none absolute inset-0 flex items-start justify-between p-2">
        <div className="pointer-events-auto flex flex-col gap-1.5">
          {control(NAV_CONTROLS.zoomIn, labels.zoomIn, () => zoomTo(zoomIndex + 1), zoomIndex === ZOOMS.length - 1)}
          {control(NAV_CONTROLS.zoomOut, labels.zoomOut, () => zoomTo(zoomIndex - 1), zoomIndex === 0)}
          {control(NAV_CONTROLS.locate, labels.locate, locate)}
        </div>
        <img src={NAV_CONTROLS.compass.src} alt={labels.north} title={labels.north} width={NAV_CONTROLS.compass.width}
          height={NAV_CONTROLS.compass.height} className="h-10 w-10 rounded-full shadow-card" />
      </div>

      {(loading || (!ok && labels.empty)) && (
        <p role={loading ? 'status' : undefined} className="pointer-events-none absolute inset-x-3 bottom-3 rounded-xl bg-white/95 px-3 py-2 text-center text-xs font-semibold text-brand-900 shadow-card">
          {loading ? labels.loading : labels.empty}
        </p>
      )}
    </div>
  )
}
