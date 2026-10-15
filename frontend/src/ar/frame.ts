// Camera frames for /localize. A frame is drawn to an off-screen canvas, downscaled to MAX_FRAME_SIDE_PX on the
// longest side and encoded as JPEG. The Blob exists only for the upload: it is never stored (no localStorage,
// IndexedDB or Cache API), never logged, and the canvas is released after encoding.

export const MAX_FRAME_SIDE_PX = 768
export const MAX_FRAME_BYTES = 1_500_000 // backend LOCALIZE_MAX_IMAGE_BYTES
const QUALITIES = [0.8, 0.6, 0.4]

/** Output size for a frame: the longest side at most `max`, aspect kept, never upscaled. Null for an empty frame. */
export function frameSize(width: number, height: number, max = MAX_FRAME_SIDE_PX): { width: number; height: number } | null {
  if (!(width > 0) || !(height > 0)) return null
  const scale = Math.min(1, max / Math.max(width, height))
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) }
}

function encode(canvas: HTMLCanvasElement, quality: number): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality))
}

/** One downscaled JPEG of the current video frame, or null when the video has no frame yet. */
export async function captureFrame(video: HTMLVideoElement): Promise<Blob | null> {
  const size = frameSize(video.videoWidth, video.videoHeight)
  if (!size) return null
  const canvas = document.createElement('canvas')
  canvas.width = size.width
  canvas.height = size.height
  try {
    const ctx = canvas.getContext('2d')
    if (!ctx) return null
    ctx.drawImage(video, 0, 0, size.width, size.height)
    for (const q of QUALITIES) {
      const blob = await encode(canvas, q)
      if (blob && blob.size <= MAX_FRAME_BYTES) return blob
    }
    return null
  } finally {
    canvas.width = 0 // release the pixels now rather than at garbage collection
    canvas.height = 0
  }
}

/** Resolves true once the video has a frame to draw (or false after `timeoutMs`). */
export function waitForFrame(video: HTMLVideoElement, timeoutMs = 4000): Promise<boolean> {
  if (video.readyState >= 2 && video.videoWidth > 0) return Promise.resolve(true)
  return new Promise((resolve) => {
    const done = (ok: boolean) => {
      clearTimeout(timer)
      video.removeEventListener('loadeddata', onData)
      resolve(ok)
    }
    const onData = () => done(video.videoWidth > 0)
    const timer = setTimeout(() => done(false), timeoutMs)
    video.addEventListener('loadeddata', onData)
  })
}
