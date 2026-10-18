// The OpenStreetMap world of the 3D tour as pure data: plan → world transform, heights, labels, bounds, framing.
// The alignment values are Chennai Central's committed metadata.json world_alignment; the features are copied from
// its osm.json (© OpenStreetMap contributors, ODbL) or made up where a test needs a particular tag.
import * as THREE from 'three'
import type { StationTour } from '../api/types'
import { buildSceneSpec } from '../tour/sceneSpec'
import {
  buildWorldSpec, declutterLabels, FOCUS_MARGIN_M, frameBounds, LABEL_DISTANCE_M, planToWorld, polygonCentroid, shownPlatformLabels, type WorldBounds,
} from '../tour/worldSpec'
import tourJson from './data/chennai_central_tour.json'
import { CHENNAI_ALIGNMENT, chennaiWorld, feature, HERITAGE, PLATFORM_5_6, square } from './worldFixture'

const chennai = tourJson as unknown as StationTour

describe('planToWorld', () => {
  it('planToWorld applies similarity', () => {
    // Plan (x right, y down) enters as (x, -y); the result is three.js (x = east, z = -north).
    const a = { ...CHENNAI_ALIGNMENT, scale: 2, rotation_deg: 90, tx: 10, ty: 20 }
    const [x, z] = planToWorld(a, [3, 4]) // (3, -4) → 2·R90·(3, -4) + (10, 20) = (8 + 10, 6 + 20) = (18, 26) east/north
    expect(x).toBeCloseTo(18, 9)
    expect(z).toBeCloseTo(-26, 9)
  })

  it('matches the Python Similarity.apply on a committed Chennai Central pair (to 0.01 m)', () => {
    // Expected value computed once with the backend code (cd backend && uv run python -c ...):
    //   head, _, _ = platform_axis_points(metres(platform_10_area), polygon_centroid(metres(building)))  # plan (x, -y)
    //   Similarity(0.855, -80.104, 11.27, 139.93, 0).apply(*head)
    // head = (111.44094478412534, -69.25408633814448) → (east, north) = (-30.686047241024088, 35.88942653667213).
    // The fit was fed plan (x, -y), so the plan point here is (x, y) = (111.4409..., 69.2540...) and three.js z = -north.
    const [x, z] = planToWorld(CHENNAI_ALIGNMENT, [111.44094478412534, 69.25408633814448])
    expect(Math.abs(x - -30.686047241024088)).toBeLessThan(0.01)
    expect(Math.abs(z - -35.88942653667213)).toBeLessThan(0.01)
  })

  it('translation alignments are applied the same way (scale 1, rotation 0)', () => {
    const a = { ...CHENNAI_ALIGNMENT, method: 'translation', scale: 1, rotation_deg: 0, tx: 5, ty: -5 }
    expect(planToWorld(a, [1, 2])).toEqual([6, 7]) // (1, -2) + (5, -5) = (6, -7) east/north
  })
})

