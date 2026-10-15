// Per-tab persistence of the planner session and the UI language, so a reload does not lose the plan.
// sessionStorage (not localStorage): it is cleared when the tab closes and never shared between tabs. It holds only
// the session id, the signed session token (useless without the server's key and the session TTL) and the language.
// Every access is wrapped: storage can be blocked or throw (private windows, sandboxed frames), and the app works
// without it.
import type { Language } from '../api/types'

const KEY = 'railsaathi.session.v1'

export interface StoredSession {
  sessionId: string
  token: string | null
}

export interface StoredState {
  language: Language
  session: StoredSession | null
}

const isLanguage = (v: unknown): v is Language => v === 'en' || v === 'ta'

export function loadState(): StoredState {
  const empty: StoredState = { language: 'en', session: null }
  try {
    const raw = window.sessionStorage.getItem(KEY)
    if (!raw) return empty
    const v = JSON.parse(raw) as { language?: unknown; session?: { sessionId?: unknown; token?: unknown } | null }
    const s = v.session
    return {
      language: isLanguage(v.language) ? v.language : 'en',
      session: s && typeof s.sessionId === 'string' && s.sessionId
        ? { sessionId: s.sessionId, token: typeof s.token === 'string' ? s.token : null }
        : null,
    }
  } catch {
    return empty
  }
}

/** Merges `patch` into the stored state. `session: null` forgets the session. */
export function saveState(patch: Partial<StoredState>): void {
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify({ ...loadState(), ...patch }))
  } catch {
    // storage unavailable: nothing is persisted, the app keeps working in memory
  }
}
