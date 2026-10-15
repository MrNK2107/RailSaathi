// Client-side localisation budget and back-off. Pure: time is passed in, so it is unit-tested.
//
// The backend allows LOCALIZE_RATE_LIMIT (20) fixes per session per LOCALIZE_RATE_WINDOW_SECONDS (600 s). The
// client keeps a sliding window of its own sends and never lets automatic re-localisation use the last
// MANUAL_RESERVE slots, so a tap or a pick still works when auto has spent its share. Auto re-localisation runs every
// AUTO_INTERVAL_MS while at least PACE_BELOW auto slots are left; below that it is paced so the rest of the share
// lasts until the window frees up, instead of bursting and then stalling. (20 per 10 minutes is one fix every 30 s
// sustained, so an 8 s cadence can only hold for the first minute or so of a walk.) A 429 blocks
// every send until Retry-After (or an exponential back-off when the header is missing); network failures and
// `unavailable` answers back off exponentially too.

export const SESSION_LIMIT = 20
export const WINDOW_MS = 600_000
export const MANUAL_RESERVE = 4
export const AUTO_INTERVAL_MS = 8_000
export const MAX_BACKOFF_MS = 120_000
export const PACE_BELOW = 8

export type SendKind = 'auto' | 'manual'

export interface Budget {
  /** Send times within the window, oldest first. */
  sent: number[]
  /** No send of any kind before this time (a 429 or a failure back-off). */
  blockedUntil: number
  /** Consecutive failures, for the exponential back-off. */
  failures: number
}

export const emptyBudget = (): Budget => ({ sent: [], blockedUntil: 0, failures: 0 })

const live = (b: Budget, now: number) => b.sent.filter((t) => now - t < WINDOW_MS)

export function remaining(b: Budget, now: number, kind: SendKind): number {
  const cap = kind === 'auto' ? SESSION_LIMIT - MANUAL_RESERVE : SESSION_LIMIT
  return Math.max(0, cap - live(b, now).length)
}

export function canSend(b: Budget, now: number, kind: SendKind): boolean {
  return now >= b.blockedUntil && remaining(b, now, kind) > 0
}

export function recordSend(b: Budget, now: number): Budget {
  return { ...b, sent: [...live(b, now), now] }
}

export function recordSuccess(b: Budget): Budget {
  return { ...b, failures: 0 }
}

/** Exponential back-off: 8 s, 16 s, 32 s … capped at MAX_BACKOFF_MS. */
export function backoffMs(failures: number): number {
  return Math.min(MAX_BACKOFF_MS, AUTO_INTERVAL_MS * 2 ** Math.max(0, failures - 1))
}

export function recordFailure(b: Budget, now: number): Budget {
  const failures = b.failures + 1
  return { ...b, failures, blockedUntil: Math.max(b.blockedUntil, now + backoffMs(failures)) }
}

/** A 429: wait for Retry-After when given, otherwise back off as for a failure. */
export function recordRateLimited(b: Budget, now: number, retryAfterS: number | null): Budget {
  const failures = b.failures + 1
  const wait = retryAfterS !== null && retryAfterS >= 0 ? retryAfterS * 1000 : backoffMs(failures)
  return { ...b, failures, blockedUntil: Math.max(b.blockedUntil, now + wait) }
}

/** Earliest time a turn-triggered re-localisation may run: AUTO_INTERVAL_MS after the last send and outside any block
 * (it skips the pacing, not the budget: callers still check `canSend(…, 'auto')`). */
export function earliestTurnRelocaliseAt(b: Budget, now: number): number {
  const sent = live(b, now)
  return Math.max(sent.length ? sent[sent.length - 1] + AUTO_INTERVAL_MS : now, b.blockedUntil)
}

/**
 * When the next automatic re-localisation may run: at least AUTO_INTERVAL_MS after the last send, not before a
 * block ends; with fewer than PACE_BELOW auto slots left, paced so they spread over what is left of the window; and
 * when the share is spent, when the oldest send leaves the window.
 */
export function nextAutoAt(b: Budget, now: number): number {
  const sent = live(b, now)
  const last = sent.length ? sent[sent.length - 1] : -Infinity
  let at = Math.max(last + AUTO_INTERVAL_MS, b.blockedUntil, now)
  const left = remaining(b, now, 'auto')
  if (left <= 0) {
    const cap = SESSION_LIMIT - MANUAL_RESERVE
    // The (n - cap + 1)th oldest send must expire before another auto send fits.
    at = Math.max(at, sent[sent.length - cap] + WINDOW_MS)
  } else if (sent.length && left < PACE_BELOW) {
    const windowLeft = sent[0] + WINDOW_MS - now
    at = Math.max(at, last + windowLeft / left)
  }
  return at
}