describe('buildWorldSpec', () => {
  const spec = buildWorldSpec(chennaiWorld())!

  it('building height from levels', () => {
    expect(spec.buildings.find((b) => b.outline[0][0] === 95)!.height).toBe(16) // 5 levels × 3.2, wins over height_m
  })

  it('default building height 9', () => {
    expect(spec.buildings.find((b) => b.outline[0][0] === -155)!.height).toBe(9)
    const tagged = buildWorldSpec(chennaiWorld([HERITAGE, feature('b/h', 'building', square(0, 50), { height_m: 12.5 })]))!
    expect(tagged.buildings[0].height).toBe(12.5)
  })

  it('platform labels: plan numbers on fitted islands; OSM refs only when the plan numbers nothing', () => {
    const suburban = spec.platforms.find((p) => p.outline.some(([x]) => x === 60))!
    expect(suburban).toMatchObject({ label: null, labelSource: null }) // R18: plan numbers exist, so OSM refs are hidden
    const unnamed = spec.platforms.find((p) => p.outline.some(([x]) => x === 120))!
    expect(unnamed).toMatchObject({ label: null, labelSource: null })
    // An OSM ref naming a number the traced plan puts on another island is not shown (it would contradict it).
    const clash = buildWorldSpec(chennaiWorld([HERITAGE, PLATFORM_5_6, feature('p/9-10', 'platform', [[60, -60], [80, -60], [80, 0], [60, 0]], { ref: '9;10' })]))!
    expect(clash.platforms.find((p) => p.outline.some(([x]) => x === 60))).toMatchObject({ label: null, labelSource: null })
    // An unfitted platform whose ref ("2;3") is not a plan number is still hidden while traced pairs exist (R18).
    const unfitted = buildWorldSpec(chennaiWorld([HERITAGE, PLATFORM_5_6, feature('p/2-3', 'platform', [[60, -60], [80, -60], [80, 0], [60, 0]], { ref: '2;3' })]))!
    expect(unfitted.platforms.find((p) => p.outline.some(([x]) => x === 60))).toMatchObject({ label: null, labelSource: null })
    expect(unfitted.platforms.some((p) => p.labelSource === 'station_plan')).toBe(true)
    // With no traced pairs at all, the OSM ref is the label.
    const noPlan = buildWorldSpec({ ...chennaiWorld([HERITAGE, feature('p/2-3', 'platform', [[60, -60], [80, -60], [80, 0], [60, 0]], { ref: '2;3' })]),
      alignment: { ...CHENNAI_ALIGNMENT, pairs: [], platform_labels: [] } })!
    expect(noPlan.platforms[0]).toMatchObject({ label: '2 · 3', labelSource: 'osm' })
  })

  it('station_plan label for traced platforms', () => {
    // way/397320033 is OSM "5;6"; the traced platforms 9 and 10 were fitted onto it, and the route uses their numbers.
    const traced = spec.platforms.find((p) => p.outline.some(([x, z]) => x === -39.75 && z === -30.29))!
    expect(traced).toMatchObject({ label: '9 · 10', labelSource: 'station_plan' })
  })

  it('world frame: x = east, z = -north; rings stay open; heritage carries the model', () => {
    expect(spec.heritage!.outline[0]).toEqual([-108.32, 21.38])
    expect(spec.heritage!.outline).toHaveLength(13)
    expect(spec.heritage).toMatchObject({ modelUrl: '/api/stations/chennai_central/model.glb', height: 41 })
    expect(spec.attribution).toBe('© OpenStreetMap contributors')
    const [cx, cz] = polygonCentroid(spec.heritage!.outline)
    expect(cx).toBeCloseTo(-50.5967, 3) // backend polygon_centroid of way/214739119: (-50.5967, -12.8022) east/north
    expect(cz).toBeCloseTo(12.8022, 3)
  })

  it('draws only the station complex: no subways, no station polygons, no far buildings; rails clipped to the bounds', () => {
    expect(spec.buildings).toHaveLength(2) // b/five and b/plain; b/far and the bus terminus are not drawn
    expect(spec.roofs).toHaveLength(1)
    expect(spec.rails.length).toBeGreaterThan(0)
    const { minX, maxX, minZ, maxZ } = spec.bounds
    for (const line of spec.rails) {
      for (const [x, z] of line) {
        expect(x).toBeGreaterThanOrEqual(minX - 1e-6)
        expect(x).toBeLessThanOrEqual(maxX + 1e-6)
        expect(z).toBeGreaterThanOrEqual(minZ - 1e-6)
        expect(z).toBeLessThanOrEqual(maxZ + 1e-6)
      }
    }
    // Bounds come from the complex (here clipped to 250 m of the origin), never from the kilometre-long rails.
    expect(maxZ - minZ).toBeLessThanOrEqual(500)
    expect(maxX - minX).toBeLessThanOrEqual(500)
    for (const p of spec.platforms) for (const [, z] of p.outline) expect(z).toBeGreaterThanOrEqual(minZ - 1e-6)
  })

  it('focus (R17): heritage and graph nodes plus a margin, not the platforms, kept inside the bounds', () => {
    const nodes: [number, number][] = [[10.94, -1.96], [-20, -60], [40, 30]]
    const { focus, bounds, heritage } = buildWorldSpec(chennaiWorld(), nodes)!
    const holds = ([x, z]: [number, number]) => x >= focus.minX && x <= focus.maxX && z >= focus.minZ && z <= focus.maxZ
    for (const p of [...heritage!.outline, ...nodes]) expect(holds(p)).toBe(true)
    expect(focus.minX).toBeCloseTo(-108.32 - FOCUS_MARGIN_M, 3)
    expect(focus.maxX).toBeCloseTo(40 + FOCUS_MARGIN_M, 3)
    expect(focus.minZ).toBeCloseTo(-60 - FOCUS_MARGIN_M, 3)
    expect(focus.maxZ).toBeCloseTo(30 + FOCUS_MARGIN_M, 3)
    // The far (north) ends of the platforms are drawn but not framed: way/397320033 runs to the bounds' north edge.
    expect(focus.minZ).toBeGreaterThan(bounds.minZ + 100)
    expect(spec.platforms.some((p) => p.outline.some((pt) => !holds(pt)))).toBe(true)
    // Clamped inside the bounds.
    const wide = buildWorldSpec(chennaiWorld(), [[1000, 1000]])!
    expect(wide.focus.maxX).toBe(wide.bounds.maxX)
    expect(wide.focus.maxZ).toBe(wide.bounds.maxZ)
  })

  it('focus without graph nodes is the heritage building plus the margin, inside the bounds', () => {
    const { focus, bounds } = spec
    expect(focus.minX).toBeGreaterThanOrEqual(bounds.minX)
    expect(focus.maxX).toBeLessThanOrEqual(bounds.maxX)
    expect(focus.minZ).toBeGreaterThanOrEqual(bounds.minZ)
    expect(focus.maxZ).toBeLessThanOrEqual(bounds.maxZ)
    // Heritage ring: x -108.32..4.01, z 1..25.9.
    expect(focus.minX).toBeCloseTo(-108.32 - FOCUS_MARGIN_M, 3)
    expect(focus.maxX).toBeCloseTo(4.01 + FOCUS_MARGIN_M, 3)
    expect(focus.minZ).toBeCloseTo(1 - FOCUS_MARGIN_M, 3)
    expect(focus.maxZ).toBeCloseTo(25.9 + FOCUS_MARGIN_M, 3)
    expect((focus.maxX - focus.minX) * (focus.maxZ - focus.minZ)).toBeLessThan((bounds.maxX - bounds.minX) * (bounds.maxZ - bounds.minZ))
  })

  it('platform labels: all labelled ones when the camera is close, none when far (R19)', () => {
    const traced = spec.platforms.findIndex((p) => p.label === '9 · 10')
    const unlabelled = spec.platforms.findIndex((p) => p.label === null)
    expect(shownPlatformLabels(spec.platforms, LABEL_DISTANCE_M)).toEqual(new Set([traced]))
    expect(shownPlatformLabels(spec.platforms, LABEL_DISTANCE_M).has(unlabelled)).toBe(false) // no label to show
    expect(shownPlatformLabels(spec.platforms, LABEL_DISTANCE_M + 1)).toEqual(new Set())
    expect(shownPlatformLabels(spec.platforms, 800)).toEqual(new Set())
  })

  it('no alignment, no world spec', () => {
    expect(buildWorldSpec({ ...chennaiWorld(), alignment: null })).toBeNull()
    expect(buildWorldSpec(null)).toBeNull()
  })
})

