// Pure tour maths: scene spec, route → camera path, Maps link-outs, and the payload shape the types mirror.
// The Chennai Central fixtures are real responses of GET /api/stations/chennai_central/tour and
// POST /api/navigation/route (ent_wall_tax → platform_10), captured from the backend at 48ea318.
import type { RouteResult, StationTour, TourNode } from '../api/types'
import {
  cameraAt, cameraKeyframes, EYE_HEIGHT, flyDurationMs, overviewPose, pathLength, pointAt, routePanoramaStops, routeToPath,
} from '../tour/cameraPath'
import { panoramaLink, placeLink, planToLatLon } from '../tour/mapsLinks'
import {
  buildSceneSpec, DEFAULT_LEVEL_GAP, liftPolyline, nearbyFacilities, PATH_LIFT, PIN_HEIGHT, toFloor, type Vec3,
} from '../tour/sceneSpec'
import routeJson from './data/chennai_central_route.json'
import tourJson from './data/chennai_central_tour.json'

const chennai = tourJson as unknown as StationTour
const chennaiRoute = routeJson as unknown as RouteResult
const prov = chennai.provenance

const node = (id: string, level: number, position: [number, number], type = 'junction'): TourNode => ({
  id, name: id.toUpperCase(), type, level, position, position_m: null, verification: 'pending', step_free: 'unknown', status: 'open', cues: [],
})

/** Two levels, no map scale: the shape of a future multi-level station. */
const twoLevel = (over: Partial<StationTour> = {}): StationTour => ({
  station_id: 'test_station', station_name: 'Test Station', version: 'local', layout_basis: 'schematic', routing_enabled: true,
  ar_enabled: false, ar_guidance_available: false, map: { url: '/api/stations/test_station/map', width_px: 1000, height_px: 500 },
  scale: null, frame: '', geo_reference: null,
  levels: [{ level: 0, name: 'Concourse', elevation_m: 0 }, { level: 1, name: 'Foot-over-bridge', elevation_m: null }],
  areas: [{ id: 'deck', kind: 'concourse', name: null, level: 1, height_m: 0.3, polygon: [[0, 0], [0.5, 0], [0.5, 0.5], [0, 0.5], [0, 0]], polygon_m: null }],
  nodes: [node('a', 0, [0, 0], 'entrance'), node('b', 1, [0.5, 0]), node('t', 1, [0.5, 0.5], 'toilet'), node('s', 0, [1, 1], 'shop')],
  edges: [
    { id: 'ab', from: 'a', to: 'b', bidirectional: true, path_type: 'stairs', level_change: 1, steps: 20, step_free: 'unknown', status: 'open',
      verification: 'pending', distance_m: null, geometry: [[0, 0], [0.25, 0], [0.5, 0]], geometry_m: null },
    { id: 'bt', from: 'b', to: 't', bidirectional: true, path_type: 'walkway', level_change: 0, steps: null, step_free: 'unknown', status: 'open',
      verification: 'pending', distance_m: null, geometry: [[0.5, 0], [0.5, 0.5]], geometry_m: null },
  ],
  panoramas: [{ pano_id: 'PANO_B', node_id: 'b', heading: 90, pitch: 0, kind: 'street_view', verified_on: null }],
  panoramas_note: null, provenance: prov, ...over,
})

describe('tour payload shape (types mirror the backend)', () => {
  // Keys of the real payload must be exactly the keys the TypeScript types declare.
  const tourKeys: Record<keyof StationTour, true> = {
    station_id: true, station_name: true, version: true, layout_basis: true, routing_enabled: true, ar_enabled: true,
    ar_guidance_available: true, map: true, scale: true, frame: true, geo_reference: true, levels: true, areas: true, nodes: true,
    edges: true, panoramas: true, panoramas_note: true, provenance: true,
  }
  const nodeKeys: Record<keyof TourNode, true> = {
    id: true, name: true, type: true, level: true, position: true, position_m: true, verification: true, step_free: true, status: true, cues: true,
  }
  const edgeKeys: Record<keyof StationTour['edges'][number], true> = {
    id: true, from: true, to: true, bidirectional: true, path_type: true, level_change: true, steps: true, step_free: true, status: true,
    verification: true, distance_m: true, geometry: true, geometry_m: true,
  }
  const areaKeys: Record<keyof StationTour['areas'][number], true> = {
    id: true, kind: true, name: true, level: true, height_m: true, polygon: true, polygon_m: true,
  }
  const sorted = (o: object) => Object.keys(o).sort()
  it('top level, nodes, edges and areas carry exactly the typed fields', () => {
    expect(sorted(chennai)).toEqual(sorted(tourKeys))
    for (const n of chennai.nodes) expect(sorted(n)).toEqual(sorted(nodeKeys))
    for (const e of chennai.edges) expect(sorted(e)).toEqual(sorted(edgeKeys))
    for (const a of chennai.areas) expect(sorted(a)).toEqual(sorted(areaKeys))
    expect(sorted(chennai.scale!)).toEqual(['height_m', 'metres_per_pixel', 'source', 'verification', 'width_m'])
    expect(sorted(chennai.geo_reference!)).toEqual(['anchor', 'expected_error_m', 'method', 'metres_per_pixel', 'rotation_deg', 'source', 'verification'])
  })
  it('the route response carries node ids and per-segment geometry', () => {
    expect(chennaiRoute.node_ids[0]).toBe('ent_wall_tax')
    expect(chennaiRoute.node_ids[chennaiRoute.node_ids.length - 1]).toBe('platform_10')
    for (const s of chennaiRoute.segments) expect(s.geometry.length).toBeGreaterThan(1)
  })
})

