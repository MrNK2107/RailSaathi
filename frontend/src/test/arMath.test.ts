// Pure AR guidance maths: bearings, gyro yaw, arrow angle, guidance target, frame sizing, budget and back-off.
import type { RouteResult, StationNode } from '../api/types'
import {
  AUTO_INTERVAL_MS, MANUAL_RESERVE, MAX_BACKOFF_MS, SESSION_LIMIT, WINDOW_MS, backoffMs, canSend, emptyBudget, nextAutoAt,
  earliestTurnRelocaliseAt, recordFailure, recordRateLimited, recordSend, recordSuccess, remaining, type Budget,
} from '../ar/budget'
import { frameSize } from '../ar/frame'
import {
  arrowAngleDeg, cameraYawDeg, directionOf, firstHeadingDeg, guidanceTarget, normalizeDeg, planBearingDeg, signedDeltaDeg,
  toTrueBearing, yawSinceFixDeg,
} from '../ar/geometry'
import { floorDirection, forwardYawDeg } from '../ar/xr'

describe('bearings on the plan', () => {
  it('normalises and takes the shortest signed turn', () => {
    expect(normalizeDeg(-10)).toBe(350)
    expect(normalizeDeg(725)).toBe(5)
    expect(signedDeltaDeg(350, 10)).toBe(20)
    expect(signedDeltaDeg(10, 350)).toBe(-20)
    expect(signedDeltaDeg(0, 180)).toBe(180)
  })

  it('measures clockwise from plan-up in pixels, so a wide plan does not skew angles', () => {
    expect(planBearingDeg([0.5, 0.5], [0.5, 0.4], 1000, 500)).toBeCloseTo(0) // up
    expect(planBearingDeg([0.5, 0.5], [0.6, 0.5], 1000, 500)).toBeCloseTo(90) // right
    expect(planBearingDeg([0.5, 0.5], [0.5, 0.6], 1000, 500)).toBeCloseTo(180) // down
    // 0.1 across a 1000 px plan (100 px) and 0.2 down a 500 px plan (100 px): exactly 45° in pixels.
    expect(planBearingDeg([0.5, 0.5], [0.6, 0.3], 1000, 500)).toBeCloseTo(45)
    expect(planBearingDeg([0.5, 0.5], [0.5, 0.5], 1000, 500)).toBeNull()
  })

  it('takes the first heading that is not a repeated point', () => {
    expect(firstHeadingDeg([[0.1, 0.1], [0.1, 0.1], [0.1, 0.2]], 100, 100)).toBeCloseTo(180)
    expect(firstHeadingDeg([[0.1, 0.1]], 100, 100)).toBeNull()
  })

  it('geo_reference rotation cancels in the arrow, which compares two station-frame bearings', () => {
    expect(toTrueBearing(350, 20)).toBe(10)
    for (const rotation of [0, 37, 270]) expect(arrowAngleDeg(90, 30, 0, rotation)).toBeCloseTo(60)
  })
})

