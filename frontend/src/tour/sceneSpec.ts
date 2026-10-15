// Pure, WebGL-free description of the virtual-tour scene, built from GET /api/stations/{id}/tour.
// The renderer (TourScene.tsx) only turns this into meshes; every position, height and label comes from here,
// so the geometry is unit-tested without a canvas.
//
// World frame (three.js, y up): the plan lies on the x/z plane, centred on the origin. Plan x (right) is world +x,
// plan y (down the plan) is world +z, so plan-up is world -z. Units are metres when the station has a map scale;
// otherwise "plan units" (the plan width is PLAN_UNITS_WIDTH), and the screen says so.
import { FACILITY_TYPES } from '../components/WayfinderParts'
import type { AreaKind, Point, StepFree, StationTour, TourNode } from '../api/types'

export type Vec3 = [number, number, number]
/** A point on the floor plane: [world x, world z]. */
export type Vec2 = [number, number]

/** Floors without a stated elevation are stacked this far apart (metres or plan units). */
export const DEFAULT_LEVEL_GAP = 6
/** Plan width used when the station has no map scale. */
export const PLAN_UNITS_WIDTH = 100
/** Pins float this far above their level so they clear platforms (nominal 0.84 m) and concourse slabs. */
export const PIN_HEIGHT = 3
/** Pathways and the route are drawn this far above their level, above the platform slabs. */
export const PATH_LIFT = 1

export interface SceneFrame {
  units: 'metres' | 'plan_units'
  /** Plan extent along world x and z. */
  width: number
  depth: number
}

export interface SceneLevel {
  level: number
  /** As returned; null when the station lists no levels (derived from node levels). */
  name: string | null
  y: number
  /** false when the height is the default stacking gap, not a stated elevation. */
  elevationKnown: boolean
}

export interface SceneArea {
  id: string
  kind: AreaKind
  name: string | null
  level: number
  /** Base of the extrusion (the level's y) and its height, both as returned (heights are nominal). */
  y: number
  height: number
  /** Open ring (closing point dropped) on the floor plane. */
  outline: Vec2[]
  color: string
  opacity: number
}

export interface ScenePin {
  id: string
  name: string
  type: string
  level: number
  position: Vec3
  stepFree: StepFree
  status: TourNode['status']
  isFacility: boolean
  hasPanorama: boolean
}

export interface SceneEdge {
  id: string
  level: number
  points: Vec3[]
  pathType: string
  stepFree: StepFree
}

export interface SceneFloor {
  /** Backend-relative URL of the plan image (map.png), laid on this level as the floor texture. */
  url: string
  level: number
  y: number
  width: number
  depth: number
}

export interface SceneSpec {
  stationId: string
  frame: SceneFrame
  /** Pins and pathways are drawn only for traced layouts (routing enabled), as on the 2D map. */
  traced: boolean
  levels: SceneLevel[]
  floor: SceneFloor
  areas: SceneArea[]
  pins: ScenePin[]
  edges: SceneEdge[]
  /** Half the plan diagonal: used to place the default camera and its far plane. */
  radius: number
  camera: { position: Vec3; target: Vec3 }
}

const AREA_STYLE: Record<AreaKind, { color: string; opacity: number }> = {
  building_footprint: { color: '#94a3b8', opacity: 0.12 },
  concourse: { color: '#c7d2fe', opacity: 0.85 },
  platform: { color: '#e2e8f0', opacity: 0.95 },
  track_bed: { color: '#78716c', opacity: 0.9 },
}

const round = (v: number) => Math.round(v * 1000) / 1000

export function sceneFrame(tour: StationTour): SceneFrame {
  if (tour.scale) return { units: 'metres', width: tour.scale.width_m, depth: tour.scale.height_m }
  const aspect = tour.map.height_px / tour.map.width_px
  return { units: 'plan_units', width: PLAN_UNITS_WIDTH, depth: round(PLAN_UNITS_WIDTH * aspect) }
}

/**
 * Plan point to the floor plane. Uses the backend's metres when present (they are normalised × image size ×
 * metres per pixel), otherwise the normalised point scaled to the frame.
 */
export function toFloor(frame: SceneFrame, normalised: Point, metres?: Point | null): Vec2 {
  const x = metres && frame.units === 'metres' ? metres[0] : normalised[0] * frame.width
  const z = metres && frame.units === 'metres' ? metres[1] : normalised[1] * frame.depth
  return [round(x - frame.width / 2), round(z - frame.depth / 2)]
}

/** Levels in ascending order with their heights. Stated elevations win; others stack by DEFAULT_LEVEL_GAP. */
export function sceneLevels(tour: StationTour): SceneLevel[] {
  const listed = new Map(tour.levels.map((l) => [l.level, l]))
  const numbers = new Set<number>([...listed.keys(), ...tour.nodes.map((n) => n.level), ...tour.areas.map((a) => a.level)])
  if (numbers.size === 0) numbers.add(0)
  return [...numbers].sort((a, b) => a - b).map((level) => {
    const l = listed.get(level)
    const known = l?.elevation_m !== null && l?.elevation_m !== undefined
    return { level, name: l?.name ?? null, y: known ? l!.elevation_m! : level * DEFAULT_LEVEL_GAP, elevationKnown: known }
  })
}

