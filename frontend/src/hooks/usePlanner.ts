import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, api as defaultApi, type ApiClient } from '../api/client'
import type { HealthResponse, JourneyPatch, Language, PlannerResponse, ReferenceData } from '../api/types'
import { STRINGS } from '../i18n/strings'
import { loadState, saveState } from '../mobile/persist'

export interface ChatMessage {
  id: number
  role: 'user' | 'assistant' | 'system'
  text: string
}

type Action = () => Promise<PlannerResponse>

let nextId = 1
const message = (role: ChatMessage['role'], text: string): ChatMessage => ({ id: nextId++, role, text })

/** Session-scoped planner state. The backend response is always the source of truth. */
export function usePlanner(client: ApiClient = defaultApi) {
  const [language, setLanguageState] = useState<Language>(() => loadState().language)
  const [response, setResponse] = useState<PlannerResponse | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [reference, setReference] = useState<ReferenceData | null>(null)
  const retryRef = useRef<Action | null>(null)
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
      if (res.assistant_message) setMessages((prev) => [...prev, message('assistant', res.assistant_message)])
      retryRef.current = null
      return true
    } catch (err) {
      const apiErr = err instanceof ApiError ? err : new ApiError(0, 'unknown', String(err))
      if (apiErr.isSessionGone) {
        const fresh = await startSession(langRef.current).catch(() => null)
        setMessages([
          message('system', STRINGS[langRef.current].errors.sessionGone),
          ...(fresh ? [message('assistant', fresh.assistant_message)] : []),
        ])
      } else {
        retryRef.current = apiErr.status === 0 || apiErr.status >= 500 ? action : null
        setError(apiErr.message)
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
      setMessages([message('assistant', fresh.assistant_message), message('user', text), message('assistant', res.assistant_message)])
      return true
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
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
    // Any failure (expired, unknown, offline) falls back to a fresh session, which `run` reports if it also fails.
    const resume = async (): Promise<PlannerResponse> => {
      const stored = loadState().session
      if (stored) {
        try {
          client.setSessionToken(stored.token)
          return await client.getSession(stored.sessionId) // run() shows its assistant message
        } catch {
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

  return {
    /** The API client (carries the session token used by the goal planner). */
    client,
    language,
    setLanguage,
    response,
    state: response?.state ?? null,
    messages,
    loading,
    error,
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
