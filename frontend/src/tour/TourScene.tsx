// The 3D canvas of the virtual tour (three.js through @react-three/fiber). Loaded lazily, only when WebGL exists.
// It draws exactly what buildSceneSpec() describes: the plan image as the floor, traced areas extruded to their
// (nominal) heights, node pins, pathways and the route as a glowing path. With an OpenStreetMap world the plan floor
// gives way to WorldLayer (buildings, platforms, canopies, rails and the heritage model). Street View imagery is
// never drawn here.
import { Html, OrbitControls } from '@react-three/drei'
import { Canvas, useFrame, useThree, type ThreeEvent } from '@react-three/fiber'
import { useEffect, useMemo, useRef, useState, type ElementRef, type MutableRefObject } from 'react'
import * as THREE from 'three'
import { cameraAt, flyDurationMs, pathLength, type CameraPose } from './cameraPath'
import { PIN_HEIGHT, type SceneArea, type SceneEdge, type ScenePin, type SceneSpec, type Vec3 } from './sceneSpec'
import WorldLayer from './WorldLayer'
import { frameBounds } from './worldSpec'

type OrbitControlsImpl = ElementRef<typeof OrbitControls>

export interface TourSceneProps {
  spec: SceneSpec
  /** Absolute URL of the plan image used as the floor texture. */
  floorUrl: string
  /** Absolute URL of the heritage .glb when the scene has a world; null draws its footprint instead. */
  modelUrl?: string | null
  /** The route glows without pulsing when the user prefers reduced motion. */
  reducedMotion?: boolean
  /** 'all', or the one level to show. */
  visibleLevel: number | 'all'
  selectedId: string | null
  onSelect: (id: string) => void
  /** Labels shown above the route's start and destination pins. */
  markers: { id: string; text: string }[]
  /** The route in world coordinates, or null. */
  path: Vec3[] | null
  /** Runs the fly-through along `path`; never set when the user prefers reduced motion. */
  flying: boolean
  onFlyEnd: () => void
  /** A pose to jump to without animation (route overview, motion-free route steps, reset). */
  pose: CameraPose | null
  /** Accessible description of the canvas. */
  label: string
}

const PIN_COLOR: Record<string, string> = {
  entrance: '#10b981', platform: '#1a56db', platform_access: '#1a56db', toilet: '#f59e0b', ticket_counter: '#f59e0b',
  information_desk: '#f59e0b', shop: '#f59e0b',
}
const ROUTE_COLOR = '#1a56db'
const ROUTE_GLOW = '#3b82f6'
const ROUTE_RADIUS = 1

export default function TourScene(props: TourSceneProps) {
  const { spec, label } = props
  return (
    <div role="img" aria-label={label} className="h-full w-full">
      <Canvas camera={{ position: spec.camera.position, fov: 50, near: 0.5, far: spec.radius * 12 }} dpr={[1, 2]}
        gl={{ antialias: true, preserveDrawingBuffer: false }}>
        <color attach="background" args={['#eef2f7']} />
        <ambientLight intensity={0.75} />
        <directionalLight position={[spec.radius, spec.radius * 1.5, spec.radius * 0.5]} intensity={0.9} />
        <SceneContent {...props} />
      </Canvas>
    </div>
  )
}

function SceneContent({ spec, floorUrl, modelUrl = null, reducedMotion = false, visibleLevel, selectedId, onSelect, markers, path, flying, onFlyEnd, pose }: TourSceneProps) {
  const controls = useRef<OrbitControlsImpl | null>(null)
  const shown = (level: number) => visibleLevel === 'all' || visibleLevel === level
  const markerText = new Map(markers.map((mk) => [mk.id, mk.text]))
  return (
    <>
      {spec.world ? <WorldLayer world={spec.world} modelUrl={modelUrl} /> : shown(spec.floor.level) && <Floor spec={spec} url={floorUrl} />}
      {spec.areas.filter((a) => shown(a.level)).map((a) => <AreaMesh key={a.id} area={a} />)}
      {spec.edges.filter((e) => shown(e.level)).map((e) => <EdgeLine key={e.id} edge={e} />)}
      {spec.pins.filter((p) => shown(p.level)).map((p) => (
        <Pin key={p.id} pin={p} selected={p.id === selectedId} marker={markerText.get(p.id)} onSelect={onSelect} />
      ))}
      {path && path.length > 1 && <RouteTube path={path} pulse={!reducedMotion} />}
      <CameraRig controls={controls} spec={spec} path={path} flying={flying} onFlyEnd={onFlyEnd} pose={pose} />
      <OrbitControls ref={controls} makeDefault enabled={!flying} target={spec.camera.target}
        maxPolarAngle={Math.PI / 2.05} minDistance={5} maxDistance={spec.radius * 4} />
    </>
  )
}

/** The plan image laid flat at its level. Loaded without Suspense so a failed load leaves a plain floor. */
function Floor({ spec, url }: { spec: SceneSpec; url: string }) {
  const [texture, setTexture] = useState<THREE.Texture | null>(null)
  useEffect(() => {
    let alive = true
    let loadedTexture: THREE.Texture | null = null
    new THREE.TextureLoader().load(url, (t) => {
      t.colorSpace = THREE.SRGBColorSpace
      loadedTexture = t
      if (alive) setTexture(t)
      else t.dispose()
    }, undefined, () => undefined)
    return () => { alive = false; loadedTexture?.dispose() }
  }, [url])
  const { floor } = spec
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, floor.y, 0]}>
      <planeGeometry args={[floor.width, floor.depth]} />
      {/* Keyed so the material is rebuilt with a map: three.js does not recompile a material when a map is added. */}
      <meshStandardMaterial key={texture ? 'plan' : 'plain'} map={texture} color={texture ? '#ffffff' : '#dfe5ee'} />
    </mesh>
  )
}

