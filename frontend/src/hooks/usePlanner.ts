import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, api as defaultApi, type ApiClient } from '../api/client'
import { errorText } from '../api/errorText'
import type { HealthResponse, JourneyPatch, Language, PlannerResponse, ReferenceData } from '../api/types'
import { STRINGS } from '../i18n/strings'
import { loadState, saveState } from '../mobile/persist'
import { MOBILE_STRINGS } from '../mobile/strings'

export interface ChatMessage {
  id: number
  role: 'user' | 'assistant' | 'system'
  text: string
  /** Set on a new session's greeting: the language the backend greeted in. */
  greeting?: Language
}

type Action = () => Promise<PlannerResponse>

let nextId = 1
const message = (role: ChatMessage['role'], text: string): ChatMessage => ({ id: nextId++, role, text })
const greeting = (text: string, lang: Language): ChatMessage => ({ ...message('assistant', text), greeting: lang })

/** Session-scoped planner state. The backend response is always the source of truth. */
export function usePlanner(client: ApiClient = defaultApi) {
  const [language, setLanguageState] = useState<Language>(() => loadState().language)
  const [response, setResponse] = useState<PlannerResponse | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(false)
  // The failed call itself; rendered in the current language (errorText) so a language switch updates it.
  const [error, setError] = useState<unknown>(null)
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [reference, setReference] = useState<ReferenceData | null>(null)
  const retryRef = useRef<Action | null>(null)
  // The language of a session just created, whose first assistant message is its greeting.
  const pendingGreeting = useRef<Language | null>(null)
  const langRef = useRef(language)
  langRef.current = language

  const setLanguage = useCallback((lang: Language) => {
    setLanguageState(lang)
    saveState({ language: lang })
  }, [])

  const startSession = useCallback(async (lang: Language) => {
    const res = await client.createSession(lang)
    saveState({ session: { sessionId: res.session_id, token: res.session_token ?? null } })
    setResponse(res)
    setMessages([]) // run() appends the greeting
    pendingGreeting.current = lang
    return res
  }, [client])

  /** Runs a backend action; resolves true only when the backend call succeeded. */
  const run = useCallback(async (action: Action, userText?: string): Promise<boolean> => {
    setLoading(true)
    setError(null)
    if (userText) setMessages((prev) => [...prev, message('user', userText)])
    try {
      const res = await action()
      setResponse(res)
      const greetLang = pendingGreeting.current
      pendingGreeting.current = null
      if (res.assistant_message) {
        const reply = greetLang ? greeting(res.assistant_message, greetLang) : message('assistant', res.assistant_message)
        setMessages((prev) => [...prev, reply])
      }
      retryRef.current = null
      return true
    } catch (err) {
      const apiErr = err instanceof ApiError ? err : new ApiError(0, 'unknown', String(err))
      if (apiErr.isSessionGone) {
        const fresh = await startSession(langRef.current).catch(() => null)
        pendingGreeting.current = null
        setMessages([
          message('system', STRINGS[langRef.current].errors.sessionGone),
          ...(fresh ? [greeting(fresh.assistant_message, langRef.current)] : []),
        ])
      } else {
        retryRef.current = apiErr.status === 0 || apiErr.status >= 500 ? action : null
        setError(apiErr)
      }
      return false
    } finally {
      setLoading(false)
    }
  }, [startSession])

  /** Start a fresh planning session and immediately send a request (e.g. a popular route). */
  const startWithMessage = useCallback(async (text: string): Promise<boolean> => {
    setLoading(true)
    setError(null)
    try {
      const fresh = await client.createSession(langRef.current)
      saveState({ session: { sessionId: fresh.session_id, token: fresh.session_token ?? null } })
      setResponse(fresh)
      const res = await client.sendMessage(fresh.session_id, text, langRef.current)
      setResponse(res)
      setMessages([greeting(fresh.assistant_message, langRef.current), message('user', text), message('assistant', res.assistant_message)])
      return true
    } catch (err) {
      setError(err)
      return false
    } finally {
      setLoading(false)
    }
  }, [client])

  const initialised = useRef(false)
  useEffect(() => {
    if (initialised.current) return // StrictMode runs effects twice in dev
    initialised.current = true
    client.health().then(setHealth).catch(() => setHealth(null))
    client.reference().then(setReference).catch(() => setReference(null))
    // Resume this tab's session after a reload; the backend is the source of truth, so ask it for the state.
    // Only a session the backend says is gone (expired, unknown, or a token it rejects) is discarded for a fresh
    // one. A transient failure (offline, timeout, 5xx) keeps the stored session and is rethrown, so `run` shows
    // the error and its Retry resumes the same plan.
    const resume = async (): Promise<PlannerResponse> => {
      const stored = loadState().session
      if (stored) {
        try {
          client.setSessionToken(stored.token)
          return await client.getSession(stored.sessionId) // run() shows its assistant message
        } catch (err) {
          const gone = err instanceof ApiError && (err.isSessionGone || err.code === 'invalid_session_token')
          if (!gone) throw err
          client.setSessionToken(null)
          saveState({ session: null })
        }
      }
      return startSession(langRef.current)
    }
    run(resume)
    // Run once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const sid = response?.session_id ?? ''
  // A greeting follows the UI language: when the language changed after the session began (e.g. Tamil picked on
  // the home screen), the app shows its own greeting in the current language instead of the backend's.
  const shown = useMemo(() => messages.map((msg) => (msg.greeting && msg.greeting !== language
    ? { ...msg, text: MOBILE_STRINGS[language].plan.greeting } : msg)), [messages, language])

  return {
    /** The API client (carries the session token used by the goal planner). */
    client,
    language,
    setLanguage,
    response,
    state: response?.state ?? null,
    messages: shown,
    loading,
    error: error === null ? null : errorText(error, MOBILE_STRINGS[language], language),
    health,
    reference,
    canRetry: retryRef.current !== null,
    retry: () => retryRef.current && run(retryRef.current),
    send: (text: string) => run(() => client.sendMessage(sid, text, language), text),
    patch: (patch: JourneyPatch) => run(() => client.patchJourney(sid, patch)),
    recommend: () => run(() => client.recommendations(sid)),
    select: (optionId: string) => run(() => client.select(sid, optionId)),
    confirm: (optionId: string | null) => run(() => client.confirm(sid, optionId)),
    reassess: (eventId: string | null) => run(() => client.reassess(sid, eventId)),
    cancel: () => run(() => client.cancel(sid)),
    restart: () => run(() => startSession(language)),
    startWithMessage,
    clearError: () => setError(null),
  }
}

export type Planner = ReturnType<typeof usePlanner>
