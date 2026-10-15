import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { useSpeechRecognition } from '../../hooks/useSpeech'
import { STRINGS } from '../../i18n/strings'
import { MicIcon, RefreshIcon, StopIcon } from '../icons'
import { useApp } from '../PlannerContext'
import { SPEECH_OPTIONS, VOICE_EXAMPLES } from '../strings'
import { AppHeader, ErrorBanner, PrimaryButton, Screen } from '../ui'
import { ExtractedDetails } from './ExtractedDetails'
import { ProgressSteps } from './ProgressSteps'

function Avatar({ listening }: { listening: boolean }) {
  const bars = [10, 18, 26, 14, 30, 20, 12]
  return (
    <div className="relative mx-auto flex h-36 w-full items-center justify-center" aria-hidden>
      {[-1, 1].map((side) => (
        <div key={side} className={`absolute flex items-center gap-1 ${side < 0 ? 'left-4' : 'right-4'}`}>
          {bars.map((h, i) => (
            <span key={i} className={`w-1 rounded-full bg-brand-500 ${listening ? 'animate-pulse' : 'opacity-40'}`}
              style={{ height: h, animationDelay: `${i * 90}ms` }} />
          ))}
        </div>
      ))}
      <svg viewBox="0 0 120 120" className="h-32 w-32">
        <circle cx="60" cy="60" r="56" fill="#dbe7ff" />
        <circle cx="60" cy="60" r="44" fill="#ffffff" stroke="#bcd2ff" strokeWidth="3" />
        <rect x="30" y="38" width="60" height="42" rx="18" fill="#1a56db" />
        <rect x="38" y="46" width="44" height="26" rx="12" fill="#0f2a6b" />
        <circle cx="50" cy="59" r="5" fill="#7dd3fc" /><circle cx="70" cy="59" r="5" fill="#7dd3fc" />
        <rect x="22" y="52" width="8" height="16" rx="4" fill="#1a56db" /><rect x="90" y="52" width="8" height="16" rx="4" fill="#1a56db" />
        <rect x="57" y="26" width="6" height="12" rx="3" fill="#1a56db" />
      </svg>
    </div>
  )
}

