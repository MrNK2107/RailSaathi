// Pure bearing maths for AR guidance. No browser APIs, so all of it is unit-tested.
//
// Frames and conventions (same as backend navigation/services/geometry.py):
// - Plan coordinates are normalised image coordinates (x right, y down), scaled by the map's pixel size before any
//   angle is taken, so a non-square plan does not skew bearings.
// - A bearing is degrees clockwise from plan-up. The /localize `facing_bearing_deg` uses the same station frame.
// - geo_reference.rotation_deg turns a station bearing into a true bearing. The arrow is a difference of two
//   station-frame bearings, so the rotation cancels; `toTrueBearing` exists for display and is tested to cancel.
// - The phone's yaw comes from the gyroscope (relative `deviceorientation`), never the magnetometer: only the change
//   since the fix is used, and steel roofs cannot bend it.
import type { LocalizeFix, Point, RouteInstruction, RouteResult, StationNode } from '../api/types'

export const normalizeDeg = (deg: number): number => ((deg % 360) + 360) % 360

/** Shortest signed angle from `from` to `to`, in (-180, 180]; positive is clockwise (a right turn). */
export function signedDeltaDeg(from: number, to: number): number {
  const d = normalizeDeg(to - from)
  return d > 180 ? d - 360 : d
}

/** Bearing from a to b on the plan, clockwise from plan-up; null when the points coincide. */
export function planBearingDeg(a: Point, b: Point, width: number, height: number): number | null {
  const dx = (b[0] - a[0]) * width
  const dy = (b[1] - a[1]) * height
  if (Math.abs(dx) < 1e-9 && Math.abs(dy) < 1e-9) return null
  return normalizeDeg((Math.atan2(dx, -dy) * 180) / Math.PI)
}

/** First non-degenerate heading along a polyline. */
export function firstHeadingDeg(points: Point[], width: number, height: number): number | null {
  for (let i = 1; i < points.length; i += 1) {
    const h = planBearingDeg(points[i - 1], points[i], width, height)
    if (h !== null) return h
  }
  return null
}

export function toTrueBearing(stationBearingDeg: number, rotationDeg: number): number {
  return normalizeDeg(stationBearingDeg + rotationDeg)
}

/**
 * Which way the rear camera points, from a `deviceorientation` event (W3C DeviceOrientation, rear-camera vector of
 * R = Rz(alpha)·Rx(beta)·Ry(gamma)), clockwise in the event's own reference frame. With relative events that frame
 * is arbitrary, so only differences are meaningful. Null when the camera points (nearly) straight up or down.
 */
export function cameraYawDeg(alpha: number | null, beta: number | null, gamma: number | null): number | null {
  if (alpha === null || beta === null || gamma === null) return null
  const r = Math.PI / 180
  const sX = Math.sin(beta * r)
  const [cY, sY] = [Math.cos(gamma * r), Math.sin(gamma * r)]
  const [cZ, sZ] = [Math.cos(alpha * r), Math.sin(alpha * r)]
  const vx = -cZ * sY - sZ * sX * cY
  const vy = -sZ * sY + cZ * sX * cY
  if (Math.hypot(vx, vy) < 0.2) return null // camera within ~12° of vertical: heading is not defined
  return normalizeDeg((Math.atan2(vx, vy) * 180) / Math.PI)
}

/** Clockwise turn of the phone since the fix, handling wrap-around (359° → 1° is +2°). */
export function yawSinceFixDeg(yawAtFix: number | null, yawNow: number | null): number {
  if (yawAtFix === null || yawNow === null) return 0
  return signedDeltaDeg(yawAtFix, yawNow)
}

/**
 * Where the on-screen arrow points, relative to straight ahead (0 = ahead, positive = to the right), in (-180, 180].
 * target bearing − facing bearing at the fix − the clockwise turn since the fix. Null without a facing bearing.
 */
export function arrowAngleDeg(targetBearingDeg: number | null, facingBearingDeg: number | null, yawSinceFix: number,
  rotationDeg = 0): number | null {
  if (targetBearingDeg === null || facingBearingDeg === null) return null
  const target = toTrueBearing(targetBearingDeg, rotationDeg)
  const facing = toTrueBearing(facingBearingDeg, rotationDeg)
  return signedDeltaDeg(0, target - facing - yawSinceFix)
}

export type Direction = 'ahead' | 'slight_right' | 'right' | 'slight_left' | 'left' | 'behind'

/** Words for the arrow (screen readers and the caption under it). */
export function directionOf(angle: number): Direction {
  const a = Math.abs(angle)
  if (a <= 20) return 'ahead'
  if (a > 135) return 'behind'
  if (angle > 0) return a <= 60 ? 'slight_right' : 'right'
  return a <= 60 ? 'slight_left' : 'left'
}

export type GuidanceTarget =
  | { kind: 'arrived'; nodeName: string }
  | { kind: 'on_route'; bearingDeg: number | null; instruction: RouteInstruction | null; nextNodeName: string }
  | { kind: 'off_route'; bearingDeg: number | null; rejoinNodeName: string }

/**
 * What to point at from the fixed node: the next waypoint along the route (the first heading of the segment that
 * leaves the node), the destination when it is the node itself, or the nearest route node when off the route.
 */
export function guidanceTarget(route: RouteResult, nodes: StationNode[], fix: Pick<LocalizeFix, 'node_id' | 'position'>,
  width: number, height: number): GuidanceTarget {
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const name = (id: string) => byId.get(id)?.name ?? id
  const ids = route.node_ids
  const index = ids.indexOf(fix.node_id)
  if (index >= 0 && index === ids.length - 1) return { kind: 'arrived', nodeName: name(fix.node_id) }
  if (index >= 0) {
    const segment = route.segments.find((s) => s.from_node === fix.node_id)
    const next = ids[index + 1]
    const nextPos = byId.get(next)?.position
    const bearing = (segment ? firstHeadingDeg(segment.geometry, width, height) : null)
      ?? (nextPos ? planBearingDeg(fix.position, nextPos, width, height) : null)
    const instruction = route.instructions.find((i) => i.node_id === fix.node_id) ?? null
    return { kind: 'on_route', bearingDeg: bearing, instruction, nextNodeName: name(next) }
  }
  let best: { id: string; d: number } | null = null
  for (const id of ids) {
    const p = byId.get(id)?.position
    if (!p) continue
    const d = Math.hypot((p[0] - fix.position[0]) * width, (p[1] - fix.position[1]) * height)
    if (!best || d < best.d) best = { id, d }
  }
  if (!best) return { kind: 'off_route', bearingDeg: null, rejoinNodeName: '' }
  return { kind: 'off_route', bearingDeg: planBearingDeg(fix.position, byId.get(best.id)!.position, width, height),
    rejoinNodeName: name(best.id) }
}
