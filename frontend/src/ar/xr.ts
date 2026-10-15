/// <reference types="webxr" />
// Progressive enhancement: on browsers with WebXR immersive-ar + hit-test (Android Chrome), the arrow is drawn on the
// floor and held in place by the device's 6DoF tracking. Only started from a button shown when
// `navigator.xr.isSessionSupported('immersive-ar')` is true. three.js is imported dynamically, so it never loads for
// the default camera-overlay path. The safety banner and an exit button stay on screen through `dom-overlay`.
//
// WebXR gives no camera frames without the experimental raw-camera-access feature, so the floor mode uses the fix
// taken before it started; leaving it returns to the camera overlay, where re-localisation continues.

/** Yaw of the viewer's forward direction (-Z) from a pose quaternion, clockwise from the XR world's -Z, degrees. */
export function forwardYawDeg(x: number, y: number, z: number, w: number): number {
  // Forward vector = q · (0, 0, -1) · q⁻¹
  const fx = -2 * (x * z + w * y)
  const fz = -(1 - 2 * (x * x + y * y))
  return ((Math.atan2(fx, -fz) * 180) / Math.PI + 360) % 360
}

/** Unit direction on the floor (XR world, y up) for a clockwise yaw from -Z. */
export function floorDirection(yawDeg: number): [number, number, number] {
  const r = (yawDeg * Math.PI) / 180
  return [Math.sin(r), 0, -Math.cos(r)]
}

export interface FloorArrowsOptions {
  /** Arrow angle relative to the camera's forward direction when the session starts (0 = ahead, + = right). */
  arrowAngleDeg: number
  /** Element kept visible over the camera (safety banner, exit button). */
  overlayRoot: HTMLElement
  onEnd: () => void
}

/** Starts the immersive session; resolves to a function that ends it. Rejects if the session cannot start. */
export async function startFloorArrows({ arrowAngleDeg, overlayRoot, onEnd }: FloorArrowsOptions): Promise<() => void> {
  const xr = navigator.xr
  if (!xr) throw new Error('webxr_unavailable')
  const THREE = await import('three')
  const session = await xr.requestSession('immersive-ar', {
    requiredFeatures: ['hit-test'], optionalFeatures: ['dom-overlay'], domOverlay: { root: overlayRoot },
  })
  const canvas = document.createElement('canvas')
  const gl = canvas.getContext('webgl2', { xrCompatible: true }) as WebGL2RenderingContext | null
  const renderer = new THREE.WebGLRenderer({ canvas, context: gl ?? undefined, alpha: true })
  renderer.xr.enabled = true
  renderer.xr.setReferenceSpaceType('local')
  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera()

  // A flat arrow lying on the floor, pointing along its local -Z.
  const shape = new THREE.Shape()
  shape.moveTo(0, -0.45).lineTo(0.22, -0.1).lineTo(0.08, -0.1).lineTo(0.08, 0.3).lineTo(-0.08, 0.3)
    .lineTo(-0.08, -0.1).lineTo(-0.22, -0.1).lineTo(0, -0.45)
  const arrow = new THREE.Mesh(new THREE.ShapeGeometry(shape),
    new THREE.MeshBasicMaterial({ color: 0x1d4ed8, transparent: true, opacity: 0.85, side: THREE.DoubleSide }))
  arrow.rotation.x = -Math.PI / 2 // lie flat: local -Y of the shape becomes world -Z
  const holder = new THREE.Group()
  holder.add(arrow)
  holder.visible = false
  scene.add(holder)

  await renderer.xr.setSession(session as unknown as Parameters<typeof renderer.xr.setSession>[0])
  const viewerSpace = await session.requestReferenceSpace('viewer')
  const hitSource = await session.requestHitTestSource?.({ space: viewerSpace })
  let worldYaw: number | null = null
  let ended = false

  renderer.setAnimationLoop((_t: number, frame?: XRFrame) => {
    if (!frame) return
    const space = renderer.xr.getReferenceSpace()
    if (!space) return
    if (worldYaw === null) {
      const pose = frame.getViewerPose(space)
      if (pose) {
        const q = pose.transform.orientation
        worldYaw = (forwardYawDeg(q.x, q.y, q.z, q.w) + arrowAngleDeg + 360) % 360
      }
    }
    const hit = hitSource ? frame.getHitTestResults(hitSource)[0] : undefined
    const hitPose = hit?.getPose(space)
    if (hitPose && worldYaw !== null) {
      const p = hitPose.transform.position
      holder.position.set(p.x, p.y + 0.01, p.z)
      const [dx, , dz] = floorDirection(worldYaw)
      holder.rotation.y = Math.atan2(-dx, -dz) // rotate local -Z onto the target direction
      holder.visible = true
    }
    renderer.render(scene, camera)
  })

  const cleanup = () => {
    if (ended) return
    ended = true
    renderer.setAnimationLoop(null)
    hitSource?.cancel()
    renderer.dispose()
    onEnd()
  }
  session.addEventListener('end', cleanup)
  return () => {
    if (!ended) session.end().catch(cleanup)
  }
}