function AreaMesh({ area }: { area: SceneArea }) {
  const geometry = useMemo(() => {
    // Shape space (x, y) maps to world (x, -z) after the -90° turn about x; extrusion depth becomes height.
    const shape = new THREE.Shape(area.outline.map(([x, z]) => new THREE.Vector2(x, -z)))
    return new THREE.ExtrudeGeometry(shape, { depth: Math.max(area.height, 0.02), bevelEnabled: false })
  }, [area])
  useEffect(() => () => geometry.dispose(), [geometry])
  return (
    <mesh geometry={geometry} rotation={[-Math.PI / 2, 0, 0]} position={[0, area.y + 0.01, 0]}>
      <meshStandardMaterial color={area.color} transparent={area.opacity < 1} opacity={area.opacity}
        depthWrite={area.opacity >= 0.5} />
    </mesh>
  )
}

function EdgeLine({ edge }: { edge: SceneEdge }) {
  const line = useMemo(() => {
    const geometry = new THREE.BufferGeometry().setFromPoints(edge.points.map((p) => new THREE.Vector3(...p)))
    const material = new THREE.LineBasicMaterial({ color: edge.pathType === 'stairs' ? '#9a3412' : '#64748b' })
    return new THREE.Line(geometry, material)
  }, [edge])
  useEffect(() => () => {
    line.geometry.dispose()
    ;(line.material as THREE.Material).dispose()
  }, [line])
  return <primitive object={line} />
}

function Pin({ pin, selected, marker, onSelect }: { pin: ScenePin; selected: boolean; marker?: string; onSelect: (id: string) => void }) {
  const minor = pin.type === 'junction' || pin.type === 'concourse'
  const color = PIN_COLOR[pin.type] ?? '#475569'
  const r = minor ? 0.9 : 1.6
  const click = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation()
    onSelect(pin.id)
  }
  const label = selected ? pin.name : marker ? `${marker}: ${pin.name}` : null
  return (
    <group position={pin.position}>
      <mesh position={[0, -PIN_HEIGHT / 2, 0]}>
        <cylinderGeometry args={[0.12, 0.12, PIN_HEIGHT, 6]} />
        <meshBasicMaterial color={color} />
      </mesh>
      <mesh onClick={click} scale={selected ? 1.5 : 1}>
        <sphereGeometry args={[r, 16, 12]} />
        <meshStandardMaterial color={selected ? '#dc2626' : color} />
      </mesh>
      {label && (
        <Html center position={[0, r * 2.2, 0]} zIndexRange={[10, 0]} style={{ pointerEvents: 'none' }}>
          <span className="whitespace-nowrap rounded-md bg-white/95 px-1.5 py-0.5 text-[11px] font-bold text-brand-900 shadow">{label}</span>
        </Html>
      )}
    </group>
  )
}

/** The route as a glowing path: emissive, a little wider than a pathway, its glow pulsing unless motion is reduced. */
function RouteTube({ path, pulse }: { path: Vec3[]; pulse: boolean }) {
  const material = useRef<THREE.MeshStandardMaterial | null>(null)
  const geometry = useMemo(() => {
    const curve = new THREE.CurvePath<THREE.Vector3>()
    for (let i = 1; i < path.length; i += 1) {
      curve.add(new THREE.LineCurve3(new THREE.Vector3(...path[i - 1]), new THREE.Vector3(...path[i])))
    }
    return new THREE.TubeGeometry(curve, Math.max(64, path.length * 8), ROUTE_RADIUS, 8, false)
  }, [path])
  useEffect(() => () => geometry.dispose(), [geometry])
  useEffect(() => { if (!pulse && material.current) material.current.emissiveIntensity = 0.9 }, [pulse])
  useFrame(({ clock }) => {
    if (pulse && material.current) material.current.emissiveIntensity = 0.75 + 0.45 * Math.sin(clock.elapsedTime * 3)
  })
  return (
    <mesh geometry={geometry} name="route">
      <meshStandardMaterial ref={material} color={ROUTE_COLOR} emissive={ROUTE_GLOW} emissiveIntensity={0.9} toneMapped={false} />
    </mesh>
  )
}

/** Fly-through along the route, and jumps to a requested pose. Both leave the orbit controls aimed at the target. */
function CameraRig({ controls, spec, path, flying, onFlyEnd, pose }: {
  controls: MutableRefObject<OrbitControlsImpl | null>; spec: SceneSpec; path: Vec3[] | null; flying: boolean
  onFlyEnd: () => void; pose: CameraPose | null
}) {
  const camera = useThree((s) => s.camera)
  const size = useThree((s) => s.size)
  const progress = useRef(0)
  const ended = useRef(false)
  const duration = useMemo(() => (path ? flyDurationMs(pathLength(path)) : 0), [path])

  const apply = (p: CameraPose) => {
    camera.position.set(...p.position)
    camera.lookAt(...p.target)
    controls.current?.target.set(...p.target)
    controls.current?.update()
  }

  useEffect(() => {
    progress.current = 0
    ended.current = false
  }, [flying, path])

  useEffect(() => {
    if (pose) apply(pose)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pose])

  useEffect(() => {
    // A world is framed for this canvas's own aspect (spec.camera assumes a square one).
    if (!pose && !flying) apply(spec.world ? frameBounds(spec.world.bounds, size.width / Math.max(1, size.height)) : spec.camera)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spec])

  useFrame((_, delta) => {
    if (!flying || !path || path.length < 2 || ended.current) return
    progress.current = Math.min(1, progress.current + (delta * 1000) / duration)
    apply(cameraAt(path, progress.current))
    if (progress.current >= 1) {
      ended.current = true
      onFlyEnd()
    }
  })
  return null
}
