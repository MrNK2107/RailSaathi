// Every English string has a real, non-empty Tamil counterpart with the same placeholders.
import { STRINGS } from '../i18n/strings'
import { POPULAR_ROUTES } from '../mobile/config'
import { MOBILE_STRINGS, SPEECH_OPTIONS, fill } from '../mobile/strings'

function leaves(o: unknown, path = '', out: Record<string, string> = {}): Record<string, string> {
  if (typeof o === 'string') out[path] = o
  else if (Array.isArray(o)) o.forEach((v, i) => leaves(v, `${path}[${i}]`, out))
  else if (o && typeof o === 'object') for (const [k, v] of Object.entries(o)) leaves(v, path ? `${path}.${k}` : k, out)
  return out
}

const TAMIL = /[஀-௿]/
const placeholders = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort()

// Proper nouns, abbreviations and numbers that are written the same in Tamil.
const SAME_AS_ENGLISH = new Set([
  'brand', 'dashboard.sos', 'ticketing.assistant', 'tour.streetView', 'tour.streetViewTitle', 'alerts.delay.trainPlaceholder',
])
const SAME_AS_ENGLISH_CLASSIC = new Set(['appName'])

describe('mobile strings', () => {
  const en = leaves(MOBILE_STRINGS.en)
  const ta = leaves(MOBILE_STRINGS.ta)

  it('has a Tamil entry for every English key, and no extra Tamil keys', () => {
    expect(Object.keys(ta).sort()).toEqual(Object.keys(en).sort())
  })

  it('has no empty string in either language', () => {
    for (const [path, v] of [...Object.entries(en), ...Object.entries(ta)]) expect(v.trim(), path).not.toBe('')
  })

  it('translates every key into Tamil script (not an English copy), except listed proper nouns', () => {
    const untranslated = Object.keys(en).filter((p) => !SAME_AS_ENGLISH.has(p) && (ta[p] === en[p] || !TAMIL.test(ta[p])))
    expect(untranslated).toEqual([])
  })

  it('keeps the same {placeholders} in both languages', () => {
    for (const path of Object.keys(en)) expect(placeholders(ta[path]), path).toEqual(placeholders(en[path]))
  })

  it('offers Tamil, English and Tanglish speech options (Tanglish is recognised as Indian English)', () => {
    expect(SPEECH_OPTIONS.map((o) => [o.id, o.code])).toEqual([['ta', 'ta-IN'], ['en', 'en-IN'], ['tanglish', 'en-IN']])
  })

  it('no longer carries the stale preview / not-connected copy', () => {
    for (const lang of ['en', 'ta'] as const) {
      const all = Object.values(leaves(MOBILE_STRINGS[lang])).join('\n')
      expect(all).not.toMatch(/not connected|Preview —|AWS Bedrock/i)
    }
  })
})

describe('popular routes', () => {
  it('have Tamil-script titles and station names', () => {
    for (const r of POPULAR_ROUTES) {
      expect(r.ta, r.from + r.to).toMatch(TAMIL)
      expect(r.stationTa, r.station).toMatch(TAMIL)
    }
  })
})

describe('fill', () => {
  it('replaces named placeholders and blanks unknown ones', () => {
    expect(fill('Coach {coach} of {total}', { coach: 'B1', total: 12 })).toBe('Coach B1 of 12')
    expect(fill('{a}-{b}', { a: 1 })).toBe('1-')
  })
})

describe('classic strings', () => {
  const en = leaves(STRINGS.en)
  const ta = leaves(STRINGS.ta)

  it('has a non-empty Tamil entry for every English key', () => {
    expect(Object.keys(ta).sort()).toEqual(Object.keys(en).sort())
    for (const [p, v] of Object.entries(ta)) expect(v.trim(), p).not.toBe('')
  })

  it('translates the voice-input errors and the missing-voice note', () => {
    for (const code of ['insecure', 'not_allowed', 'no_microphone', 'network', 'language_unsupported', 'service_unavailable', 'start_failed', 'restart_limit']) {
      expect(ta[`mic.errors.${code}`]).toMatch(TAMIL)
      expect(ta[`mic.errors.${code}`]).not.toBe(en[`mic.errors.${code}`])
    }
    expect(ta.noVoice).toMatch(TAMIL)
  })

  it('writes Tamil text, not English copies, apart from the app name', () => {
    const copies = Object.keys(en).filter((p) => !SAME_AS_ENGLISH_CLASSIC.has(p) && ta[p] === en[p])
    expect(copies).toEqual([])
  })
})