export function levelY(levels: SceneLevel[], level: number): number {
  return levels.find((l) => l.level === level)?.y ?? level * DEFAULT_LEVEL_GAP
}

/** Drops the closing point of a closed ring. */
function openRing(points: Vec2[]): Vec2[] {
  if (points.length > 1) {
    const [a, b] = [points[0], points[points.length - 1]]
    if (a[0] === b[0] && a[1] === b[1]) return points.slice(0, -1)
  }
  return points
}

/**
 * Lays a floor polyline into 3D, its height going linearly (by length) from y0 at the first point to y1 at the
 * last. Used for pathways and the route, so a stair between levels climbs along its own geometry.
 */
export function liftPolyline(points: Vec2[], y0: number, y1: number): Vec3[] {
  const lengths = [0]
  for (let i = 1; i < points.length; i += 1) {
    lengths.push(lengths[i - 1] + Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]))
  }
  const total = lengths[lengths.length - 1]
  return points.map((p, i) => {
    const f = total > 0 ? lengths[i] / total : points.length > 1 ? i / (points.length - 1) : 0
    return [p[0], round(y0 + (y1 - y0) * f), p[1]]
  })
}

export function buildSceneSpec(tour: StationTour): SceneSpec {
  const frame = sceneFrame(tour)
  const levels = sceneLevels(tour)
  const traced = tour.routing_enabled
  const panoNodes = new Set(tour.panoramas.map((p) => p.node_id))
  const nodeLevel = new Map(tour.nodes.map((n) => [n.id, n.level]))
  const baseLevel = levels.some((l) => l.level === 0) ? 0 : levels[0].level

  const areas: SceneArea[] = tour.areas.map((a) => ({
    id: a.id, kind: a.kind, name: a.name, level: a.level, y: levelY(levels, a.level), height: a.height_m,
    outline: openRing(a.polygon.map((p, i) => toFloor(frame, p, a.polygon_m?.[i]))),
    ...AREA_STYLE[a.kind],
  }))

  const pins: ScenePin[] = traced ? tour.nodes.map((n) => {
    const [x, z] = toFloor(frame, n.position, n.position_m)
    return {
      id: n.id, name: n.name, type: n.type, level: n.level, position: [x, round(levelY(levels, n.level) + PIN_HEIGHT), z],
      stepFree: n.step_free, status: n.status, isFacility: FACILITY_TYPES.includes(n.type), hasPanorama: panoNodes.has(n.id),
    }
  }) : []

  const edges: SceneEdge[] = traced ? tour.edges.map((e) => {
    const from = nodeLevel.get(e.from) ?? baseLevel
    const to = nodeLevel.get(e.to) ?? from
    const floor = e.geometry.map((p, i) => toFloor(frame, p, e.geometry_m?.[i]))
    return {
      id: e.id, level: from, pathType: e.path_type, stepFree: e.step_free,
      points: liftPolyline(floor, levelY(levels, from) + PATH_LIFT, levelY(levels, to) + PATH_LIFT),
    }
  }) : []

  const radius = round(Math.hypot(frame.width, frame.depth) / 2)
  return {
    stationId: tour.station_id, frame, traced, levels, areas, pins, edges, radius,
    floor: { url: tour.map.url, level: baseLevel, y: levelY(levels, baseLevel), width: frame.width, depth: frame.depth },
    camera: { position: [0, round(radius * 0.7), round(radius * 0.6)], target: [0, 0, 0] },
  }
}

/** Facilities (toilets, ticket counters, information desks, shops) within `hops` pathways of a node, nearest first. */
export function nearbyFacilities(tour: StationTour, nodeId: string, hops = 2): TourNode[] {
  const neighbours = new Map<string, string[]>()
  const link = (a: string, b: string) => neighbours.set(a, [...(neighbours.get(a) ?? []), b])
  for (const e of tour.edges) {
    link(e.from, e.to)
    link(e.to, e.from) // proximity, not walking direction
  }
  const byId = new Map(tour.nodes.map((n) => [n.id, n]))
  const seen = new Set([nodeId])
  const out: TourNode[] = []
  let frontier = [nodeId]
  for (let d = 0; d < hops; d += 1) {
    const next: string[] = []
    for (const id of frontier) {
      for (const nb of neighbours.get(id) ?? []) {
        if (seen.has(nb)) continue
        seen.add(nb)
        next.push(nb)
        const node = byId.get(nb)
        if (node && FACILITY_TYPES.includes(node.type)) out.push(node)
      }
    }
    frontier = next
  }
  return out
}
