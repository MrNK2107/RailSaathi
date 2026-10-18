// Pure, WebGL-free description of the OpenStreetMap world around a station (the `world` block of the tour payload),
// in the three.js frame of the tour: x = east, z = -north, metres from the osm.json origin, y up.
//
// Frames (ruling R4): osm.json points are [east, north]; metadata world_alignment maps plan metres (x, -y), y down
// the plan, to (east, north). Only the default (proper) transform is ever applied, never the recorded mirrored
// alternative (ruling R12). Only the station complex is drawn (ruling R13): no underground subways, no `station`
// polygons (one is a bus terminus), buildings near the station only, and rails clipped to the complex.
import type { Point, TourWorld, TourWorldAlignment, TourWorldFeature } from '../api/types'
import type { CameraPose } from './cameraPath'
import type { Vec2, Vec3 } from './sceneSpec'

/** Verbatim OpenStreetMap credit, shown by the screen whenever the world is drawn. */
export const OSM_ATTRIBUTION = '© OpenStreetMap contributors'
export const STOREY_HEIGHT_M = 3.2
export const DEFAULT_BUILDING_HEIGHT_M = 9
export const PLATFORM_HEIGHT_M = 0.84
export const ROOF_Y_M = 6.5
export const ROOF_THICKNESS_M = 0.3
export const HERITAGE_HEIGHT_M = 41
/** The heritage footprint is extruded this high when the model cannot be loaded. */
export const HERITAGE_FALLBACK_HEIGHT_M = 18
/** Features with a point this close to the origin make up the station complex; its bounds never reach further. */
export const COMPLEX_REACH_M = 250
/** Camera pitch above the horizon when framing the complex from the south. */
export const FRAME_PITCH_DEG = 55
/** Margin around the heritage building and the traced graph in the opening frame (rulings R15, R17). */
export const FOCUS_MARGIN_M = 18
/** Platform labels show only when the camera is this close to its target (the route's destination island always shows). */
export const LABEL_DISTANCE_M = 150
/** Heights the framing keeps in view above the ground (the heritage roofline is lower than this). */
const FRAME_TOP_M = 20

export interface WorldBounds { minX: number; maxX: number; minZ: number; maxZ: number }
export interface WorldBuilding { outline: Vec2[]; height: number }
export interface WorldPlatform { outline: Vec2[]; label: string | null; labelSource: 'osm' | 'station_plan' | null }
export interface WorldHeritage { outline: Vec2[]; modelUrl: string | null; height: number }

export interface WorldSpec {
  buildings: WorldBuilding[]
  /** Canopies: `height` is the slab thickness; they sit at ROOF_Y_M on posts. */
  roofs: WorldBuilding[]
  platforms: WorldPlatform[]
  rails: Vec2[][]
  heritage: WorldHeritage | null
  /** Everything drawn (ground, clipping, far plane). */
  bounds: WorldBounds
  /**
   * What the opening camera frames (R17): the heritage ring and the traced graph's nodes (`focusPoints`, already in the
   * world frame) plus FOCUS_MARGIN_M, kept inside `bounds`. Platforms do not count: their far ends would pull it north.
   */
  focus: WorldBounds
  attribution: string
}

const round = (v: number) => Math.round(v * 1000) / 1000

/**
 * A plan point in metres (x right, y down the plan, from the plan's top-left: the tour's `position_m`) to the world
 * floor [x = east, z = -north]. Reproduces backend `Similarity.apply` on (x, -y), the input the fit was made on.
 */
export function planToWorld(alignment: TourWorldAlignment, [xPlan, yPlan]: Point): Vec2 {
  const a = (alignment.rotation_deg * Math.PI) / 180
  const c = alignment.scale * Math.cos(a)
  const s = alignment.scale * Math.sin(a)
  const [x, y] = [xPlan, -yPlan]
  const east = c * x - s * y + alignment.tx
  const north = s * x + c * y + alignment.ty
  return [east, -north]
}

/** osm.json [east, north] to the world floor [x, z]. */
const toWorld = ([east, north]: Point): Vec2 => [east, north === 0 ? 0 : -north]

