// AR guidance state machine: consent, permissions, fixes, low confidence, unavailable, rate limits, leaving.
import type { LocalizeResponse } from '../api/types'
import { arReducer, initialArState, type ArEvent, type ArState } from '../ar/machine'

const prov = { mode: 'live' as const, source: 'gemini-vision', as_of: '2026-10-16T10:00:00Z', note: 'Approximate: estimated from one camera frame.' }

function res(over: Partial<LocalizeResponse>): LocalizeResponse {
  return {
    status: 'fix', station_id: 'chennai_central', fix: null, candidates: [], confidence_threshold: 0.6, latency_ms: 900,
    message: null, session_token: 't', provenance: prov, ...over,
  }
}
const fix = (node_id: string) => ({
  node_id, node_name: node_id.toUpperCase(), level: 0, position: [0.5, 0.5] as [number, number], confidence: 0.8,
  facing_bearing_deg: 90, matched_cues: ['PLATFORM 10'],
})
const run = (events: ArEvent[], from: ArState = initialArState) => events.reduce(arReducer, from)
const ready: ArEvent[] = [{ type: 'CONSENT_ACCEPTED' }, { type: 'PERMISSIONS_GRANTED', motion: true }]
const result = (r: LocalizeResponse, yawNow: number | null = 10): ArEvent => ({ type: 'LOCALISE_RESULT', response: r, yawNow, destinationNodeId: 'platform_10' })

