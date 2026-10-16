// Pure formatting helpers for route figures returned by the backend.
import type { Point, RouteResult } from '../api/types'

export function formatMetres(m: number | null): string | null {
  return m === null ? null : `${Math.round(m)} m`
}

/** Whole minutes, never less than 1 for a non-zero duration. */
export function formatMinutes(seconds: number | null): number | null {
  if (seconds === null) return null
  return seconds <= 0 ? 0 : Math.max(1, Math.round(seconds / 60))
}

/** Distance the backend could support: measured if every pathway is measured, else the plan-scale estimate. */
export function routeDistance(route: RouteResult): number | null {
  return route.distance_m ?? route.estimated_distance_m
}

/** Bounding box of a polyline in normalized map coordinates, or null when empty. */
export function bounds(points: Point[]): { minX: number; minY: number; maxX: number; maxY: number } | null {
  if (points.length === 0) return null
  return points.reduce(
    (b, [x, y]) => ({ minX: Math.min(b.minX, x), minY: Math.min(b.minY, y), maxX: Math.max(b.maxX, x), maxY: Math.max(b.maxY, y) }),
    { minX: points[0][0], minY: points[0][1], maxX: points[0][0], maxY: points[0][1] },
  )
}