export default function VoiceAgent() {
  const { planner, go, m } = useApp()
  const lang = planner.language
  const state = planner.state
  const [draft, setDraft] = useState('')
  const [fromVoice, setFromVoice] = useState(false)
  // The recognition language follows the UI language; a manual choice applies only until the UI language changes.
  const [picked, setPicked] = useState<{ ui: string; code: string } | null>(null)
  const speechLang = picked && picked.ui === lang ? picked.code : lang === 'ta' ? 'ta-IN' : 'en-IN'
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const listRef = useRef<HTMLOListElement>(null)

  const onTranscript = useCallback((text: string) => {
    setDraft(text)
    setFromVoice(true)
  }, [])
  const mic = useSpeechRecognition(speechLang, onTranscript)
  const listening = mic.state === 'listening'

  useEffect(() => {
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [planner.messages])

  const submit = async (e?: FormEvent) => {
    e?.preventDefault()
    const text = draft.trim()
    if (!text || planner.loading || listening) return
    setDraft('')
    setFromVoice(false)
    await planner.send(text)
  }

  const hasDetails = Boolean(state && (state.journey.origin || state.journey.destination))
  const resultsReady = Boolean(state && ['presenting_recommendations', 'awaiting_confirmation', 'no_feasible_options', 'confirmed']
    .includes(state.status))
  const source = planner.response?.extraction?.source

  return (
    <Screen footer={resultsReady ? (
      <PrimaryButton onClick={() => go('options')}>{m.plan.viewOptions}</PrimaryButton>
    ) : undefined}>
      <AppHeader right={(
        <button type="button" onClick={() => planner.restart()} disabled={planner.loading}
          className="inline-flex items-center gap-1 rounded-full border border-ink-300 px-3 py-1 text-xs font-semibold text-brand-700">
          <RefreshIcon size={14} /> {m.plan.newPlan}
        </button>
      )} />

      <section className="px-4 pt-4 text-center">
        <h1 className="text-2xl font-extrabold text-brand-900">{m.plan.title}</h1>
        <p className="mt-1 text-sm text-ink-500">{m.plan.subtitle}</p>
        <Avatar listening={listening} />

        <button type="button" onClick={() => (listening ? mic.stop() : mic.start(draft))}
          disabled={mic.state === 'unsupported' || mic.state === 'processing'}
          aria-label={listening ? m.plan.stopVoice : m.plan.startVoice} aria-pressed={listening}
          className={`mx-auto -mt-2 grid h-20 w-20 place-items-center rounded-full text-white shadow-card ring-8 transition
            ${listening ? 'bg-red-600 ring-red-100' : 'bg-brand-600 ring-brand-100 hover:bg-brand-700'}
            disabled:cursor-not-allowed disabled:bg-ink-300 disabled:ring-ink-100`}>
          {listening ? <StopIcon size={30} /> : <MicIcon size={34} />}
        </button>
        <p className="mt-3 text-sm font-medium text-ink-700" role="status">
          {listening ? m.plan.listening : mic.state === 'unsupported' ? m.plan.micUnsupported
            : mic.state === 'error' ? m.plan.micErrors[mic.errorCode ?? 'start_failed'] : m.plan.tapToSpeak}
        </p>

        <label className="mx-auto mt-3 inline-flex items-center gap-2 rounded-full bg-brand-50 px-3 py-1.5 text-sm font-semibold text-brand-700">
          <span className="sr-only">{m.plan.speakIn}</span>
          <select value={speechLang} onChange={(e) => setPicked({ ui: lang, code: e.target.value })} disabled={listening}
            aria-label={m.plan.speakIn} className="bg-transparent font-semibold outline-none">
            {SPEECH_OPTIONS.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
          </select>
        </label>
      </section>

      <form onSubmit={submit} className="px-4 pt-4">
        <label htmlFor="voice-input" className="sr-only">{m.plan.inputLabel}</label>
        {fromVoice && !listening && <p className="mb-1 text-xs font-medium text-amber-800">{m.plan.reviewTranscript}</p>}
        <div className="flex items-end gap-2 rounded-2xl border border-ink-300 bg-white p-2 focus-within:border-brand-500">
          <textarea id="voice-input" ref={inputRef} rows={2} maxLength={1000} value={draft}
            onChange={(e) => setDraft(e.target.value)} placeholder={m.plan.inputPlaceholder}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void submit() } }}
            className="flex-1 resize-none bg-transparent px-1 text-sm text-ink-900 outline-none" />
          <button type="submit" disabled={!draft.trim() || planner.loading || listening}
            className="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
            {m.plan.send}
          </button>
        </div>
      </form>

      <ErrorBanner />

      {!hasDetails && (
        <section aria-label={m.plan.tryExamples} className="space-y-2 px-4 pt-4">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-ink-500">{m.plan.tryExamples}</h2>
          {VOICE_EXAMPLES[lang].map((ex) => (
            <button key={ex} type="button" onClick={() => { setDraft(ex); inputRef.current?.focus() }}
              className="block w-full rounded-2xl bg-brand-50 p-3 text-left text-sm text-brand-900 ring-1 ring-brand-100 hover:bg-brand-100">
              “{ex}”
            </button>
          ))}
        </section>
      )}

      {planner.messages.length > 0 && (
        <section aria-label={m.plan.conversation} className="px-4 pt-4">
          <ol ref={listRef} role="log" aria-live="polite" aria-label={m.plan.conversation} className="max-h-64 space-y-2 overflow-y-auto">
            {planner.messages.slice(-8).map((msg) => (
              <li key={msg.id} className={msg.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
                <p className={`max-w-[88%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm ${
                  msg.role === 'user' ? 'bg-brand-600 text-white'
                    : msg.role === 'system' ? 'bg-amber-50 text-amber-900' : 'bg-ink-100 text-ink-900'}`}>
                  {msg.text}
                </p>
              </li>
            ))}
            {planner.loading && <li className="text-sm text-ink-500" role="status">…</li>}
          </ol>
          {source && <p className="mt-1 text-[11px] text-ink-500">{source === 'rules' ? m.plan.understoodBy.rules : m.plan.understoodBy.ai}</p>}
        </section>
      )}

      {state && hasDetails && (
        <>
          <ExtractedDetails state={state} t={STRINGS[lang]} disabled={planner.loading} onPatch={planner.patch} />
          <ProgressSteps state={state} />
        </>
      )}
      <div className="h-6" />
    </Screen>
  )
}