describe('AR state machine', () => {
  it('consent → permissions → localising → guiding, recording the yaw at the fix', () => {
    let s = run([{ type: 'CONSENT_ACCEPTED' }])
    expect(s.phase).toBe('permissions')
    s = run([{ type: 'PERMISSIONS_GRANTED', motion: true }], s)
    expect(s).toMatchObject({ phase: 'localising', motion: true })
    s = run([result(res({ fix: fix('cj_north') }), 42)], s)
    expect(s.phase).toBe('guiding')
    expect(s.active).toMatchObject({ fix: { node_id: 'cj_north' }, yawAtFix: 42, picked: false })
  })

  it('declining consent or a denied camera falls back to the steps with the reason', () => {
    expect(run([{ type: 'CONSENT_DECLINED' }])).toMatchObject({ phase: 'fallback', fallback: 'declined' })
    expect(run([{ type: 'CONSENT_ACCEPTED' }, { type: 'PERMISSION_FAILED', reason: 'camera_denied' }]))
      .toMatchObject({ phase: 'fallback', fallback: 'camera_denied' })
    // Fallback is terminal: nothing reopens AR behind the user's back.
    const done = run([{ type: 'CONSENT_DECLINED' }, { type: 'CONSENT_ACCEPTED' }, ...ready])
    expect(done.phase).toBe('fallback')
  })

  it('motion permission refused still guides, without gyro', () => {
    expect(run([{ type: 'CONSENT_ACCEPTED' }, { type: 'PERMISSIONS_GRANTED', motion: false }])).toMatchObject({ phase: 'localising', motion: false })
  })

  it('low confidence shows candidates; a pick becomes the fix without a facing bearing', () => {
    const cands = [{ node_id: 'nj_west', node_name: 'North Corridor', confidence: 0.45 }, { node_id: 'cj_north', node_name: 'CJ', confidence: 0.3 }]
    let s = run([...ready, result(res({ status: 'low_confidence', candidates: cands }))])
    expect(s).toMatchObject({ phase: 'choosing', candidates: cands })
    s = run([{ type: 'CANDIDATE_PICKED', candidate: cands[0], position: [0.2, 0.3], yawNow: 5, destinationNodeId: 'platform_10' }], s)
    expect(s.phase).toBe('guiding')
    expect(s.active).toMatchObject({ fix: { node_id: 'nj_west', facing_bearing_deg: null, position: [0.2, 0.3] }, yawAtFix: 5, picked: true })
    expect(s.candidates).toEqual([])
  })

  it('"none of these" re-scans from the candidate list', () => {
    const s = run([...ready, result(res({ status: 'low_confidence', candidates: [{ node_id: 'x', node_name: 'X', confidence: 0.2 }] })), { type: 'LOCALISE_START' }])
    expect(s.phase).toBe('localising')
  })

  it('low confidence with no candidates is a recoverable error before the first fix', () => {
    const s = run([...ready, result(res({ status: 'low_confidence' }))])
    expect(s).toMatchObject({ phase: 'error', error: 'not_sure' })
    expect(run([{ type: 'RETRY' }], s).phase).toBe('localising')
  })

  it('unavailable before a fix falls back with the server message; after a fix keeps guiding with a notice', () => {
    const msg = 'Camera positioning is unavailable right now.'
    expect(run([...ready, result(res({ status: 'unavailable', message: msg, provenance: { ...prov, mode: 'unavailable' } }))]))
      .toMatchObject({ phase: 'fallback', fallback: 'unavailable', message: msg })
    const guiding = run([...ready, result(res({ fix: fix('cj_north') }))])
    const s = run([{ type: 'LOCALISE_START' }, result(res({ status: 'unavailable', message: msg }))], guiding)
    expect(s).toMatchObject({ phase: 'guiding', notice: 'unavailable', active: { fix: { node_id: 'cj_north' } } })
  })

  it('re-localising keeps the last fix; rate limits and network errors become notices', () => {
    const guiding = run([...ready, result(res({ fix: fix('cj_north') }))])
    const reloc = run([{ type: 'LOCALISE_START' }], guiding)
    expect(reloc.phase).toBe('relocalising')
    expect(reloc.active?.fix.node_id).toBe('cj_north')
    expect(run([{ type: 'LOCALISE_FAILED', reason: 'rate_limited' }], reloc)).toMatchObject({ phase: 'guiding', notice: 'rate_limited' })
    expect(run([{ type: 'LOCALISE_FAILED', reason: 'network' }], reloc)).toMatchObject({ phase: 'guiding', notice: 'network' })
    // A new fix clears the notice.
    const s = run([{ type: 'LOCALISE_FAILED', reason: 'network' }, { type: 'LOCALISE_START' }, result(res({ fix: fix('nj_west') }), 99)], reloc)
    expect(s).toMatchObject({ phase: 'guiding', notice: null, active: { fix: { node_id: 'nj_west' }, yawAtFix: 99 } })
  })

  it('a rate limit before the first fix is an error the user can retry', () => {
    expect(run([...ready, { type: 'LOCALISE_FAILED', reason: 'rate_limited' }])).toMatchObject({ phase: 'error', error: 'rate_limited' })
  })

  it('AR switched off for the station (404) falls back at any point', () => {
    const guiding = run([...ready, result(res({ fix: fix('cj_north') }))])
    expect(run([{ type: 'LOCALISE_FAILED', reason: 'ar_off' }], guiding)).toMatchObject({ phase: 'fallback', fallback: 'ar_off' })
  })

  it('a refused request (4xx) falls back with the server message, even with a fix', () => {
    const guiding = run([...ready, result(res({ fix: fix('cj_north') }))])
    expect(run([{ type: 'LOCALISE_START' }, { type: 'LOCALISE_FAILED', reason: 'rejected', message: 'The image is too large.' }], guiding))
      .toMatchObject({ phase: 'fallback', fallback: 'rejected', message: 'The image is too large.' })
  })

  it('a fix at the destination is arrival; a late answer after leaving is ignored', () => {
    expect(run([...ready, result(res({ fix: fix('platform_10') }))]).phase).toBe('arrived')
    const guiding = run([...ready, result(res({ fix: fix('cj_north') }))])
    expect(run([result(res({ fix: fix('nj_west') }))], guiding).active?.fix.node_id).toBe('cj_north') // not localising
  })

  it('leaving is a fallback without a reason', () => {
    expect(run([...ready, { type: 'EXIT' }])).toMatchObject({ phase: 'fallback', fallback: null })
  })
})
