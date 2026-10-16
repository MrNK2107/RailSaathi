// One mapping from a failed call to passenger copy in the screen's language. Backend envelope messages and the
// client's own ApiError messages are English (the client's are developer text), so they are never shown in Tamil.
// In English a server-authored message is kept as detail: on its own for a request error the app has no copy for,
// or in brackets after the "temporarily unavailable" copy for a 5xx.
import type { Language } from './types'
import { ApiError } from './client'

export interface ErrorCopy {
  network: string
  timeout: string
  rateLimited: string
  sessionGone: string
  unavailable: string
  routingUnavailable: string
  generic: string
}

type Kind = Exclude<keyof ErrorCopy, 'generic'>

function kindOf(err: ApiError): Kind | null {
  if (err.code === 'network_error') return 'network'
  if (err.code === 'timeout' || err.status === 504) return 'timeout'
  if (err.code === 'rate_limited' || err.status === 429) return 'rateLimited'
  if (err.isSessionGone || err.code === 'invalid_session_token') return 'sessionGone'
  if (err.code === 'routing_unavailable') return 'routingUnavailable'
  if (err.status === 0 || err.status >= 500) return 'unavailable'
  return null
}

/** The server's own message (English), when the error came from an HTTP response that carried one. */
function serverDetail(err: ApiError): string | null {
  return err.status > 0 && err.message && !err.message.startsWith('Request failed') ? err.message : null
}

export function errorText(err: unknown, m: { errors: ErrorCopy }, lang: Language): string {
  if (!(err instanceof ApiError)) return m.errors.generic
  const kind = kindOf(err)
  const detail = lang === 'en' ? serverDetail(err) : null
  if (kind === null) return detail ?? m.errors.generic
  const copy = m.errors[kind]
  return kind === 'unavailable' && detail && detail !== copy ? `${copy} (${detail})` : copy
}