describe('gyro yaw (relative deviceorientation, rear camera)', () => {
  it('an upright phone faces -alpha: turning right lowers alpha and raises the yaw', () => {
    expect(cameraYawDeg(0, 90, 0)).toBeCloseTo(0)
    expect(cameraYawDeg(350, 90, 0)).toBeCloseTo(10) // turned 10° right
    expect(cameraYawDeg(90, 90, 0)).toBeCloseTo(270) // turned 90° left
  })

  it('a tilted phone still reports the camera heading; flat or missing data gives none', () => {
    expect(cameraYawDeg(0, 60, 0)).toBeCloseTo(0)
    expect(cameraYawDeg(0, 0, 0)).toBeNull() // camera points at the floor
    expect(cameraYawDeg(null, 90, 0)).toBeNull()
  })

  it('the turn since the fix wraps 359 → 1 as +2 and needs both readings', () => {
    expect(yawSinceFixDeg(359, 1)).toBe(2)
    expect(yawSinceFixDeg(1, 359)).toBe(-2)
    expect(yawSinceFixDeg(null, 10)).toBe(0)
  })

  it('arrow = target − facing − turn since fix', () => {
    expect(arrowAngleDeg(90, 90, 0)).toBe(0) // facing the waypoint
    expect(arrowAngleDeg(90, 0, 0)).toBe(90) // waypoint to the right
    expect(arrowAngleDeg(90, 0, 90)).toBe(0) // turned right by 90°: now ahead
    expect(arrowAngleDeg(10, 350, -5)).toBe(25) // wraps
    expect(arrowAngleDeg(0, 0, 180)).toBe(180)
    expect(arrowAngleDeg(90, null, 0)).toBeNull()
    expect(arrowAngleDeg(null, 0, 0)).toBeNull()
  })

  it('names the direction', () => {
    expect(directionOf(5)).toBe('ahead')
    expect(directionOf(-20)).toBe('ahead')
    expect(directionOf(45)).toBe('slight_right')
    expect(directionOf(-90)).toBe('left')
    expect(directionOf(170)).toBe('behind')
  })

  it('WebXR: forward yaw from a pose quaternion and the floor direction it maps to', () => {
    expect(forwardYawDeg(0, 0, 0, 1)).toBeCloseTo(0)
    const turnRight90 = [0, -Math.SQRT1_2, 0, Math.SQRT1_2] as const // -90° about +Y: -Z turns to +X
    expect(forwardYawDeg(...turnRight90)).toBeCloseTo(90)
    const [x, , z] = floorDirection(90)
    expect(x).toBeCloseTo(1)
    expect(z).toBeCloseTo(0)
  })
})

describe('guidance target from a fix', () => {
  const nodes: StationNode[] = [
    { id: 'a', name: 'Gate A', type: 'entrance', position: [0.1, 0.5], step_free: 'unknown' },
    { id: 'b', name: 'Junction B', type: 'junction', position: [0.5, 0.5], step_free: 'unknown' },
    { id: 'c', name: 'Platform 10', type: 'platform', position: [0.5, 0.1], step_free: 'unknown' },
    { id: 'z', name: 'Food court', type: 'facility', position: [0.45, 0.9], step_free: 'unknown' },
  ]
  const route = {
    node_ids: ['a', 'b', 'c'],
    segments: [
      { edge_id: 'e1', from_node: 'a', to_node: 'b', geometry: [[0.1, 0.5], [0.5, 0.5]], path_type: 'walkway', level_change: 0, step_free: 'unknown' },
      { edge_id: 'e2', from_node: 'b', to_node: 'c', geometry: [[0.5, 0.5], [0.5, 0.1]], path_type: 'walkway', level_change: 0, step_free: 'unknown' },
    ],
    instructions: [
      { step: 1, text: 'Walk east to Junction B', node_id: 'a', edge_id: 'e1', distance_m: 40, distance_is_estimate: true },
      { step: 2, text: 'Turn left to Platform 10', node_id: 'b', edge_id: 'e2', distance_m: 30, distance_is_estimate: true },
    ],
  } as unknown as RouteResult

  it('on the route: the heading of the segment leaving the node and its instruction', () => {
    const t = guidanceTarget(route, nodes, { node_id: 'b', position: [0.5, 0.5] }, 1000, 1000)
    expect(t).toMatchObject({ kind: 'on_route', nextNodeName: 'Platform 10' })
    if (t.kind !== 'on_route') throw new Error('expected on_route')
    expect(t.bearingDeg).toBeCloseTo(0)
    expect(t.instruction?.text).toBe('Turn left to Platform 10')
  })

  it('at the destination: arrived', () => {
    expect(guidanceTarget(route, nodes, { node_id: 'c', position: [0.5, 0.1] }, 1000, 1000)).toEqual({ kind: 'arrived', nodeName: 'Platform 10' })
  })

  it('off the route: back towards the nearest route node', () => {
    const t = guidanceTarget(route, nodes, { node_id: 'z', position: [0.45, 0.9] }, 1000, 1000)
    expect(t.kind).toBe('off_route')
    if (t.kind !== 'off_route') throw new Error('expected off_route')
    expect(t.rejoinNodeName).toBe('Junction B')
    expect(t.bearingDeg).toBeGreaterThan(0)
    expect(t.bearingDeg).toBeLessThan(20) // up and slightly right
  })
})

