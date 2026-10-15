// Browser capabilities for AR guidance: secure context, a camera, motion permission (iOS) and the rear camera
// stream. Lives in the lazy AR chunk; StationNavigation imports it dynamically only for a station with AR on.
import type { FallbackReason } from './machine'

export type Support = { ok: true } | { ok: false; reason: Extract<FallbackReason, 'insecure' | 'no_camera'> }

/** Whether AR can be offered at all: a secure context and at least one camera. Never prompts for permission. */
export async function checkArSupport(): Promise<Support> {
  if (typeof window === 'undefined' || !window.isSecureContext) return { ok: false, reason: 'insecure' }
  const md = navigator.mediaDevices
  if (!md || typeof md.getUserMedia !== 'function') return { ok: false, reason: 'no_camera' }
  if (typeof md.enumerateDevices === 'function') {
    try {
      const devices = await md.enumerateDevices()
      // Before permission some browsers list kinds without labels; a browser that lists nothing is given a chance.
      if (devices.length && !devices.some((d) => d.kind === 'videoinput')) return { ok: false, reason: 'no_camera' }
    } catch {
      /* treat as unknown: getUserMedia will tell */
    }
  }
  return { ok: true }
}

type PermissionApi = { requestPermission?: () => Promise<'granted' | 'denied'> }

/**
 * iOS 13+ needs DeviceOrientationEvent.requestPermission() from a user gesture: call this first in the click
 * handler. Resolves true when motion events may arrive (granted, or no permission API), false when refused.
 */
export function requestMotionPermission(): Promise<boolean> {
  if (typeof window === 'undefined' || typeof window.DeviceOrientationEvent === 'undefined') return Promise.resolve(false)
  const api = window.DeviceOrientationEvent as unknown as PermissionApi
  if (typeof api.requestPermission !== 'function') return Promise.resolve(true)
  return api.requestPermission().then((r) => r === 'granted', () => false)
}

export type CameraResult = { ok: true; stream: MediaStream } | { ok: false; reason: Extract<FallbackReason, 'camera_denied' | 'no_camera' | 'camera_failed' | 'insecure'> }

/** The rear camera, video only. */
export async function openRearCamera(): Promise<CameraResult> {
  const md = typeof navigator !== 'undefined' ? navigator.mediaDevices : undefined
  if (!md?.getUserMedia) return { ok: false, reason: 'no_camera' }
  try {
    const stream = await md.getUserMedia({
      audio: false,
      video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } },
    })
    return { ok: true, stream }
  } catch (e) {
    const name = e instanceof Error ? e.name : ''
    if (name === 'NotAllowedError' || name === 'PermissionDeniedError') return { ok: false, reason: 'camera_denied' }
    if (name === 'NotFoundError' || name === 'OverconstrainedError' || name === 'DevicesNotFoundError') return { ok: false, reason: 'no_camera' }
    if (name === 'SecurityError') return { ok: false, reason: 'insecure' }
    return { ok: false, reason: 'camera_failed' }
  }
}

export function stopStream(stream: MediaStream | null): void {
  stream?.getTracks().forEach((t) => t.stop())
}

/** WebXR immersive-ar (Android Chrome). False on any error or when the API is missing. */
export async function immersiveArSupported(): Promise<boolean> {
  const xr = (navigator as Navigator & { xr?: { isSessionSupported(mode: string): Promise<boolean> } }).xr
  if (!xr || typeof xr.isSessionSupported !== 'function') return false
  try {
    return (await xr.isSessionSupported('immersive-ar')) === true
  } catch {
    return false
  }
}
