// Draws worldSpec's OpenStreetMap world (© OpenStreetMap contributors, credited by the screen) inside the tour
// canvas, in few draw calls: the ground, all buildings merged into one mesh, all platforms in one, the canopies in
// one with their posts as one instanced mesh, and the rails as one set of line segments. The heritage building is
// the plain .glb (GLTFLoader, loaded on demand, no Draco), placed at its footprint's area centroid; if it cannot be
// loaded the footprint is extruded to 18 m instead.
import { Html } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js'
import type { Vec2 } from './sceneSpec'
import {
  HERITAGE_FALLBACK_HEIGHT_M, LABEL_DISTANCE_M, PLATFORM_HEIGHT_M, polygonCentroid, ROOF_Y_M, shownPlatformLabels, declutterLabels, type LabelRect, type WorldBuilding, type WorldSpec,
} from './worldSpec'

const COLOR = { building: '#cbd2dc', platform: '#e7e2d6', rail: '#4b5563', roof: '#9fb3c8', ground: '#eef1f4', heritage: '#7a1f1f' }
const GROUND_MARGIN_M = 80
const RAIL_Y = 0.12
const POST_SIZE_M = 0.35
const LABEL_INSET_M = 30
const ORIGIN = new THREE.Vector3()

export interface WorldLayerProps {
  world: WorldSpec
  /** Absolute URL of the heritage .glb, or null (then the footprint is extruded). */
  modelUrl: string | null
  /** Tooltip for labels whose number comes from the station plan. */
  platformFromPlan?: string
  /** Pin labels currently drawn (start, destination, selected place): world position of the label and its text. */
  pinLabels?: { position: [number, number, number]; text: string }[]
}

const THROTTLE_S = 0.15
/** Approximate on-screen size of the HTML labels (text-[11px] bold pins, text-[10px] bold platform labels). */
const pinRect = (x: number, y: number, text: string): LabelRect => ({ x, y, w: text.length * 6.4 + 12, h: 22 })
const platformRect = (x: number, y: number, text: string): LabelRect => ({ x, y, w: text.length * 5.8 + 8, h: 18 })

