// errorText: one mapping from a failed call to passenger copy; Tamil never shows English envelope or client text.
import { ApiError } from '../api/client'
import { errorText } from '../api/errorText'
import { MOBILE_STRINGS } from '../mobile/strings'

const en = MOBILE_STRINGS.en
const ta = MOBILE_STRINGS.ta
const LATIN_WORD = /[A-Za-z]{3,}/

const cases: [string, ApiError, keyof typeof en.errors][] = [
  ['network', new ApiError(0, 'network_error', 'Cannot reach the planner service. Check that the backend is running.'), 'network'],
  ['timeout', new ApiError(0, 'timeout', 'The planner service took too long to respond.'), 'timeout'],
  ['gateway timeout', new ApiError(504, 'gateway_timeout', 'Gateway Timeout'), 'timeout'],
  ['429', new ApiError(429, 'rate_limited', 'Too many requests'), 'rateLimited'],
  ['session gone', new ApiError(404, 'session_not_found', 'Session not found.'), 'sessionGone'],
  ['bad token', new ApiError(401, 'invalid_session_token', 'A valid session token is required.'), 'sessionGone'],
  ['routing off', new ApiError(503, 'routing_unavailable', 'Step-by-step directions are not available.'), 'routingUnavailable'],
  ['5xx', new ApiError(503, 'storage_unavailable', 'Saved data is temporarily unavailable.'), 'unavailable'],
]

describe('errorText', () => {
  it.each(cases)('%s maps to its Tamil copy with no English text', (_label, err, key) => {
    const text = errorText(err, ta, 'ta')
    expect(text).toBe(ta.errors[key])
    expect(text.replace('RailSaathi', '')).not.toMatch(LATIN_WORD)
  })

  it.each(cases)('%s maps to its English copy, never the client developer text', (_label, err, key) => {
    const text = errorText(err, en, 'en')
    expect(text.startsWith(en.errors[key])).toBe(true)
    expect(text).not.toMatch(/backend is running|planner service/)
  })

  it('in English a 5xx keeps the server message as detail; a 4xx without copy shows it alone', () => {
    expect(errorText(new ApiError(503, 'storage_unavailable', 'Saved data is temporarily unavailable.'), en, 'en'))
      .toBe(`${en.errors.unavailable} (Saved data is temporarily unavailable.)`)
    expect(errorText(new ApiError(422, 'date_out_of_range', 'Meetings can be planned up to 60 days ahead.'), en, 'en'))
      .toBe('Meetings can be planned up to 60 days ahead.')
    expect(errorText(new ApiError(422, 'date_out_of_range', 'Meetings can be planned up to 60 days ahead.'), ta, 'ta'))
      .toBe(ta.errors.generic)
  })

  it('anything that is not an ApiError, or has no server text, is the generic copy', () => {
    expect(errorText(new Error('boom'), en, 'en')).toBe(en.errors.generic)
    expect(errorText('x', ta, 'ta')).toBe(ta.errors.generic)
    expect(errorText(new ApiError(400, 'http_error', 'Request failed (400)'), en, 'en')).toBe(en.errors.generic)
  })
})
