// Google Maps link-outs (Maps URLs, no key needed) for when Street View cannot open inside the app: no browser key,
// or a Maps outage. Coordinates come from the station's geo_reference, which is approximate and says by how much.
import type { GeoReference, Point, StationTour, TourPanorama } from '../api/types'

const EARTH_RADIUS_M = 6_371_000
const MAPS = 'https://www.google.com/maps'

export interface LatLon {
  lat: number
  lon: number
}

/**
 * Plan point to latitude/longitude: the forward form of `latlon_to_plan` in backend/scripts/stations.py (anchor,
 * metres per pixel, rotation of plan-up from north clockwise; small-offset equirectangular).
 */
export function planToLatLon(geo: GeoReference, mapSize: { width_px: number; height_px: number }, p: Point): LatLon {
  const right = (p[0] - geo.anchor.x) * mapSize.width_px * geo.metres_per_pixel
  const up = -(p[1] - geo.anchor.y) * mapSize.height_px * geo.metres_per_pixel
  const rot = (geo.rotation_deg * Math.PI) / 180
  const east = right * Math.cos(rot) + up * Math.sin(rot)
  const north = -right * Math.sin(rot) + up * Math.cos(rot)
  const lat = geo.anchor.lat + (north / EARTH_RADIUS_M) * (180 / Math.PI)
  const lon = geo.anchor.lon + (east / (EARTH_RADIUS_M * Math.cos((geo.anchor.lat * Math.PI) / 180))) * (180 / Math.PI)
  return { lat: Number(lat.toFixed(6)), lon: Number(lon.toFixed(6)) }
}

/** A specific panorama in Google Maps' own Street View viewer. */
export function panoramaLink(p: TourPanorama): string {
  const q = new URLSearchParams({ api: '1', map_action: 'pano', pano: p.pano_id, heading: String(p.heading), pitch: String(p.pitch) })
  return `${MAPS}/@?${q}`
}

/**
 * Google Maps at a node's approximate coordinates (or the station anchor). Without a geo_reference it searches for
 * the station by name instead, and `approximate_m` is null.
 */
export function placeLink(tour: StationTour, position?: Point): { url: string; approximate_m: number | null } {
  const geo = tour.geo_reference
  if (!geo) {
    const q = new URLSearchParams({ api: '1', query: `${tour.station_name} railway station` })
    return { url: `${MAPS}/search/?${q}`, approximate_m: null }
  }
  const at = planToLatLon(geo, tour.map, position ?? [geo.anchor.x, geo.anchor.y])
  const q = new URLSearchParams({ api: '1', query: `${at.lat},${at.lon}` })
  return { url: `${MAPS}/search/?${q}`, approximate_m: geo.expected_error_m }
}
