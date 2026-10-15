// Real-time AR guidance (lazy chunk). The rear camera shows the station; every few seconds one downscaled frame goes
// to /api/navigation/localize (Gemini vision). From the fix, the arrow points at the next waypoint of the route the
// user already chose, and the gyroscope turns it as the phone turns between fixes. Everything is approximate and
// says so on screen; the safety banner never goes away; leaving always returns to the text steps.
//
// Privacy: frames are encoded in memory, sent once and dropped. Nothing is written to storage or logged.
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { ApiError, type ApiClient } from '../api/client'
import type { LocalizeCandidate, Provenance, RouteResult, StationDetails } from '../api/types'
import { ProvenanceBadge } from '../components/ProvenanceBadge'
import { AlertIcon, CameraIcon, CloseIcon, RefreshIcon, StepsIcon } from '../mobile/icons'
import type { MobileStrings } from '../mobile/strings'
import {
  AUTO_INTERVAL_MS, canSend, earliestTurnRelocaliseAt, emptyBudget, nextAutoAt, recordFailure, recordRateLimited, recordSend, recordSuccess,
  type Budget, type SendKind,
} from './budget'
import { immersiveArSupported, openRearCamera, requestMotionPermission, stopStream } from './device'
import { captureFrame, waitForFrame } from './frame'
import { arrowAngleDeg, directionOf, guidanceTarget, yawSinceFixDeg } from './geometry'
import { arReducer, initialArState, type FallbackReason } from './machine'
import { useCameraYaw } from './useCameraYaw'

/** A turn this large since the fix triggers a re-localisation (within the budget). */
export const LARGE_TURN_DEG = 60

// One budget per page load, shared by every AR visit: the server's limit is per session, not per visit.
let sessionBudget: Budget = emptyBudget()
/** Tests only. */
export function resetLocaliseBudget(): void {
  sessionBudget = emptyBudget()
}

export interface ArGuidanceProps {
  client: ApiClient
  stationId: string
  details: StationDetails
  route: RouteResult | null
  m: MobileStrings['ar']
  /** Leave AR: null when the user chose to, otherwise the reason (and the server message for `unavailable`). */
  onExit: (reason: FallbackReason | null, message: string | null) => void
  /** Tests: the clock used for the budget. */
  now?: () => number
}

const fill = (template: string, values: Record<string, string | number>) =>
  template.replace(/\{(\w+)\}/g, (_, k: string) => String(values[k] ?? ''))

const BTN = 'flex items-center justify-center gap-1.5 rounded-xl px-3 py-2 text-xs font-bold focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:ring-offset-2'