describe('buildSceneSpec', () => {
  it('Chennai Central: metres frame centred on the origin, one ground level, the plan as the floor', () => {
    const spec = buildSceneSpec(chennai)
    expect(spec.frame).toEqual({ units: 'metres', width: 324.03, depth: 153.74 })
    expect(spec.levels).toEqual([{ level: 0, name: 'Ground level (concourse and platforms)', y: 0, elevationKnown: true }])
    expect(spec.floor).toEqual({ url: '/api/stations/chennai_central/map', level: 0, y: 0, width: 324.03, depth: 153.74 })
    expect(spec.traced).toBe(true)
    expect(spec.radius).toBeCloseTo(Math.hypot(324.03, 153.74) / 2, 2)
  })

  it('Chennai Central: traced areas are extruded rings at their nominal heights, closing point dropped', () => {
    const spec = buildSceneSpec(chennai)
    expect(spec.areas).toHaveLength(14)
    const building = spec.areas.find((a) => a.id === 'building')!
    expect(building.kind).toBe('building_footprint')
    expect(building.height).toBe(8)
    expect(building.opacity).toBeLessThan(0.5) // see-through, so it does not hide the concourse
    expect(building.outline).toHaveLength(4)
    expect(building.outline[0]).toEqual([round(98.94 - 324.03 / 2), round(27.05 - 153.74 / 2)])
    const platform = spec.areas.find((a) => a.kind === 'platform')!
    expect(platform.height).toBe(0.84)
    expect(platform.name).toMatch(/traced from the schematic plan, approximate/)
  })

  it('Chennai Central: one pin per node at its metres position, inside the plan; pathways lifted above the level', () => {
    const spec = buildSceneSpec(chennai)
    expect(spec.pins).toHaveLength(chennai.nodes.length)
    const wallTax = spec.pins.find((p) => p.id === 'ent_wall_tax')!
    expect(wallTax.position).toEqual([round(158.9 - 324.03 / 2), PIN_HEIGHT, round(28.11 - 153.74 / 2)])
    expect(wallTax.stepFree).toBe('unknown') // exactly as returned
    for (const p of spec.pins) {
      expect(Math.abs(p.position[0])).toBeLessThanOrEqual(324.03 / 2)
      expect(Math.abs(p.position[2])).toBeLessThanOrEqual(153.74 / 2)
      expect(p.hasPanorama).toBe(false) // panoramas: [] until the owner authors them
    }
    expect(spec.pins.filter((p) => p.isFacility).map((p) => p.type).sort()).toEqual(
      chennai.nodes.filter((n) => ['toilet', 'ticket_counter', 'information_desk', 'shop'].includes(n.type)).map((n) => n.type).sort())
    expect(spec.edges).toHaveLength(chennai.edges.length)
    for (const e of spec.edges) for (const p of e.points) expect(p[1]).toBe(PATH_LIFT)
  })

  it('no map scale: plan units keep the plan aspect ratio; unstated elevations stack by the default gap', () => {
    const spec = buildSceneSpec(twoLevel())
    expect(spec.frame).toEqual({ units: 'plan_units', width: 100, depth: 50 })
    expect(spec.levels.map((l) => [l.level, l.y, l.elevationKnown])).toEqual([[0, 0, true], [1, DEFAULT_LEVEL_GAP, false]])
    expect(spec.areas[0].y).toBe(DEFAULT_LEVEL_GAP)
    expect(spec.areas[0].outline).toEqual([[-50, -25], [0, -25], [0, 0], [-50, 0]])
    expect(spec.pins.find((p) => p.id === 'b')!.position).toEqual([0, DEFAULT_LEVEL_GAP + PIN_HEIGHT, -25])
    expect(spec.pins.find((p) => p.id === 'b')!.hasPanorama).toBe(true)
  })

  it('a stair between levels climbs along its own geometry', () => {
    const stair = buildSceneSpec(twoLevel()).edges.find((e) => e.id === 'ab')!
    expect(stair.points.map((p) => p[1])).toEqual([PATH_LIFT, PATH_LIFT + DEFAULT_LEVEL_GAP / 2, PATH_LIFT + DEFAULT_LEVEL_GAP])
  })

  it('untraced station (routing disabled): floor and areas only, no pins or pathways, like the 2D map', () => {
    const spec = buildSceneSpec(twoLevel({ routing_enabled: false }))
    expect(spec.traced).toBe(false)
    expect(spec.pins).toEqual([])
    expect(spec.edges).toEqual([])
    expect(spec.areas).toHaveLength(1)
  })

  it('no levels listed: levels come from the nodes, unnamed', () => {
    const spec = buildSceneSpec(twoLevel({ levels: [], areas: [] }))
    expect(spec.levels).toEqual([
      { level: 0, name: null, y: 0, elevationKnown: false },
      { level: 1, name: null, y: DEFAULT_LEVEL_GAP, elevationKnown: false },
    ])
  })

  it('toFloor uses the backend metres when present and the normalised point otherwise', () => {
    const frame = { units: 'metres' as const, width: 200, depth: 100 }
    expect(toFloor(frame, [0.5, 0.5], [101, 49])).toEqual([1, -1])
    expect(toFloor(frame, [0.25, 0.75])).toEqual([-50, 25])
  })

  it('nearbyFacilities lists facilities within two pathways, nearest first', () => {
    const tour = twoLevel()
    expect(nearbyFacilities(tour, 'a').map((n) => n.id)).toEqual(['t'])
    expect(nearbyFacilities(tour, 'a', 1)).toEqual([])
    expect(nearbyFacilities(chennai, 'toilet_west').every((n) => n.id !== 'toilet_west')).toBe(true)
  })
})