/** Area centroid of a ring (open or closed); the vertex mean when the ring has no area. Same as the backend's. */
export function polygonCentroid(points: Vec2[]): Vec2 {
  let a = 0
  let cx = 0
  let cy = 0
  for (let i = 0; i < points.length; i += 1) {
    const [x1, y1] = points[i]
    const [x2, y2] = points[(i + 1) % points.length]
    const cross = x1 * y2 - x2 * y1
    a += cross
    cx += (x1 + x2) * cross
    cy += (y1 + y2) * cross
  }
  if (Math.abs(a) < 1e-9) {
    const n = points.length || 1
    return [points.reduce((t, p) => t + p[0], 0) / n, points.reduce((t, p) => t + p[1], 0) / n]
  }
  return [cx / (3 * a), cy / (3 * a)]
}

/** Building height: storeys × 3.2 m, else the tagged height, else 9 m. */
export function buildingHeight(f: TourWorldFeature): number {
  if (f.levels !== null && f.levels > 0) return round(f.levels * STOREY_HEIGHT_M)
  if (f.height_m !== null && f.height_m > 0) return f.height_m
  return DEFAULT_BUILDING_HEIGHT_M
}

const inside = (b: WorldBounds, [x, z]: Vec2) => x >= b.minX && x <= b.maxX && z >= b.minZ && z <= b.maxZ
const near = (f: TourWorldFeature) => f.points.some(([e, n]) => Math.hypot(e, n) <= COMPLEX_REACH_M)
const clamp = (v: number) => Math.min(COMPLEX_REACH_M, Math.max(-COMPLEX_REACH_M, v))

/** Bounds of the complex: buildings, roofs, platforms and the heritage building near the origin, never the rails. */
function complexBounds(features: TourWorldFeature[]): WorldBounds {
  const pts = features
    .filter((f) => ['building', 'roof', 'platform', 'heritage'].includes(f.kind) && near(f))
    .flatMap((f) => f.points.map(([e, n]) => toWorld([clamp(e), clamp(n)])))
  if (pts.length === 0) return { minX: -50, maxX: 50, minZ: -50, maxZ: 50 }
  const xs = pts.map((p) => p[0])
  const zs = pts.map((p) => p[1])
  return { minX: Math.min(...xs), maxX: Math.max(...xs), minZ: Math.min(...zs), maxZ: Math.max(...zs) }
}

/** Sutherland–Hodgman clip of a ring against the bounds rectangle (convex, so the result is one ring). */
export function clipRing(ring: Vec2[], b: WorldBounds): Vec2[] {
  type Edge = { keep: (p: Vec2) => boolean; cut: (p: Vec2, q: Vec2) => Vec2 }
  const atX = (x: number) => (p: Vec2, q: Vec2): Vec2 => [x, p[1] + ((q[1] - p[1]) * (x - p[0])) / (q[0] - p[0])]
  const atZ = (z: number) => (p: Vec2, q: Vec2): Vec2 => [p[0] + ((q[0] - p[0]) * (z - p[1])) / (q[1] - p[1]), z]
  const edges: Edge[] = [
    { keep: (p) => p[0] >= b.minX, cut: atX(b.minX) }, { keep: (p) => p[0] <= b.maxX, cut: atX(b.maxX) },
    { keep: (p) => p[1] >= b.minZ, cut: atZ(b.minZ) }, { keep: (p) => p[1] <= b.maxZ, cut: atZ(b.maxZ) },
  ]
  let out = ring
  for (const { keep, cut } of edges) {
    const input = out
    out = []
    for (let i = 0; i < input.length; i += 1) {
      const p = input[i]
      const q = input[(i + 1) % input.length]
      if (keep(p)) out.push(p)
      if (keep(p) !== keep(q)) out.push(cut(p, q))
    }
    if (out.length === 0) break
  }
  return out.map(([x, z]) => [round(x), round(z)])
}