export default function ArGuidance({ client, stationId, details, route, m, onExit, now = Date.now }: ArGuidanceProps) {
  const [ar, dispatch] = useReducer(arReducer, initialArState)
  const [stream, setStream] = useState<MediaStream | null>(null)
  const [provenance, setProvenance] = useState<Provenance | null>(null)
  const [xrOk, setXrOk] = useState(false)
  const [floor, setFloor] = useState(false)
  const [floorError, setFloorError] = useState(false)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const rootRef = useRef<HTMLDivElement | null>(null)
  const inflight = useRef<AbortController | null>(null)
  const endFloor = useRef<(() => void) | null>(null)
  // False once AR is left (unmounted or fallen back): late camera grants are stopped, late frames never sent.
  const alive = useRef(true)
  const { yaw, yawRef } = useCameraYaw(ar.motion)
  const destination = route?.node_ids[route.node_ids.length - 1] ?? null

  // Leaving: stop the camera, cancel any upload, end floor mode.
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
      inflight.current?.abort()
      endFloor.current?.()
    }
  }, [])
  useEffect(() => () => stopStream(stream), [stream])

  useEffect(() => {
    const v = videoRef.current
    if (!v || !stream) return
    v.srcObject = stream
    v.play()?.catch(() => { /* autoplay is muted and inline; a refusal leaves the last frame */ })
  }, [stream])

  useEffect(() => {
    if (ar.phase !== 'fallback') return
    alive.current = false
    inflight.current?.abort()
    endFloor.current?.()
    setStream(null) // the stream effect's cleanup stops the tracks
    onExit(ar.fallback, ar.message)
  }, [ar.phase, ar.fallback, ar.message, onExit])

  useEffect(() => {
    let live = true
    immersiveArSupported().then((ok) => { if (live) setXrOk(ok) })
    return () => { live = false }
  }, [])

  const start = useCallback(() => {
    dispatch({ type: 'CONSENT_ACCEPTED' })
    // Both prompts start inside the click, which iOS needs for the motion permission.
    const motion = requestMotionPermission()
    const camera = openRearCamera()
    Promise.all([motion, camera]).then(([motionOk, cam]) => {
      if (!alive.current) { // left AR while the permission prompt was open
        if (cam.ok) stopStream(cam.stream)
        return
      }
      if (!cam.ok) {
        dispatch({ type: 'PERMISSION_FAILED', reason: cam.reason })
        return
      }
      setStream(cam.stream)
      dispatch({ type: 'PERMISSIONS_GRANTED', motion: motionOk })
    })
  }, [])

  const localise = useCallback(async (kind: SendKind) => {
    if (inflight.current || !route) return
    dispatch({ type: 'LOCALISE_START' })
    const t = now()
    if (!canSend(sessionBudget, t, kind)) {
      dispatch({ type: 'LOCALISE_FAILED', reason: 'rate_limited' })
      return
    }
    // Claimed before any await, so leaving AR during frame capture aborts this attempt too.
    const ctl = new AbortController()
    inflight.current = ctl
    const gone = () => ctl.signal.aborted || !alive.current
    let frame: Blob | null = null
    try {
      const video = videoRef.current
      const ready = video ? await waitForFrame(video) : false
      if (gone()) return
      const yawAtCapture = yawRef.current
      frame = ready && video ? await captureFrame(video) : null
      if (gone()) return
      if (!frame) {
        dispatch({ type: 'PERMISSION_FAILED', reason: 'camera_failed' }) // the camera gives no picture
        return
      }
      const image = frame
      const send = (fresh: boolean) => {
        sessionBudget = recordSend(sessionBudget, now())
        return client.localize({
          station_id: stationId, image, route_node_ids: route.node_ids,
          previous_node_id: ar.active?.fix.node_id ?? null,
        }, { signal: ctl.signal, freshSession: fresh })
      }
      let res
      try {
        res = await send(false)
      } catch (e) {
        // A stale session token (e.g. the backend restarted with a new key): drop it and try once with a new session.
        if (!(e instanceof ApiError && e.code === 'invalid_session_token') || gone() || !canSend(sessionBudget, now(), 'manual')) throw e
        res = await send(true)
      }
      frame = null // the only reference: dropped as soon as the upload is done
      if (gone()) return
      sessionBudget = res.status === 'unavailable' ? recordFailure(sessionBudget, now()) : recordSuccess(sessionBudget)
      setProvenance(res.provenance)
      dispatch({ type: 'LOCALISE_RESULT', response: res, yawNow: yawAtCapture, destinationNodeId: destination })
    } catch (e) {
      frame = null
      if (gone() || (e instanceof ApiError && e.isAborted)) return
      if (e instanceof ApiError && e.status === 429) {
        sessionBudget = recordRateLimited(sessionBudget, now(), e.retryAfterS)
        dispatch({ type: 'LOCALISE_FAILED', reason: 'rate_limited' })
      } else if (e instanceof ApiError && e.code === 'ar_guidance_unavailable') {
        dispatch({ type: 'LOCALISE_FAILED', reason: 'ar_off' })
      } else if (e instanceof ApiError && e.status >= 400 && e.status < 500) {
        // 413/415/422/401 and the like: the request itself is refused, so retrying would only repeat it.
        dispatch({ type: 'LOCALISE_FAILED', reason: 'rejected', message: e.message })
      } else {
        sessionBudget = recordFailure(sessionBudget, now()) // network, timeout or 5xx: back off and retry
        dispatch({ type: 'LOCALISE_FAILED', reason: 'network' })
      }
    } finally {
      if (inflight.current === ctl) inflight.current = null
    }
  }, [client, stationId, route, ar.active, destination, now, yawRef])

  // First fix as soon as the camera is up.
  useEffect(() => {
    if (ar.phase === 'localising' && stream && !inflight.current) void localise('manual')
  }, [ar.phase, stream, localise])

  // Automatic re-localisation while guiding, paced by the budget; paused in floor mode or a hidden tab.
  useEffect(() => {
    if (ar.phase !== 'guiding' || floor) return undefined
    const delay = Math.max(AUTO_INTERVAL_MS / 8, nextAutoAt(sessionBudget, now()) - now())
    const timer = setTimeout(() => {
      if (typeof document !== 'undefined' && document.hidden) return
      void localise('auto')
    }, delay)
    return () => clearTimeout(timer)
  }, [ar.phase, ar.active, ar.notice, floor, localise, now])

  const turned = ar.active && ar.motion ? yawSinceFixDeg(ar.active.yawAtFix, yaw) : 0
  // A large turn re-localises early (ahead of the pacing), but never faster than the auto interval or past the budget.
  useEffect(() => {
    if (ar.phase !== 'guiding' || floor || Math.abs(turned) < LARGE_TURN_DEG) return
    const t = now()
    if (canSend(sessionBudget, t, 'auto') && t >= earliestTurnRelocaliseAt(sessionBudget, t)) void localise('auto')
  }, [turned, ar.phase, floor, localise, now])

  const pick = (c: LocalizeCandidate) => {
    const node = details.station.nodes.find((n) => n.id === c.node_id)
    dispatch({ type: 'CANDIDATE_PICKED', candidate: c, position: node?.position ?? null, yawNow: yawRef.current, destinationNodeId: destination })
  }

  const target = useMemo(() => (ar.active && route
    ? guidanceTarget(route, details.station.nodes, ar.active.fix, details.station.map.width, details.station.map.height)
    : null), [ar.active, route, details])
  const angle = target && target.kind !== 'arrived' && ar.active
    ? arrowAngleDeg(target.bearingDeg, ar.active.fix.facing_bearing_deg, turned)
    : null

  const startFloor = async () => {
    if (angle === null || !rootRef.current) return
    setFloorError(false)
    setFloor(true)
    try {
      const { startFloorArrows } = await import('./xr')
      endFloor.current = await startFloorArrows({ arrowAngleDeg: angle, overlayRoot: rootRef.current,
        onEnd: () => { endFloor.current = null; setFloor(false) } })
    } catch {
      setFloor(false)
      setFloorError(true)
    }
  }

  const exit = () => dispatch({ type: 'EXIT' })
  const busy = ar.phase === 'localising' || ar.phase === 'relocalising'
  const cameraOn = !!stream

  return (
    <div ref={rootRef} data-testid="ar-guidance" className="space-y-3">
      {/* Always visible in AR mode. */}
      <div role="note" className="space-y-1 rounded-xl bg-amber-50 p-3 text-xs font-semibold text-amber-900 ring-1 ring-amber-200">
        <p className="flex items-center gap-1.5"><AlertIcon size={14} /> {m.safety}</p>
        <p data-testid="ar-approximate">{m.approximate}</p>
      </div>

      {!route ? <p className="text-sm text-ink-500">{m.needsRoute}</p> : ar.phase === 'consent' ? (
        <section aria-labelledby="ar-consent-title" className="space-y-2 rounded-2xl bg-white p-4 shadow-card ring-1 ring-ink-100">
          <h3 id="ar-consent-title" className="flex items-center gap-2 text-sm font-bold text-brand-900"><CameraIcon size={18} /> {m.consentTitle}</h3>
          <p className="text-xs text-ink-700">{m.consentBody}</p>
          <p className="text-xs text-ink-500">{m.consentMotion}</p>
          <div className="flex gap-2 pt-1">
            <button type="button" onClick={start} className={`${BTN} flex-1 bg-brand-600 text-white hover:bg-brand-700`}>{m.accept}</button>
            <button type="button" onClick={() => dispatch({ type: 'CONSENT_DECLINED' })} className={`${BTN} flex-1 bg-white text-ink-700 ring-1 ring-ink-300`}>{m.decline}</button>
          </div>
        </section>
      ) : (
        <>
          <div className="relative overflow-hidden rounded-2xl bg-ink-900" style={{ aspectRatio: '3 / 4', maxHeight: '60vh' }}>
            <video ref={videoRef} aria-label={m.cameraLabel} playsInline muted autoPlay className="h-full w-full object-cover" />
            {angle !== null && (ar.phase === 'guiding' || ar.phase === 'relocalising') && (
              <div className="pointer-events-none absolute inset-x-0 bottom-6 flex justify-center" style={{ perspective: '400px' }}>
                <svg data-testid="ar-arrow" data-angle={Math.round(angle)} role="img"
                  aria-label={fill(m.arrowLabel, { direction: m.direction[directionOf(angle)] })}
                  width="120" height="120" viewBox="-50 -50 100 100"
                  style={{ transform: `rotateX(50deg) rotate(${angle}deg)`, transition: 'transform 150ms linear' }}>
                  <path d="M0 -45 L28 -5 L10 -5 L10 40 L-10 40 L-10 -5 L-28 -5 Z" fill="#1d4ed8" fillOpacity="0.85" stroke="white" strokeWidth="4" />
                </svg>
              </div>
            )}
            {!cameraOn && <p role="status" className="absolute inset-0 grid place-items-center text-xs text-white">{m.starting}</p>}
          </div>

          <div aria-live="polite" className="space-y-1 text-sm">
            {busy && <p role="status" className="text-xs text-ink-500">{ar.phase === 'relocalising' ? m.relocalising : m.localising}</p>}
            {ar.active && (ar.phase === 'guiding' || ar.phase === 'relocalising') && target && target.kind !== 'arrived' && (
              <GuidanceText m={m} target={target} angle={angle} nodeName={ar.active.fix.node_name} confidence={ar.active.fix.confidence} picked={ar.active.picked} />
            )}
            {ar.phase === 'arrived' && ar.active && (
              <p className="rounded-xl bg-match-50 p-3 font-bold text-match-600">{fill(m.arrived, { place: ar.active.fix.node_name })}</p>
            )}
            {ar.notice && ar.phase === 'guiding' && <p className="text-xs text-amber-900">{ar.notice === 'unavailable' && ar.message ? ar.message : m.notice[ar.notice]}</p>}
            {!ar.motion && ar.active && ar.phase === 'guiding' && <p className="text-xs text-ink-500">{m.noMotion}</p>}
            {provenance && provenance.mode !== 'unavailable' && <ProvenanceBadge provenance={provenance} variant="full" />}
          </div>

          {ar.phase === 'choosing' && (
            <section aria-labelledby="ar-choose-title" className="space-y-2 rounded-2xl bg-white p-3 ring-1 ring-ink-100">
              <h3 id="ar-choose-title" className="text-sm font-bold text-brand-900">{m.chooseTitle}</h3>
              <p className="text-xs text-ink-500">{m.chooseHint}</p>
              <ul className="space-y-1.5">
                {ar.candidates.map((c) => (
                  <li key={c.node_id}>
                    <button type="button" onClick={() => pick(c)} className={`${BTN} w-full justify-between bg-brand-50 text-brand-800 ring-1 ring-brand-200`}>
                      <span>{c.node_name}</span><span className="font-normal">{fill(m.confidence, { pct: Math.round(c.confidence * 100) })}</span>
                    </button>
                  </li>
                ))}
              </ul>
              <button type="button" onClick={() => void localise('manual')} className={`${BTN} w-full bg-white text-ink-700 ring-1 ring-ink-300`}>{m.noneOfThese}</button>
            </section>
          )}

          {ar.phase === 'error' && ar.error && (
            <div role="alert" className="space-y-2 rounded-xl bg-red-50 p-3 text-xs text-red-900">
              <p>{m.error[ar.error]}</p>
              <button type="button" onClick={() => { dispatch({ type: 'RETRY' }) }} className={`${BTN} bg-white text-red-900 ring-1 ring-red-200`}>{m.retry}</button>
            </div>
          )}

          {floorError && <p role="alert" className="text-xs text-red-900">{m.floorFailed}</p>}

          <div className="flex flex-wrap gap-2">
            {(ar.phase === 'guiding' || ar.phase === 'arrived') && !floor && (
              <button type="button" onClick={() => void localise('manual')} className={`${BTN} flex-1 bg-brand-600 text-white hover:bg-brand-700`}>
                <RefreshIcon size={14} /> {m.rescan}
              </button>
            )}
            {xrOk && ar.phase === 'guiding' && angle !== null && !floor && (
              <button type="button" onClick={() => void startFloor()} title={m.floorHint} className={`${BTN} flex-1 bg-white text-brand-800 ring-1 ring-brand-200`}>
                {m.floor}
              </button>
            )}
            {floor && (
              <button type="button" onClick={() => endFloor.current?.()} className={`${BTN} flex-1 bg-white text-brand-800 ring-1 ring-brand-200`}>
                <CloseIcon size={14} /> {m.floorExit}
              </button>
            )}
          </div>
        </>
      )}

      <button type="button" onClick={exit} className={`${BTN} w-full bg-white text-ink-900 ring-1 ring-ink-300`}>
        <StepsIcon size={14} /> {m.exit}
      </button>
    </div>
  )
}

