// Route → 3D path → camera, as pure functions (no three.js), so the fly-through is unit-tested.
import type { RouteResult, StationTour, TourPanorama } from '../api/types'
import { levelY, liftPolyline, PATH_LIFT, toFloor, type SceneSpec, type Vec2, type Vec3 } from './sceneSpec'

export interface CameraPose {
  position: Vec3
  target: Vec3
}

/** Eye height above the route and how far behind and ahead of the walker the camera sits (metres or plan units). */
export const EYE_HEIGHT = 12
export const EYE_BEHIND = 14
export const LOOK_AHEAD = 20

const same = (a: Vec3, b: Vec3) => a[0] === b[0] && a[1] === b[1] && a[2] === b[2]

/**
 * The route's `geometry`, segment by segment, in world coordinates. Each segment climbs from its start node's level
 * to its end node's level along its own geometry. Falls back to `route.geometry` on the start node's level when the
 * response has no segments.
 */
export function routeToPath(route: RouteResult, tour: StationTour, spec: SceneSpec): Vec3[] {
  if (route.status !== 'ok') return []
  const nodeLevel = new Map(tour.nodes.map((n) => [n.id, n.level]))
  const y = (nodeId: string | undefined) => levelY(spec.levels, nodeLevel.get(nodeId ?? '') ?? spec.floor.level) + PATH_LIFT
  const floor = (pts: RouteResult['geometry']): Vec2[] => pts.map((p) => toFloor(spec.frame, p))
  const out: Vec3[] = []
  const push = (p: Vec3) => { if (out.length === 0 || !same(out[out.length - 1], p)) out.push(p) }
  if (route.segments.length > 0 && route.segments.every((s) => s.geometry?.length > 1)) {
    for (const s of route.segments) liftPolyline(floor(s.geometry), y(s.from_node), y(s.to_node)).forEach(push)
  } else {
    const level = y(route.node_ids[0])
    liftPolyline(floor(route.geometry), level, level).forEach(push)
  }
  return out
}

export function pathLength(path: Vec3[]): number {
  let total = 0
  for (let i = 1; i < path.length; i += 1) total += dist(path[i - 1], path[i])
  return total
}

function dist(a: Vec3, b: Vec3): number {
  return Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2])
}

/** The point at fraction `t` (0..1, clamped) of the path's length. */
export function pointAt(path: Vec3[], t: number): Vec3 {
  if (path.length === 0) return [0, 0, 0]
  if (path.length === 1) return path[0]
  const goal = Math.min(1, Math.max(0, t)) * pathLength(path)
  let walked = 0
  for (let i = 1; i < path.length; i += 1) {
    const step = dist(path[i - 1], path[i])
    if (walked + step >= goal && step > 0) {
      const f = (goal - walked) / step
      const [a, b] = [path[i - 1], path[i]]
      return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f]
    }
    walked += step
  }
  return path[path.length - 1]
}

/**
 * Camera at fraction `t` of the walk: it looks at a point LOOK_AHEAD along the route from the walker and sits
 * EYE_BEHIND back along the route and EYE_HEIGHT above it, so it follows the route round corners.
 */
export function cameraAt(path: Vec3[], t: number): CameraPose {
  const length = pathLength(path)
  const clamp = (v: number) => Math.min(1, Math.max(0, v))
  const tt = clamp(t)
  if (length === 0) {
    const p = pointAt(path, 0)
    return { position: [p[0], p[1] + EYE_HEIGHT, p[2] + EYE_BEHIND], target: p }
  }
  const here = pointAt(path, tt)
  const ahead = pointAt(path, clamp(tt + LOOK_AHEAD / length))
  const behind = pointAt(path, clamp(tt - EYE_BEHIND / length))
  // At the very start there is nothing behind: step back against the direction of travel instead.
  let back: Vec3 = behind
  if (dist(behind, here) < 1e-6) {
    const dir = sub(ahead, here)
    const n = Math.hypot(dir[0], dir[2]) || 1
    back = [here[0] - (dir[0] / n) * EYE_BEHIND, here[1], here[2] - (dir[2] / n) * EYE_BEHIND]
  }
  return { position: [back[0], back[1] + EYE_HEIGHT, back[2]], target: dist(ahead, here) < 1e-6 ? here : ahead }
}

function sub(a: Vec3, b: Vec3): Vec3 {
  return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}

/** `count` evenly spaced camera poses from start to end: the motion-free way to step along a route. */
export function cameraKeyframes(path: Vec3[], count = 5): CameraPose[] {
  if (path.length === 0) return []
  const n = Math.max(2, count)
  return Array.from({ length: n }, (_, i) => cameraAt(path, i / (n - 1)))
}

/** Fly-through duration: a steady 15 units/s, between 4 and 30 seconds. */
export function flyDurationMs(length: number): number {
  return Math.round(Math.min(30_000, Math.max(4_000, (length / 15) * 1000)))
}

/** A pose that frames the whole route from above (used to show a route without animating). */
export function overviewPose(path: Vec3[]): CameraPose | null {
  if (path.length === 0) return null
  const xs = path.map((p) => p[0])
  const ys = path.map((p) => p[1])
  const zs = path.map((p) => p[2])
  const centre: Vec3 = [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2, (Math.min(...zs) + Math.max(...zs)) / 2]
  const span = Math.max(20, Math.max(...xs) - Math.min(...xs), Math.max(...zs) - Math.min(...zs))
  return { position: [centre[0], centre[1] + span * 1.3, centre[2] + span], target: centre }
}

/** Panoramas on the route, in walking order (one per pano id): the Street View "step along the route" stops. */
export function routePanoramaStops(nodeIds: string[], panoramas: TourPanorama[]): TourPanorama[] {
  const seen = new Set<string>()
  const out: TourPanorama[] = []
  for (const id of nodeIds) {
    for (const p of panoramas) {
      if (p.node_id === id && !seen.has(p.pano_id)) {
        seen.add(p.pano_id)
        out.push(p)
      }
    }
  }
  return out
}