/** Liang–Barsky clip of a polyline against the bounds: the pieces that lie inside. */
export function clipPolyline(line: Vec2[], b: WorldBounds): Vec2[][] {
  const pieces: Vec2[][] = []
  let current: Vec2[] = []
  const flush = () => { if (current.length > 1) pieces.push(current); current = [] }
  for (let i = 1; i < line.length; i += 1) {
    const [p, q] = [line[i - 1], line[i]]
    const d: Vec2 = [q[0] - p[0], q[1] - p[1]]
    let t0 = 0
    let t1 = 1
    const tests: [number, number][] = [[-d[0], p[0] - b.minX], [d[0], b.maxX - p[0]], [-d[1], p[1] - b.minZ], [d[1], b.maxZ - p[1]]]
    let visible = true
    for (const [pp, qq] of tests) {
      if (pp === 0) { if (qq < 0) visible = false; continue }
      const r = qq / pp
      if (pp < 0) t0 = Math.max(t0, r)
      else t1 = Math.min(t1, r)
    }
    if (!visible || t0 > t1) { flush(); continue }
    const a: Vec2 = [round(p[0] + d[0] * t0), round(p[1] + d[1] * t0)]
    const e: Vec2 = [round(p[0] + d[0] * t1), round(p[1] + d[1] * t1)]
    const last = current[current.length - 1]
    if (!last || last[0] !== a[0] || last[1] !== a[1]) { flush(); current.push(a) }
    current.push(e)
    if (t1 < 1) flush()
  }
  flush()
  return pieces
}

/** OSM way id → the traced platform numbers fitted onto it (metadata world_alignment pairs + platform_labels). */
function tracedLabels(alignment: TourWorldAlignment): Map<string, string[]> {
  const pairs = Array.isArray(alignment.pairs) ? (alignment.pairs as { area?: unknown; osm?: unknown }[]) : []
  const labels = Array.isArray(alignment.platform_labels) ? (alignment.platform_labels as { area?: unknown; label?: unknown }[]) : []
  const labelOf = new Map(labels.map((l) => [String(l.area), String(l.label)]))
  const out = new Map<string, string[]>()
  for (const p of pairs) {
    const label = labelOf.get(String(p.area))
    if (typeof p.osm === 'string' && label) out.set(p.osm, [...(out.get(p.osm) ?? []), label])
  }
  for (const [k, v] of out) out.set(k, [...new Set(v)].sort((a, b) => Number(a) - Number(b) || a.localeCompare(b)))
  return out
}

/**
 * The drawable world, or null without a world or an alignment (the plan cannot be placed in it). Platforms the
 * traced plan was fitted onto carry the plan's numbers (what the route and the pins use); other platforms their
 * OSM ref ("3;4" shown as "3 · 4"), unless the ref names a number the plan already puts elsewhere: the plan and OSM
 * number the platforms differently here (metadata parity_basis), and two "9 · 10" labels would contradict each other.
 */
export function buildWorldSpec(world: TourWorld | null | undefined, focusPoints: Vec2[] = []): WorldSpec | null {
  if (!world || !world.alignment) return null
  const { features } = world
  const bounds = complexBounds(features)
  const traced = tracedLabels(world.alignment)
  const planNumbers = new Set([...traced.values()].flat())
  const ring = (f: TourWorldFeature) => f.points.map(toWorld)
  const centredIn = (f: TourWorldFeature) => f.points.length > 2 && inside(bounds, polygonCentroid(ring(f)))

  const buildings = features.filter((f) => f.kind === 'building' && centredIn(f))
    .map((f) => ({ outline: ring(f), height: buildingHeight(f) }))
  const roofs = features.filter((f) => f.kind === 'roof' && centredIn(f))
    .map((f) => ({ outline: ring(f), height: ROOF_THICKNESS_M }))
  const platforms: WorldPlatform[] = features.filter((f) => f.kind === 'platform' && near(f)).flatMap((f): WorldPlatform[] => {
    const outline = clipRing(ring(f), bounds)
    if (outline.length < 3) return []
    const plan = traced.get(f.id)
    if (plan?.length) return [{ outline, label: plan.join(' · '), labelSource: 'station_plan' }]
    const refs = (f.ref ?? '').split(';').map((r) => r.trim()).filter(Boolean)
    if (refs.length > 0 && !refs.some((r) => planNumbers.has(r))) return [{ outline, label: refs.join(' · '), labelSource: 'osm' }]
    return [{ outline, label: null, labelSource: null }]
  })
  const rails = features.filter((f) => f.kind === 'rail').flatMap((f) => clipPolyline(f.points.map(toWorld), bounds))

  const modelFeature = world.model?.feature_id
  const h = features.find((f) => f.kind === 'heritage' && (!modelFeature || f.id === modelFeature))
    ?? features.find((f) => f.kind === 'heritage')
  const heritage: WorldHeritage | null = h ? {
    outline: ring(h),
    modelUrl: world.model && world.model.feature_id === h.id ? world.model.url : null,
    height: world.model?.height_m ?? HERITAGE_HEIGHT_M,
  } : null

  const focus = focusBounds([...(heritage ? [heritage.outline] : []), focusPoints], bounds)
  return { buildings, roofs, platforms, rails, heritage, bounds, focus, attribution: OSM_ATTRIBUTION }
}

