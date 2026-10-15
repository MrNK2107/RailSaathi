// AR guidance state machine. A pure reducer, so every transition (denial, low confidence, unavailable, rate limits)
// is unit-tested without a camera.
//
// consent → permissions → localising → guiding ⇄ relocalising → arrived
//                                    ↘ choosing (low confidence: "Are you near…?") → guiding
// error: a recoverable failure before the first fix (rate limited, network); the user can retry or leave.
// fallback: AR ends and the screen returns to the text steps with `reason` shown (declined, permission denied,
// no camera, localisation unavailable, AR switched off for the station, a request the server rejects (4xx).
import type { LocalizeCandidate, LocalizeFix, LocalizeResponse } from '../api/types'

export type FallbackReason = 'declined' | 'camera_denied' | 'no_camera' | 'insecure' | 'unavailable' | 'ar_off' | 'camera_failed' | 'rejected'
export type ErrorReason = 'rate_limited' | 'network' | 'not_sure'

/** The fix the arrow is computed from, with the phone's yaw when it was taken. */
export interface ActiveFix {
  fix: Pick<LocalizeFix, 'node_id' | 'node_name' | 'position' | 'facing_bearing_deg' | 'confidence' | 'matched_cues'>
  /** Camera yaw (relative gyroscope frame) at the moment of the fix; null without motion data. */
  yawAtFix: number | null
  /** True when the user picked the node from candidates (no facing bearing from the model). */
  picked: boolean
}

export interface ArState {
  phase: 'consent' | 'permissions' | 'localising' | 'guiding' | 'relocalising' | 'choosing' | 'arrived' | 'error' | 'fallback'
  active: ActiveFix | null
  candidates: LocalizeCandidate[]
  /** Shown while guiding when the last attempt failed but an older fix is still used. */
  notice: ErrorReason | 'unavailable' | null
  error: ErrorReason | null
  fallback: FallbackReason | null
  /** Server message for `unavailable` (shown with the fallback). */
  message: string | null
  motion: boolean
}

export type ArEvent =
  | { type: 'CONSENT_ACCEPTED' }
  | { type: 'CONSENT_DECLINED' }
  | { type: 'PERMISSIONS_GRANTED'; motion: boolean }
  | { type: 'PERMISSION_FAILED'; reason: Extract<FallbackReason, 'camera_denied' | 'no_camera' | 'insecure' | 'camera_failed'> }
  | { type: 'LOCALISE_START' }
  | { type: 'LOCALISE_RESULT'; response: LocalizeResponse; yawNow: number | null; destinationNodeId: string | null }
  | { type: 'LOCALISE_FAILED'; reason: 'rate_limited' | 'network' | 'ar_off' | 'rejected'; message?: string | null }
  | { type: 'CANDIDATE_PICKED'; candidate: LocalizeCandidate; position: [number, number] | null; yawNow: number | null; destinationNodeId: string | null }
  | { type: 'RETRY' }
  | { type: 'EXIT' }

export const initialArState: ArState = {
  phase: 'consent', active: null, candidates: [], notice: null, error: null, fallback: null, message: null, motion: false,
}

const fallback = (s: ArState, reason: FallbackReason, message: string | null = null): ArState =>
  ({ ...s, phase: 'fallback', fallback: reason, message })

function settle(s: ArState, active: ActiveFix, destinationNodeId: string | null): ArState {
  const arrived = destinationNodeId !== null && active.fix.node_id === destinationNodeId
  return { ...s, phase: arrived ? 'arrived' : 'guiding', active, candidates: [], notice: null, error: null }
}

export function arReducer(s: ArState, e: ArEvent): ArState {
  if (s.phase === 'fallback') return s // terminal: the screen has gone back to the steps
  switch (e.type) {
    case 'CONSENT_ACCEPTED':
      return s.phase === 'consent' ? { ...s, phase: 'permissions' } : s
    case 'CONSENT_DECLINED':
      return fallback(s, 'declined')
    case 'PERMISSIONS_GRANTED':
      return s.phase === 'permissions' ? { ...s, phase: 'localising', motion: e.motion } : s
    case 'PERMISSION_FAILED':
      return fallback(s, e.reason)
    case 'LOCALISE_START':
      if (s.phase === 'guiding' || s.phase === 'arrived') return { ...s, phase: 'relocalising' }
      if (s.phase === 'error' || s.phase === 'choosing') return { ...s, phase: s.active ? 'relocalising' : 'localising', error: null }
      return s
    case 'LOCALISE_RESULT': {
      if (s.phase !== 'localising' && s.phase !== 'relocalising') return s // a late answer after leaving
      const r = e.response
      if (r.status === 'unavailable') {
        // A working fix is kept (with a notice); without one, AR cannot guide, so it falls back with the reason.
        return s.active ? { ...s, phase: 'guiding', notice: 'unavailable', message: r.message } : fallback(s, 'unavailable', r.message)
      }
      if (r.status === 'fix' && r.fix) {
        return settle(s, { fix: r.fix, yawAtFix: e.yawNow, picked: false }, e.destinationNodeId)
      }
      if (r.candidates.length) return { ...s, phase: 'choosing', candidates: r.candidates, notice: null }
      return s.active ? { ...s, phase: 'guiding', notice: 'not_sure' } : { ...s, phase: 'error', error: 'not_sure' }
    }
    case 'LOCALISE_FAILED':
      if (e.reason === 'ar_off') return fallback(s, 'ar_off')
      if (e.reason === 'rejected') return fallback(s, 'rejected', e.message ?? null) // retrying cannot help
      if (s.phase !== 'localising' && s.phase !== 'relocalising') return s
      return s.active ? { ...s, phase: 'guiding', notice: e.reason } : { ...s, phase: 'error', error: e.reason }
    case 'CANDIDATE_PICKED': {
      if (s.phase !== 'choosing' || !e.position) return s
      const fix = { node_id: e.candidate.node_id, node_name: e.candidate.node_name, position: e.position,
        facing_bearing_deg: null, confidence: e.candidate.confidence, matched_cues: [] }
      return settle(s, { fix, yawAtFix: e.yawNow, picked: true }, e.destinationNodeId)
    }
    case 'RETRY':
      return s.phase === 'error' ? { ...s, phase: 'localising', error: null } : s
    case 'EXIT':
      return { ...s, phase: 'fallback', fallback: null }
    default:
      return s
  }
}