describe('frame size', () => {
  it('scales the longest side to 768 px, keeps the aspect and never upscales', () => {
    expect(frameSize(1280, 720)).toEqual({ width: 768, height: 432 })
    expect(frameSize(720, 1280)).toEqual({ width: 432, height: 768 })
    expect(frameSize(640, 480)).toEqual({ width: 640, height: 480 })
    expect(frameSize(0, 480)).toBeNull()
  })
})

describe('localisation budget and back-off', () => {
  it('auto sends leave MANUAL_RESERVE slots for taps and picks', () => {
    let b = emptyBudget()
    for (let i = 0; i < SESSION_LIMIT - MANUAL_RESERVE; i += 1) b = recordSend(b, i * 1000)
    const t = 20_000
    expect(canSend(b, t, 'auto')).toBe(false)
    expect(canSend(b, t, 'manual')).toBe(true)
    expect(remaining(b, t, 'manual')).toBe(MANUAL_RESERVE)
    // The window slides: once the oldest send is 10 minutes old, auto may send again.
    expect(canSend(b, WINDOW_MS, 'auto')).toBe(true)
  })

  it('auto runs every 8 s while the share is large, then paces itself', () => {
    let b = recordSend(emptyBudget(), 0)
    expect(nextAutoAt(b, 1000)).toBe(AUTO_INTERVAL_MS)
    for (let i = 1; i < 10; i += 1) b = recordSend(b, i * AUTO_INTERVAL_MS)
    const last = 9 * AUTO_INTERVAL_MS
    expect(nextAutoAt(b, last)).toBeGreaterThan(last + AUTO_INTERVAL_MS) // 6 auto slots left: spread them out
  })

  it('a large turn may skip the pacing but not the 8 s minimum or a block', () => {
    let b = emptyBudget()
    for (let i = 0; i < 12; i += 1) b = recordSend(b, i * AUTO_INTERVAL_MS) // few auto slots left: paced
    const last = 11 * AUTO_INTERVAL_MS
    expect(earliestTurnRelocaliseAt(b, last)).toBe(last + AUTO_INTERVAL_MS)
    expect(nextAutoAt(b, last)).toBeGreaterThan(last + AUTO_INTERVAL_MS)
    expect(earliestTurnRelocaliseAt(recordRateLimited(b, last, 60), last)).toBe(last + 60_000)
  })

  it('a 429 blocks every send until Retry-After; without the header it backs off exponentially', () => {
    const b = recordRateLimited(emptyBudget(), 1000, 30)
    expect(canSend(b, 30_999, 'manual')).toBe(false)
    expect(canSend(b, 31_000, 'manual')).toBe(true)
    expect(nextAutoAt(b, 2000)).toBe(31_000)
    const c = recordRateLimited(recordRateLimited(emptyBudget(), 0, null), 0, null)
    expect(c.blockedUntil).toBe(backoffMs(2))
  })

  it('failures back off 8, 16, 32 s … capped; a success resets the count', () => {
    expect([1, 2, 3].map(backoffMs)).toEqual([8000, 16000, 32000])
    expect(backoffMs(20)).toBe(MAX_BACKOFF_MS)
    let b: Budget = recordFailure(emptyBudget(), 0)
    b = recordFailure(b, 0)
    expect(b.blockedUntil).toBe(16000)
    expect(recordSuccess(b).failures).toBe(0)
  })

  it('simulated hour of auto re-localisation plus a tap every 20 s never exceeds the server limit', () => {
    let b = emptyBudget()
    const sends: number[] = []
    let nextAuto = 0
    for (let t = 0; t < 3_600_000; t += 500) {
      if (t >= nextAuto && canSend(b, t, 'auto')) {
        b = recordSend(b, t)
        sends.push(t)
      } else if (t % 20_000 === 0 && canSend(b, t, 'manual')) {
        b = recordSend(b, t)
        sends.push(t)
      }
      nextAuto = nextAutoAt(b, t)
    }
    for (const start of sends) {
      expect(sends.filter((s) => s >= start && s < start + WINDOW_MS).length).toBeLessThanOrEqual(SESSION_LIMIT)
    }
    expect(sends.length).toBeGreaterThan(100) // and it keeps guiding: about 20 fixes per 10 minutes
  })
})