describe('frameBounds', () => {
  it('frameBounds fits a 320x480 canvas', () => {
    const bounds: WorldBounds = { minX: -260, maxX: 250, minZ: -250, maxZ: 40 }
    const pose = frameBounds(bounds, 320 / 480)
    const camera = new THREE.PerspectiveCamera(50, 320 / 480, 0.5, 10_000)
    camera.position.set(...pose.position)
    camera.lookAt(...pose.target)
    camera.updateMatrixWorld()
    for (const x of [bounds.minX, bounds.maxX]) {
      for (const z of [bounds.minZ, bounds.maxZ]) {
        const p = new THREE.Vector3(x, 0, z).project(camera)
        expect(Math.abs(p.x)).toBeLessThanOrEqual(1)
        expect(Math.abs(p.y)).toBeLessThanOrEqual(1)
        expect(p.z).toBeLessThan(1)
      }
    }
    // From the south (+z) at a 55° pitch, so the frontage faces the camera.
    const [dx, dy, dz] = [0, 1, 2].map((i) => pose.position[i] - pose.target[i])
    expect(dx).toBeCloseTo(0, 6)
    expect(dz).toBeGreaterThan(0)
    expect(Math.atan2(dy, dz) * 180 / Math.PI).toBeCloseTo(55, 3)
  })
})