function GuidanceText({ m, target, angle, nodeName, confidence, picked }: {
  m: MobileStrings['ar']
  target: Exclude<ReturnType<typeof guidanceTarget>, { kind: 'arrived' }>
  angle: number | null
  nodeName: string
  confidence: number
  picked: boolean
}) {
  const distance = target.kind === 'on_route' ? target.instruction?.distance_m ?? null : null
  return (
    <div className="space-y-1 rounded-xl bg-white p-3 ring-1 ring-ink-100">
      <p className="text-xs text-ink-500">
        {fill(m.near, { place: nodeName })}{picked ? '' : ` · ${fill(m.confidence, { pct: Math.round(confidence * 100) })}`}
      </p>
      {angle !== null
        ? <p className="font-bold text-brand-900">{m.direction[directionOf(angle)]}</p>
        : <p className="text-xs text-amber-900">{m.noFacing}</p>}
      {target.kind === 'on_route' ? (
        <>
          <p className="text-sm text-ink-900">{target.instruction?.text ?? fill(m.nextStop, { place: target.nextNodeName })}</p>
          {distance !== null && <p className="text-xs text-ink-500">{fill(m.distance, { m: Math.round(distance) })}</p>}
        </>
      ) : <p className="text-sm text-ink-900">{fill(m.rejoin, { place: target.rejoinNodeName })}</p>}
    </div>
  )
}