describe('route → camera path', () => {
  it('Chennai route: starts at the entrance, ends at the platform, no repeated joints, length matches the geometry', () => {
    const spec = buildSceneSpec(chennai)
    const path = routeToPath(chennaiRoute, chennai, spec)
    const at = (id: string) => {
      const n = chennai.nodes.find((x) => x.id === id)!
      const [x, z] = toFloor(spec.frame, n.position)
      return [x, PATH_LIFT, z]
    }
    expect(path[0]).toEqual(at('ent_wall_tax'))
    expect(path[path.length - 1]).toEqual(at('platform_10'))
    for (let i = 1; i < path.length; i += 1) expect(path[i]).not.toEqual(path[i - 1])
    const flat = chennaiRoute.geometry.map((p) => toFloor(spec.frame, p))
    let expected = 0
    for (let i = 1; i < flat.length; i += 1) expected += Math.hypot(flat[i][0] - flat[i - 1][0], flat[i][1] - flat[i - 1][1])
    expect(pathLength(path)).toBeCloseTo(expected, 1)
  })

  it('climbs between levels segment by segment', () => {
    const tour = twoLevel()
    const spec = buildSceneSpec(tour)
    const route = {
      ...chennaiRoute, node_ids: ['a', 'b', 't'], geometry: [[0, 0], [0.25, 0], [0.5, 0], [0.5, 0.5]],
      segments: [
        { edge_id: 'ab', from_node: 'a', to_node: 'b', geometry: [[0, 0], [0.25, 0], [0.5, 0]], level_change: 1, path_type: 'stairs', step_free: 'unknown' },
        { edge_id: 'bt', from_node: 'b', to_node: 't', geometry: [[0.5, 0], [0.5, 0.5]], level_change: 0, path_type: 'walkway', step_free: 'unknown' },
      ],
    } as RouteResult
    expect(routeToPath(route, tour, spec)).toEqual([[-50, 1, -25], [-25, 4, -25], [0, 7, -25], [0, 7, 0]])
  })

  it('no_route gives no path; a route without segments falls back to its geometry on the start level', () => {
    const tour = twoLevel()
    const spec = buildSceneSpec(tour)
    expect(routeToPath({ ...chennaiRoute, status: 'no_route' }, tour, spec)).toEqual([])
    const bare = { ...chennaiRoute, node_ids: ['b'], segments: [], geometry: [[0.5, 0], [0.5, 0.5]] } as RouteResult
    expect(routeToPath(bare, tour, spec)).toEqual([[0, 7, -25], [0, 7, 0]])
  })

  const L: Vec3[] = [[0, 0, 0], [30, 0, 0], [30, 0, 30]]

  it('pointAt walks by arc length and clamps', () => {
    expect(pathLength(L)).toBe(60)
    expect(pointAt(L, 0)).toEqual([0, 0, 0])
    expect(pointAt(L, 0.25)).toEqual([15, 0, 0])
    expect(pointAt(L, 0.75)).toEqual([30, 0, 15])
    expect(pointAt(L, 2)).toEqual([30, 0, 30])
    expect(pointAt(L, -1)).toEqual([0, 0, 0])
  })

  it('cameraAt sits above and behind the walker and looks ahead along the route, round corners', () => {
    const start = cameraAt(L, 0)
    expect(start.target).toEqual([20, 0, 0]) // LOOK_AHEAD along the first leg
    expect(start.position).toEqual([-14, EYE_HEIGHT, 0]) // nothing behind yet: steps back against travel
    const corner = cameraAt(L, 0.5) // at the corner (30, 0, 0)
    expectVec(corner.target, [30, 0, 20])
    expectVec(corner.position, [16, EYE_HEIGHT, 0])
    const end = cameraAt(L, 1)
    expectVec(end.target, [30, 0, 30])
    expect(end.position[1]).toBe(EYE_HEIGHT)
  })

  it('keyframes are evenly spaced poses from start to end; fly duration is clamped', () => {
    const frames = cameraKeyframes(L, 5)
    expect(frames).toHaveLength(5)
    expect(frames[0]).toEqual(cameraAt(L, 0))
    expect(frames[4]).toEqual(cameraAt(L, 1))
    expect(cameraKeyframes([], 5)).toEqual([])
    expect(flyDurationMs(15)).toBe(4000)
    expect(flyDurationMs(150)).toBe(10_000)
    expect(flyDurationMs(5000)).toBe(30_000)
  })

  it('overviewPose frames the whole route from above', () => {
    const pose = overviewPose(L)!
    expect(pose.target).toEqual([15, 0, 15])
    expect(pose.position[1]).toBeGreaterThanOrEqual(30)
    expect(overviewPose([])).toBeNull()
  })

  it('routePanoramaStops: panoramas on the route in walking order, once each', () => {
    const p = (pano_id: string, node_id: string) => ({ pano_id, node_id, heading: 0, pitch: 0, kind: 'street_view' as const, verified_on: null })
    const panos = [p('P3', 'c'), p('P1', 'a'), p('P1', 'a'), p('PX', 'elsewhere'), p('P2', 'b')]
    expect(routePanoramaStops(['a', 'b', 'c'], panos).map((s) => s.pano_id)).toEqual(['P1', 'P2', 'P3'])
    expect(routePanoramaStops(['a'], [])).toEqual([])
  })

  it('liftPolyline interpolates height by length', () => {
    expect(liftPolyline([[0, 0], [3, 4], [3, 14]], 0, 15)).toEqual([[0, 0, 0], [3, 5, 4], [3, 15, 14]])
  })
})

