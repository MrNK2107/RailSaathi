import { TRIPS_SCHEMA_VERSION, loadTrips, removeTrip, saveTrip, type SavedTrip } from '../mobile/trips'

const KEY = 'railsaathi.savedTrips.v1'

const trip = (id: string, over: Partial<SavedTrip> = {}): SavedTrip => ({
  confirmationId: id, savedAt: '2026-10-10T10:00:00Z', trainNo: '12658', trainName: 'Bengaluru Mail',
  fromLabel: 'Chennai Central (MAS)', toLabel: 'KSR Bengaluru (SBC)', journeyDate: '2026-10-12',
  departure: '2026-10-12T22:00:00+05:30', arrival: '2026-10-13T04:30:00+05:30', passengers: 2, dataMode: 'live',
  handoff: { module: 'smart_passenger_planner' }, ...over,
})

const stored = () => JSON.parse(localStorage.getItem(KEY) ?? 'null')

beforeEach(() => localStorage.clear())

describe('saved trips storage', () => {
  it('writes the versioned envelope', () => {
    expect(saveTrip(trip('RSP-1'))).toBe(true)
    expect(stored()).toMatchObject({ schemaVersion: TRIPS_SCHEMA_VERSION, trips: [{ confirmationId: 'RSP-1' }] })
    expect(loadTrips().map((t) => t.confirmationId)).toEqual(['RSP-1'])
  })

  it('migrates the version 1 bare array on read and rewrites it as version 2 on the next save', () => {
    localStorage.setItem(KEY, JSON.stringify([trip('OLD-1'), trip('OLD-2')]))
    expect(loadTrips().map((t) => t.confirmationId)).toEqual(['OLD-1', 'OLD-2'])
    saveTrip(trip('NEW-1'))
    expect(stored().schemaVersion).toBe(TRIPS_SCHEMA_VERSION)
    expect(loadTrips().map((t) => t.confirmationId)).toEqual(['NEW-1', 'OLD-1', 'OLD-2'])
  })

  it('fills the optional fields a version 1 entry lacked and drops entries that are unusable', () => {
    const { passengers: _p, dataMode: _d, handoff: _h, ...sparse } = trip('OLD-3')
    localStorage.setItem(KEY, JSON.stringify([sparse, { confirmationId: 'NO-TIMES' }, 'junk', null]))
    expect(loadTrips()).toEqual([expect.objectContaining({ confirmationId: 'OLD-3', passengers: null, dataMode: 'unknown', handoff: {} })])
  })

  it('treats corrupt or unexpected storage as empty and still saves', () => {
    localStorage.setItem(KEY, '{not json')
    expect(loadTrips()).toEqual([])
    localStorage.setItem(KEY, JSON.stringify({ schemaVersion: 2, trips: 'nope' }))
    expect(loadTrips()).toEqual([])
    expect(saveTrip(trip('RSP-2'))).toBe(true)
    expect(loadTrips()).toHaveLength(1)
  })

  it('never reads or overwrites data written by a newer version of the app', () => {
    const future = JSON.stringify({ schemaVersion: TRIPS_SCHEMA_VERSION + 1, trips: [trip('FUTURE')], extra: true })
    localStorage.setItem(KEY, future)
    expect(loadTrips()).toEqual([])
    expect(saveTrip(trip('RSP-3'))).toBe(false)
    removeTrip('FUTURE')
    expect(localStorage.getItem(KEY)).toBe(future)
  })

  it('replaces an entry with the same id, keeps newest first and caps the list at 20', () => {
    for (let i = 0; i < 25; i += 1) saveTrip(trip(`T-${i}`))
    saveTrip(trip('T-24', { trainName: 'Updated' }))
    const trips = loadTrips()
    expect(trips).toHaveLength(20)
    expect(trips[0]).toMatchObject({ confirmationId: 'T-24', trainName: 'Updated' })
    expect(trips.filter((t) => t.confirmationId === 'T-24')).toHaveLength(1)
  })

  it('removes one trip and returns the rest, even when storage cannot be written', () => {
    saveTrip(trip('A'))
    saveTrip(trip('B'))
    expect(removeTrip('A').map((t) => t.confirmationId)).toEqual(['B'])
    const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota') })
    expect(removeTrip('B')).toEqual([])
    expect(saveTrip(trip('C'))).toBe(false)
    set.mockRestore()
  })
})
