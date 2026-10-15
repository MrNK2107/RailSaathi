// Device capabilities the tour adapts to: WebGL (else the 2D plan) and the reduced-motion preference (else the
// route fly-through animates).
import { useEffect, useState } from 'react'

/** True when the browser can create a WebGL context. Never throws; false in test environments without WebGL. */
export function hasWebGL(): boolean {
  try {
    if (typeof window === 'undefined' || typeof window.WebGLRenderingContext === 'undefined') return false
    const canvas = document.createElement('canvas')
    return !!(canvas.getContext('webgl2') || canvas.getContext('webgl'))
  } catch {
    return false
  }
}

const REDUCED = '(prefers-reduced-motion: reduce)'

export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(REDUCED).matches
}

/** Follows the reduced-motion preference live. */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(prefersReducedMotion)
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined
    const mq = window.matchMedia(REDUCED)
    const onChange = () => setReduced(mq.matches)
    mq.addEventListener?.('change', onChange)
    return () => mq.removeEventListener?.('change', onChange)
  }, [])
  return reduced
}