describe('Google Maps link-outs', () => {
  const geo = chennai.geo_reference!
  it('the anchor maps to the station coordinate; 50 m along plan-right is 50 m east on a north-up plan', () => {
    expect(planToLatLon(geo, chennai.map, [geo.anchor.x, geo.anchor.y])).toEqual({ lat: 13.0825, lon: 80.275 })
    const fifty = 50 / (chennai.map.width_px * geo.metres_per_pixel)
    const east = planToLatLon(geo, chennai.map, [geo.anchor.x + fifty, geo.anchor.y])
    expect(east.lat).toBe(13.0825)
    const metresEast = ((east.lon - 80.275) * Math.PI / 180) * 6_371_000 * Math.cos(13.0825 * Math.PI / 180)
    expect(metresEast).toBeCloseTo(50, 0)
  })

  it('rotation: with plan-up 90° clockwise from north, plan-right points south (inverse of the panoramas CLI)', () => {
    const fifty = 50 / (chennai.map.width_px * geo.metres_per_pixel)
    const p = planToLatLon({ ...geo, rotation_deg: 90 }, chennai.map, [geo.anchor.x + fifty, geo.anchor.y])
    expect(p.lon).toBeCloseTo(80.275, 6)
    expect(((p.lat - 13.0825) * Math.PI / 180) * 6_371_000).toBeCloseTo(-50, 0)
  })

  it('panorama and place links use Maps URLs with no key', () => {
    const link = panoramaLink({ pano_id: 'abc DEF', node_id: 'x', heading: 90, pitch: -5, kind: 'street_view', verified_on: null })
    expect(link).toBe('https://www.google.com/maps/@?api=1&map_action=pano&pano=abc+DEF&heading=90&pitch=-5')
    expect(placeLink(chennai)).toEqual({ url: 'https://www.google.com/maps/search/?api=1&query=13.0825%2C80.275', approximate_m: 50 })
    expect(placeLink(twoLevel())).toEqual({ url: 'https://www.google.com/maps/search/?api=1&query=Test+Station+railway+station', approximate_m: null })
    expect(link).not.toMatch(/key=/)
  })
})

function expectVec(actual: Vec3, expected: Vec3) {
  actual.forEach((v, i) => expect(v).toBeCloseTo(expected[i], 6))
}

function round(v: number) {
  return Math.round(v * 1000) / 1000
}