export default function WorldLayer({ world, modelUrl, platformFromPlan, pinLabels = [] }: WorldLayerProps) {
  const { minX, maxX, minZ, maxZ } = world.bounds
  // Platform labels sit at the station end of each platform (towards the heritage building), where the route arrives.
  const toward = useMemo<Vec2>(() => (world.heritage ? polygonCentroid(world.heritage.outline) : [0, 0]), [world.heritage])
  // Which platform labels are drawn: those the zoom allows (R16/R19) that are not within 44 px of a pin label or of
  // another platform label (R20). Worked out at most every THROTTLE_S and stored only when the set changes.
  const [visible, setVisible] = useState<ReadonlySet<number>>(() => new Set())
  const visibleKey = useRef('')
  const lastRun = useRef(-Infinity)
  const points = useMemo(() => world.platforms.map((p) => (p.label ? labelPoint(p.outline, toward) : null)), [world.platforms, toward])
  const pinsRef = useRef(pinLabels)
  pinsRef.current = pinLabels
  useFrame(({ camera, controls, clock, size }) => {
    if (clock.elapsedTime - lastRun.current < THROTTLE_S) return
    lastRun.current = clock.elapsedTime
    const target = (controls as { target?: THREE.Vector3 } | null)?.target ?? ORIGIN
    const close = camera.position.distanceTo(target) <= LABEL_DISTANCE_M
    const allowed = [...shownPlatformLabels(world.platforms, close ? 0 : Infinity)]
    const project = (x: number, y: number, z: number) => {
      const v = new THREE.Vector3(x, y, z).project(camera)
      return v.z < 1 ? { x: (v.x * 0.5 + 0.5) * size.width, y: (-v.y * 0.5 + 0.5) * size.height } : null
    }
    const pins = pinsRef.current.flatMap((p) => {
      const s = project(...p.position)
      return s ? [pinRect(s.x, s.y, p.text)] : []
    })
    const cands = allowed.flatMap((i) => {
      const [x, z] = points[i]!
      const s = project(x, PLATFORM_HEIGHT_M + 1.5, z)
      return s ? [{ i, rect: platformRect(s.x, s.y, world.platforms[i].label!) }] : []
    })
    const keep = declutterLabels(pins, cands.map((c) => c.rect))
    const next = new Set(cands.filter((_, k) => keep.has(k)).map((c) => c.i))
    const key = [...next].join(',')
    if (key !== visibleKey.current) {
      visibleKey.current = key
      setVisible(next)
    }
  })
  const shown = visible
  return (
    <group name="world">
      <mesh name="world-ground" rotation={[-Math.PI / 2, 0, 0]} position={[(minX + maxX) / 2, -0.02, (minZ + maxZ) / 2]}>
        <planeGeometry args={[maxX - minX + GROUND_MARGIN_M * 2, maxZ - minZ + GROUND_MARGIN_M * 2]} />
        <meshStandardMaterial color={COLOR.ground} />
      </mesh>
      <Extruded name="world-buildings" items={world.buildings} y={0} color={COLOR.building} />
      <Extruded name="world-platforms" items={world.platforms.map((p) => ({ outline: p.outline, height: PLATFORM_HEIGHT_M }))} y={0} color={COLOR.platform} />
      <Extruded name="world-roofs" items={world.roofs} y={ROOF_Y_M} color={COLOR.roof} opacity={0.85} />
      <RoofPosts roofs={world.roofs} />
      <Rails rails={world.rails} />
      {world.platforms.map((p, i) => {
        if (!shown.has(i)) return null
        const [x, z] = labelPoint(p.outline, toward)
        return (
          <Html key={`${p.label}-${i}`} center position={[x, PLATFORM_HEIGHT_M + 1.5, z]} zIndexRange={[5, 0]} style={{ pointerEvents: 'none' }}>
            <span title={p.labelSource === 'station_plan' ? platformFromPlan : undefined} className="whitespace-nowrap rounded bg-white/90 px-1 text-[10px] font-bold text-ink-700 shadow">{p.label}</span>
          </Html>
        )
      })}
      {world.heritage && <Heritage outline={world.heritage.outline} url={modelUrl} />}
    </group>
  )
}

/** A point LABEL_INSET_M in from the platform's end nearest `toward` (its centroid when the platform is shorter). */
export function labelPoint(outline: Vec2[], toward: Vec2): Vec2 {
  const centre = polygonCentroid(outline)
  const end = outline.reduce((best, p) => (Math.hypot(p[0] - toward[0], p[1] - toward[1]) < Math.hypot(best[0] - toward[0], best[1] - toward[1]) ? p : best))
  const d = Math.hypot(centre[0] - end[0], centre[1] - end[1])
  if (d <= LABEL_INSET_M) return centre
  const f = LABEL_INSET_M / d
  return [end[0] + (centre[0] - end[0]) * f, end[1] + (centre[1] - end[1]) * f]
}

/** A ring on the floor extruded `height` up from `y` (shape (x, -z), turned -90° about x). */
export function extrude(outline: Vec2[], height: number, y: number): THREE.BufferGeometry {
  const shape = new THREE.Shape(outline.map(([x, z]) => new THREE.Vector2(x, -z)))
  const g = new THREE.ExtrudeGeometry(shape, { depth: Math.max(height, 0.02), bevelEnabled: false })
  g.rotateX(-Math.PI / 2)
  g.translate(0, y, 0)
  return g
}

function Extruded({ name, items, y, color, opacity = 1 }: { name: string; items: WorldBuilding[]; y: number; color: string; opacity?: number }) {
  const geometry = useMemo(() => {
    const parts = items.filter((it) => it.outline.length > 2).map((it) => extrude(it.outline, it.height, y))
    if (parts.length === 0) return null
    const merged = mergeGeometries(parts, false)
    parts.forEach((p) => p.dispose())
    return merged
  }, [items, y])
  useEffect(() => () => geometry?.dispose(), [geometry])
  if (!geometry) return null
  return (
    <mesh name={name} geometry={geometry}>
      <meshStandardMaterial color={color} transparent={opacity < 1} opacity={opacity} depthWrite={opacity >= 1} />
    </mesh>
  )
}

