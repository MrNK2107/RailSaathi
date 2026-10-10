// "My Trips": confirmed journey plans saved on this device only (localStorage).
// This is a per-browser convenience; it is not synced and is not a booking record.

const KEY = 'railsaathi.savedTrips.v1'
const MAX_TRIPS = 20

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

export function loadTrips(): SavedTrip[] {
  try {
    const raw = window.localStorage.getItem(KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

/** Returns true if stored. Replaces an existing entry with the same confirmation id. */
export function saveTrip(trip: SavedTrip): boolean {
  try {
    const others = loadTrips().filter((t) => t.confirmationId !== trip.confirmationId)
    window.localStorage.setItem(KEY, JSON.stringify([trip, ...others].slice(0, MAX_TRIPS)))
    return true
  } catch {
    return false
  }
}

export function removeTrip(confirmationId: string): SavedTrip[] {
  const remaining = loadTrips().filter((t) => t.confirmationId !== confirmationId)
  try {
    window.localStorage.setItem(KEY, JSON.stringify(remaining))
  } catch {
    // storage unavailable: the in-memory list still updates for this view
  }
  return remaining
}
