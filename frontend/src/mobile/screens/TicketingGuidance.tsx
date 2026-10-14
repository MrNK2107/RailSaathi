// Ticketing guidance chat (POST /api/chat). Answers are rendered as PLAIN TEXT (React escapes everything; no markdown
// or HTML) and every link must pass the official-domain allowlist before it becomes a live anchor.
import { useRef, useState, type FormEvent, type ReactNode } from 'react'
import { ApiError } from '../../api/client'
import type { TicketingLink, TicketingResponse, TicketingSource } from '../../api/types'
import { ProvenanceBadge } from '../../components/ProvenanceBadge'
import { officialUrl } from '../../utils/officialLinks'
import { AlertIcon, ArrowRight } from '../icons'
import { useApp } from '../PlannerContext'
import { AppHeader, PrimaryButton, Screen } from '../ui'

type Turn =
  | { kind: 'user'; id: number; text: string }
  | { kind: 'assistant'; id: number; res: TicketingResponse }

/** A live anchor only for allowlisted https URLs; anything else degrades to plain text. */
function ExternalLink({ url, children }: { url: string; children: ReactNode }) {
  const safe = officialUrl(url)
  if (!safe) return <>{children}</>
  return (
    <a href={safe} target="_blank" rel="noopener noreferrer" className="font-semibold text-brand-700 underline">
      {children}
    </a>
  )
}

function Sources({ sources }: { sources: TicketingSource[] }) {
  const { m } = useApp()
  if (sources.length === 0) return null
  return (
    <div className="mt-3">
      <p className="text-xs font-bold text-ink-700">{m.ticketing.sources}</p>
      <ul className="mt-1 space-y-1 text-xs text-ink-700">
        {sources.map((s) => (
          <li key={s.source_id}>
            <ExternalLink url={s.url}>{s.title || s.publisher}</ExternalLink>
            {s.as_of && <span className="text-ink-500"> · {m.ticketing.asOf} {s.as_of.slice(0, 10)}</span>}
          </li>
        ))}
      </ul>
    </div>
  )
}

function OfficialLinks({ links }: { links: TicketingLink[] }) {
  const { m } = useApp()
  const safe = links.filter((l) => officialUrl(l.url))
  if (safe.length === 0) return null
  return (
    <div className="mt-3">
      <p className="text-xs font-bold text-red-900">{m.ticketing.officialLinks}</p>
      <ul className="mt-1 space-y-1">
        {safe.map((l) => (
          <li key={l.url}>
            <a href={officialUrl(l.url) ?? undefined} target="_blank" rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs font-semibold text-brand-700 underline">
              {l.title} <ArrowRight size={12} />
            </a>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Answer({ res }: { res: TicketingResponse }) {
  const { m } = useApp()
  const provenance = res.provenance
  if (res.status === 'unavailable') {
    return (
      <article data-testid="ticketing-unavailable" aria-label={m.ticketing.assistant}>
        <ProvenanceBadge provenance={provenance} variant="full" unavailableTitle={m.ticketing.unavailableTitle} />
        <p className="mt-2 whitespace-pre-wrap text-sm text-ink-900">{res.answer}</p>
        <OfficialLinks links={res.links ?? []} />
      </article>
    )
  }
  return (
    <article aria-label={m.ticketing.assistant}>
      <p data-testid="ticketing-answer" className="whitespace-pre-wrap break-words text-sm text-ink-900">{res.answer}</p>
      {!res.evidence_sufficient && (
        <p className="mt-2 rounded-lg bg-amber-50 p-2 text-xs text-amber-900">{m.ticketing.weakEvidence}</p>
      )}
      <Sources sources={res.sources} />
      <ProvenanceBadge provenance={provenance} variant="full" className="mt-3" unavailableTitle={m.ticketing.unavailableTitle} />
    </article>
  )
}

export default function TicketingGuidance() {
  const { planner, m } = useApp()
  const [turns, setTurns] = useState<Turn[]>([])
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const conversationId = useRef<string | undefined>(undefined)
  const nextId = useRef(0)

  const ask = async (message: string): Promise<TicketingResponse> => {
    // Chat is bound to the planner session token, so make sure a session exists first.
    if (!planner.response) await planner.restart()
    const body = { message, ...(conversationId.current ? { conversation_id: conversationId.current } : {}) }
    try {
      return await planner.client.ticketing(body)
    } catch (err) {
      if (!(err instanceof ApiError && err.code === 'invalid_session_token')) throw err
      // A new session cannot see the old conversation (history is bound to the session token), so start a fresh one.
      await planner.restart()
      conversationId.current = undefined
      return await planner.client.ticketing({ message })
    }
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const message = text.trim()
    if (!message || busy) return
    setBusy(true)
    setError(null)
    setText('')
    setTurns((t) => [...t, { kind: 'user', id: nextId.current++, text: message }])
    try {
      const res = await ask(message)
      conversationId.current = res.conversation_id
      setTurns((t) => [...t, { kind: 'assistant', id: nextId.current++, res }])
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Screen>
      <AppHeader />
      <div className="space-y-4 p-4">
        <h1 className="text-2xl font-extrabold text-brand-900">{m.ticketing.title}</h1>
        <p className="text-sm text-ink-700">{m.ticketing.intro}</p>
        <p data-testid="ticketing-notice" className="rounded-xl bg-amber-50 p-3 text-xs font-semibold text-amber-900">
          {m.ticketing.notice}
        </p>

        <ol className="space-y-3" aria-live="polite">
          {turns.map((t) => (
            <li key={t.id} className={`rounded-2xl p-4 shadow-card ring-1 ring-ink-100 ${t.kind === 'user' ? 'bg-brand-50' : 'bg-white'}`}>
              {t.kind === 'user'
                ? <p className="whitespace-pre-wrap break-words text-sm text-ink-900"><span className="sr-only">{m.ticketing.you}: </span>{t.text}</p>
                : <Answer res={t.res} />}
            </li>
          ))}
        </ol>

        {error && (
          <div role="alert" className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            <AlertIcon size={18} className="mt-0.5 shrink-0" /> <span>{error}</span>
          </div>
        )}

        <form onSubmit={submit} className="space-y-3 rounded-2xl bg-white p-4 shadow-card ring-1 ring-ink-100">
          <label className="block text-xs font-semibold text-ink-700">{m.ticketing.inputLabel}
            <textarea className="mt-1 w-full rounded-xl border border-ink-300 px-3 py-2 text-sm" rows={3} maxLength={10000}
              value={text} placeholder={m.ticketing.placeholder} onChange={(e) => setText(e.target.value)} />
          </label>
          <PrimaryButton type="submit" disabled={busy || !text.trim()}>{busy ? m.ticketing.sending : m.ticketing.send}</PrimaryButton>
        </form>
      </div>
    </Screen>
  )
}