/** One post under each canopy corner, all in one instanced mesh. */
function RoofPosts({ roofs }: { roofs: WorldBuilding[] }) {
  const mesh = useMemo(() => {
    const corners = roofs.flatMap((r) => r.outline)
    if (corners.length === 0) return null
    const geometry = new THREE.BoxGeometry(POST_SIZE_M, ROOF_Y_M, POST_SIZE_M)
    const material = new THREE.MeshStandardMaterial({ color: COLOR.roof })
    const posts = new THREE.InstancedMesh(geometry, material, corners.length)
    const m = new THREE.Matrix4()
    corners.forEach(([x, z], i) => posts.setMatrixAt(i, m.makeTranslation(x, ROOF_Y_M / 2, z)))
    posts.instanceMatrix.needsUpdate = true
    posts.name = 'world-roof-posts'
    return posts
  }, [roofs])
  useEffect(() => () => {
    mesh?.geometry.dispose()
    ;(mesh?.material as THREE.Material | undefined)?.dispose()
    mesh?.dispose()
  }, [mesh])
  return mesh ? <primitive object={mesh} /> : null
}

function Rails({ rails }: { rails: Vec2[][] }) {
  const lines = useMemo(() => {
    const pos: number[] = []
    for (const line of rails) {
      for (let i = 1; i < line.length; i += 1) pos.push(line[i - 1][0], RAIL_Y, line[i - 1][1], line[i][0], RAIL_Y, line[i][1])
    }
    if (pos.length === 0) return null
    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
    const segments = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color: COLOR.rail }))
    segments.name = 'world-rails'
    return segments
  }, [rails])
  useEffect(() => () => {
    lines?.geometry.dispose()
    ;(lines?.material as THREE.Material | undefined)?.dispose()
  }, [lines])
  return lines ? <primitive object={lines} /> : null
}

type ModelState = { status: 'loading' } | { status: 'ready'; scene: THREE.Group } | { status: 'failed' }

/** The heritage .glb at the footprint's area centroid (glb +X east, -Z north, +Y up, metres), or the fallback. */
function Heritage({ outline, url }: { outline: Vec2[]; url: string | null }) {
  const [model, setModel] = useState<ModelState>(url ? { status: 'loading' } : { status: 'failed' })
  useEffect(() => {
    if (!url) {
      setModel({ status: 'failed' })
      return undefined
    }
    setModel({ status: 'loading' })
    let alive = true
    let loaded: THREE.Group | null = null
    const fail = () => { if (alive) setModel({ status: 'failed' }) }
    import('three/examples/jsm/loaders/GLTFLoader.js').then(({ GLTFLoader }) => {
      new GLTFLoader().load(url, (gltf) => {
        loaded = gltf.scene
        if (alive) setModel({ status: 'ready', scene: gltf.scene })
        else disposeTree(gltf.scene)
      }, undefined, fail)
    }, fail)
    return () => {
      alive = false
      if (loaded) disposeTree(loaded)
    }
  }, [url])
  const [cx, cz] = useMemo(() => polygonCentroid(outline), [outline])
  if (model.status === 'ready') return <primitive object={model.scene} position={[cx, 0, cz]} />
  if (model.status === 'failed') return <HeritageFallback outline={outline} />
  return null
}

function HeritageFallback({ outline }: { outline: Vec2[] }) {
  const geometry = useMemo(() => extrude(outline, HERITAGE_FALLBACK_HEIGHT_M, 0), [outline])
  useEffect(() => () => geometry.dispose(), [geometry])
  return (
    <mesh name="heritage-fallback" geometry={geometry}>
      <meshStandardMaterial color={COLOR.heritage} />
    </mesh>
  )
}

function disposeTree(root: THREE.Object3D) {
  root.traverse((o) => {
    const mesh = o as THREE.Mesh
    if (!mesh.isMesh) return
    mesh.geometry.dispose()
    for (const m of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) m.dispose()
  })
}
