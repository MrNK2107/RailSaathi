// Live camera yaw from the gyroscope (`deviceorientation`, relative). Never `deviceorientationabsolute` and never
// `webkitCompassHeading`: guidance uses only the change since the last fix, so magnetic interference cannot move it.
import { useEffect, useRef, useState } from 'react'
import { cameraYawDeg } from './geometry'

/** Returns the latest yaw (degrees, arbitrary zero) and a ref for reading it synchronously at fix time. */
export function useCameraYaw(enabled: boolean) {
  const ref = useRef<number | null>(null)
  const [yaw, setYaw] = useState<number | null>(null)

  useEffect(() => {
    if (!enabled || typeof window === 'undefined') return undefined
    let frame = 0
    const onOrientation = (e: DeviceOrientationEvent) => {
      if (e.absolute) return // relative rotation only
      ref.current = cameraYawDeg(e.alpha, e.beta, e.gamma) ?? ref.current
      if (!frame) {
        frame = requestAnimationFrame(() => {
          frame = 0
          setYaw(ref.current)
        })
      }
    }
    window.addEventListener('deviceorientation', onOrientation)
    return () => {
      window.removeEventListener('deviceorientation', onOrientation)
      if (frame) cancelAnimationFrame(frame)
    }
  }, [enabled])

  return { yaw, yawRef: ref }
}