describe('buildSceneSpec', () => {
  it('buildSceneSpec without world', () => {
    // Captured from buildSceneSpec before the world existed (HEAD a94072d); only `world: null` is new.
    const egmore: StationTour = {
      ...chennai, station_id: 'chennai_egmore', station_name: 'Chennai Egmore', routing_enabled: false, ar_enabled: false,
      scale: null, geo_reference: null, levels: [], panoramas_note: null,
      areas: [{ id: 'hall', kind: 'concourse', name: 'Hall', level: 0, height_m: 0.3, polygon: [[0.1, 0.2], [0.5, 0.2], [0.5, 0.6], [0.1, 0.2]], polygon_m: null }],
      map: { url: '/api/stations/chennai_egmore/map', width_px: 1200, height_px: 700 },
    }
    expect(buildSceneSpec(egmore)).toEqual({
      stationId: 'chennai_egmore', frame: { units: 'plan_units', width: 100, depth: 58.333 }, traced: false,
      levels: [{ level: 0, name: null, y: 0, elevationKnown: false }],
      areas: [{ id: 'hall', kind: 'concourse', name: 'Hall', level: 0, y: 0, height: 0.3, outline: [[-40, -17.5], [0, -17.5], [0, 5.833]], color: '#c7d2fe', opacity: 0.85 }],
      pins: [], edges: [], radius: 57.885,
      floor: { url: '/api/stations/chennai_egmore/map', level: 0, y: 0, width: 100, depth: 58.333 },
      camera: { position: [0, 40.519, 34.731], target: [0, 0, 0] },
      world: null,
    })
    expect(buildSceneSpec({ ...egmore, world: null }).world).toBeNull()
  })
})

describe('declutterLabels (R20)', () => {
  const box = (x: number, y: number, w = 40, h = 18) => ({ x, y, w, h })

  it('hides a platform label that overlaps or is within 44 px of a pin label; keeps a far one', () => {
    const pin = box(100, 100, 160, 22)
    expect(declutterLabels([pin], [box(100, 100)])).toEqual(new Set()) // on top of the pin
    expect(declutterLabels([pin], [box(100, 150)])).toEqual(new Set()) // gap 150-100-20 = 30 px
    expect(declutterLabels([pin], [box(100, 200)])).toEqual(new Set([0])) // gap 79 px
  })

  it('the pin wins over a platform label that came first', () => {
    expect(declutterLabels([box(50, 50)], [box(60, 52), box(300, 300)])).toEqual(new Set([1]))
  })

  it('is greedy in the given order: the earlier platform label stays, the later one near it goes', () => {
    const labels = [box(100, 100), box(130, 100), box(260, 100)]
    expect(declutterLabels([], labels)).toEqual(new Set([0, 2]))
    expect(declutterLabels([], [...labels].reverse())).toEqual(new Set([0, 1])) // order decides, deterministically
    expect(declutterLabels([], labels)).toEqual(declutterLabels([], labels))
  })

  it('without pins or neighbours every label stays', () => {
    expect(declutterLabels([], [box(0, 0), box(200, 0)])).toEqual(new Set([0, 1]))
  })
})
