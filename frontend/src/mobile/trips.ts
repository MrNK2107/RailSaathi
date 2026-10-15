// "My Trips": confirmed journey plans saved on this device only (localStorage).
// This is a per-browser convenience; it is not synced and is not a booking record.
//
// Stored shape (version 2): { schemaVersion: 2, trips: SavedTrip[] }.
// Version 1 (no envelope) was a bare array of trips under the same key; it is migrated on first read.
// A version newer than this build understands is never read or overwritten, so an older tab cannot destroy the data
// of a newer one.

const KEY = 'railsaathi.savedTrips.v1'
const MAX_TRIPS = 20
export const TRIPS_SCHEMA_VERSION = 2

export interface SavedTrip {
  confirmationId: string
  savedAt: string
  trainNo: string
  trainName: string
  fromLabel: string
  toLabel: string
  journeyDate: string | null
  departure: string
  arrival: string
  passengers: number | null
  dataMode: string
  handoff: Record<string, unknown>
}

const str = (v: unknown): string | null => (typeof v === 'string' && v !== '' ? v : null)

/** Keeps a stored entry only if it has what the screens need; fills the optional fields v1 sometimes lacked. */
function normaliseTrip(raw: unknown): SavedTrip | null {
  if (!raw || typeof raw !== 'object') return null
  const t = raw as Record<string, unknown>
  const confirmationId = str(t.confirmationId)
  const departure = str(t.departure)
  const arrival = str(t.arrival)
  if (!confirmationId || !departure || !arrival) return null
  return {
    confirmationId,
    savedAt: str(t.savedAt) ?? '',
    trainNo: str(t.trainNo) ?? '',
    trainName: str(t.trainName) ?? '',
    fromLabel: str(t.fromLabel) ?? '',
    toLabel: str(t.toLabel) ?? '',
    journeyDate: str(t.journeyDate),
    departure,
    arrival,
    passengers: typeof t.passengers === 'number' ? t.passengers : null,
    dataMode: str(t.dataMode) ?? 'unknown',
    handoff: t.handoff && typeof t.handoff === 'object' && !Array.isArray(t.handoff) ? (t.handoff as Record<string, unknown>) : {},
  }
}

type Read = { trips: SavedTrip[]; newer: boolean }

/** Reads whatever version is stored and migrates it to the current shape in memory. */
function read(): Read {
  try {
    const raw = window.localStorage.getItem(KEY)
    if (!raw) return { trips: [], newer: false }
    const parsed: unknown = JSON.parse(raw)
    let list: unknown
    if (Array.isArray(parsed)) {
      list = parsed // version 1: a bare array
    } else if (parsed && typeof parsed === 'object') {
      const env = parsed as { schemaVersion?: unknown; trips?: unknown }
      if (typeof env.schemaVersion === 'number' && env.schemaVersion > TRIPS_SCHEMA_VERSION) return { trips: [], newer: true }
      list = env.trips
    } else {
      return { trips: [], newer: false }
    }
    if (!Array.isArray(list)) return { trips: [], newer: false }
    return { trips: list.map(normaliseTrip).filter((t): t is SavedTrip => t !== null), newer: false }
  } catch {
    return { trips: [], newer: false }
  }
}

const write = (trips: SavedTrip[]) =>
  window.localStorage.setItem(KEY, JSON.stringify({ schemaVersion: TRIPS_SCHEMA_VERSION, trips }))

export function loadTrips(): SavedTrip[] {
  return read().trips
}

/** Returns true if stored. Replaces an existing entry with the same confirmation id. */
export function saveTrip(trip: SavedTrip): boolean {
  try {
    const { trips, newer } = read()
    if (newer) return false // written by a newer version of the app: do not overwrite it
    const others = trips.filter((t) => t.confirmationId !== trip.confirmationId)
    write([trip, ...others].slice(0, MAX_TRIPS))
    return true
  } catch {
    return false
  }
}

export function removeTrip(confirmationId: string): SavedTrip[] {
  const { trips, newer } = read()
  const remaining = trips.filter((t) => t.confirmationId !== confirmationId)
  if (newer) return remaining
  try {
    write(remaining)
  } catch {
    // storage unavailable: the in-memory list still updates for this view
  }
  return remaining
}