/** Bounds of the given rings plus FOCUS_MARGIN_M, kept inside `within`; `within` itself when there are no rings. */
function focusBounds(rings: Vec2[][], within: WorldBounds): WorldBounds {
  const pts = rings.flat()
  if (pts.length === 0) return within
  const xs = pts.map((p) => p[0])
  const zs = pts.map((p) => p[1])
  return {
    minX: Math.max(within.minX, Math.min(...xs) - FOCUS_MARGIN_M), maxX: Math.min(within.maxX, Math.max(...xs) + FOCUS_MARGIN_M),
    minZ: Math.max(within.minZ, Math.min(...zs) - FOCUS_MARGIN_M), maxZ: Math.min(within.maxZ, Math.max(...zs) + FOCUS_MARGIN_M),
  }
}

/** Ray-casting point-in-ring test on the floor plane. */
export function insideRing([x, z]: Vec2, ring: Vec2[]): boolean {
  let hit = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const [xi, zi] = ring[i]
    const [xj, zj] = ring[j]
    if ((zi > z) !== (zj > z) && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi) hit = !hit
  }
  return hit
}

/**
 * Which platforms show their label: every labelled one when the camera is within LABEL_DISTANCE_M of its target,
 * otherwise only the island the route ends on (so the opening view on a phone is not a pile of overlapping labels).
 */
export function shownPlatformLabels(platforms: WorldPlatform[], cameraDistance: number, routeEnd: Vec2 | null): Set<number> {
  const shown = new Set<number>()
  platforms.forEach((p, i) => {
    if (!p.label) return
    if (cameraDistance <= LABEL_DISTANCE_M || (routeEnd && insideRing(routeEnd, p.outline))) shown.add(i)
  })
  return shown
}

/**
 * A camera pose that keeps the whole complex (ground to FRAME_TOP_M) in view on a canvas of the given aspect
 * (width / height), looking north from the south at FRAME_PITCH_DEG, so the frontage faces the camera.
 */
export function frameBounds(bounds: WorldBounds, aspect: number, fovDeg = 50): CameraPose {
  const target: Vec3 = [(bounds.minX + bounds.maxX) / 2, 0, (bounds.minZ + bounds.maxZ) / 2]
  const pitch = (FRAME_PITCH_DEG * Math.PI) / 180
  const dir: Vec3 = [0, Math.sin(pitch), Math.cos(pitch)] // target → camera
  const up: Vec3 = [0, Math.cos(pitch), -Math.sin(pitch)]
  const margin = 0.92
  const tanV = Math.tan(((fovDeg * Math.PI) / 180) / 2) * margin
  const tanH = tanV * aspect
  let distance = 1
  for (const x of [bounds.minX, bounds.maxX]) {
    for (const z of [bounds.minZ, bounds.maxZ]) {
      for (const y of [0, FRAME_TOP_M]) {
        const p = [x - target[0], y - target[1], z - target[2]]
        const along = p[1] * dir[1] + p[2] * dir[2]
        const vertical = p[1] * up[1] + p[2] * up[2]
        distance = Math.max(distance, along + Math.abs(vertical) / tanV, along + Math.abs(p[0]) / tanH)
      }
    }
  }
  return {
    position: [round(target[0]), round(distance * dir[1]), round(target[2] + distance * dir[2])],
    target: [round(target[0]), 0, round(target[2])],
  }
}
