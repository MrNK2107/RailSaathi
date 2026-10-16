import { RELAX_PATCHES } from '../api/relax'
import { formatDate, formatDay, formatDuration, formatRupees, formatTime } from '../utils/format'

describe('format', () => {
  it('shows times and days in Indian Standard Time whatever the offset of the input', () => {
    expect(formatTime('2026-10-10T10:30:00+05:30')).toBe('10:30')
    expect(formatTime('2026-10-10T05:00:00Z')).toBe('10:30')
    expect(formatTime('2026-10-10T22:15:00Z')).toBe('03:45') // rolls into the next IST day
    expect(formatDay('2026-10-10T22:15:00Z')).toBe('11 Oct')
  })

  it('formats a calendar date without shifting it by the viewer timezone', () => {
    expect(formatDate('2026-10-10')).toMatch(/Sat.*10.*Oct.*2026/)
    expect(formatDate('2026-01-01')).toMatch(/Thu.*1.*Jan.*2026/)
  })

  it('formats durations as hours and zero-padded minutes', () => {
    expect(formatDuration(495)).toBe('8h 15m')
    expect(formatDuration(60)).toBe('1h 00m')
    expect(formatDuration(5)).toBe('0h 05m')
  })

  it('formats rupees with Indian digit grouping and no paise', () => {
    expect(formatRupees(590)).toBe('₹590')
    expect(formatRupees(1234567)).toBe('₹12,34,567')
    expect(formatRupees(799.6)).toBe('₹800')
  })
})

describe('relax suggestions', () => {
  it('maps each backend constraint to the patch that loosens only that requirement', () => {
    expect(RELAX_PATCHES.arrival_deadline).toEqual({ arrival_deadline: null })
    expect(RELAX_PATCHES.budget_limit).toEqual({ budget_limit: null, budget_strict: false })
    expect(RELAX_PATCHES.travel_class).toEqual({ class_strict: false })
    expect(RELAX_PATCHES.direct_only).toEqual({ transfer_strict: false })
    expect(RELAX_PATCHES.mandatory_assistance).toEqual({ assistance_mandatory: false })
  })

  it('has no entry for an unknown constraint, so the UI cannot patch something it does not understand', () => {
    expect(RELAX_PATCHES.unknown_constraint).toBeUndefined()
    expect(Object.keys(RELAX_PATCHES).sort()).toEqual(['arrival_deadline', 'budget_limit', 'direct_only', 'mandatory_assistance', 'travel_class'])
  })
})

describe('release-only switches', () => {
  it('maps a wheelchair the same way in every station view (step-free, not verified-only)', async () => {
    const { accessibilityPrefs } = await import('../navigation/useStationNav')
    const { mobilityPrefs } = await import('../hooks/useStationWayfinding')
    expect(mobilityPrefs('wheelchair')).toEqual(accessibilityPrefs(true, false))
    expect(mobilityPrefs('wheelchair')).toEqual({ wheelchair: true, avoid_stairs: true, require_verified_accessibility: false })
    expect(mobilityPrefs('avoid_stairs')).toEqual(accessibilityPrefs(false, true))
    expect(mobilityPrefs('normal')).toEqual(accessibilityPrefs(false, false))
  })

  it('the page description does not call the release a demo-data prototype', async () => {
    const html = (await import('../../index.html?raw')).default
    const description = /<meta name="description" content="([^"]+)"/.exec(html)?.[1] ?? ''
    expect(description).toMatch(/RailSaathi/)
    expect(description).not.toMatch(/prototype|demo data/i)
  })
})

describe('patch helpers', () => {
  it('maps editor values to API patches', async () => {
    const { toPatch } = await import('../components/FieldEditor')
    expect(toPatch('budget', { limit: '1500', strict: true, priority: '' })).toEqual({ budget_limit: 1500, budget_strict: true, budget_priority: null })
    expect(toPatch('origin', { place: '' })).toEqual({ origin: null })
  })
})
