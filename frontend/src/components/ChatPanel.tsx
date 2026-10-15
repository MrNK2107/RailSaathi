import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import type { Language } from '../api/types'
import type { ChatMessage } from '../hooks/usePlanner'
import { useSpeechRecognition, useSpeechSynthesis } from '../hooks/useSpeech'
import { EXAMPLES, SPEECH_LANG, type Strings } from '../i18n/strings'
import { MicButton } from './MicButton'

interface Props {
  t: Strings
  language: Language
  messages: ChatMessage[]
  loading: boolean
  error: string | null
  canRetry: boolean
  onSend: (text: string) => void
  onRetry: () => void
  onRestart: () => void
  onCancel: () => void
}

export function ChatPanel({ t, language, messages, loading, error, canRetry, onSend, onRetry, onRestart, onCancel }: Props) {
  const [draft, setDraft] = useState('')
  const [fromVoice, setFromVoice] = useState(false)
  const listRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const handleTranscript = useCallback((text: string) => {
    setDraft(text)
    setFromVoice(true)
    inputRef.current?.focus()
  }, [])
  const mic = useSpeechRecognition(SPEECH_LANG[language], handleTranscript)
  const tts = useSpeechSynthesis(SPEECH_LANG[language])

  useEffect(() => {
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages])

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const text = draft.trim()
    if (!text || loading) return
    onSend(text)
    setDraft('')
    setFromVoice(false)
  }

  const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant')

  return (
    <section aria-labelledby="chat-title" className="flex h-full flex-col rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <h2 id="chat-title" className="font-semibold text-slate-800">{t.chatTitle}</h2>
        <div className="flex gap-2 text-sm">
          {tts.supported && lastAssistant && (
            <button
              type="button"
              disabled={tts.voice === 'missing'}
              title={tts.voice === 'missing' ? t.noVoice : undefined}
              onClick={() => (tts.speaking ? tts.stop() : tts.speak(lastAssistant.text))}
              className="rounded border border-slate-300 px-2 py-1 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {tts.speaking ? t.stopReading : t.readAloud}
            </button>
          )}
          <button type="button" onClick={onRestart} className="rounded border border-slate-300 px-2 py-1 hover:bg-slate-50">
            {t.newPlan}
          </button>
          <button type="button" onClick={onCancel} className="rounded border border-red-200 px-2 py-1 text-red-700 hover:bg-red-50">
            {t.cancelPlan}
          </button>
        </div>
      </div>

      <div ref={listRef} role="log" aria-live="polite" className="min-h-[260px] flex-1 space-y-3 overflow-y-auto px-4 py-3" aria-label={t.chatTitle}>
        {messages.map((m) => (
          <div key={m.id} className={m.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
            <p
              className={
                m.role === 'user'
                  ? 'max-w-[85%] whitespace-pre-wrap rounded-lg bg-rail-600 px-3 py-2 text-white'
                  : m.role === 'system'
                    ? 'max-w-[85%] rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900'
                    : 'max-w-[85%] whitespace-pre-wrap rounded-lg bg-slate-100 px-3 py-2 text-slate-800'
              }
            >
              {m.text}
            </p>
          </div>
        ))}
        {loading && <p className="text-sm text-slate-500" role="status">{t.thinking}</p>}
      </div>

      {error && (
        <div role="alert" className="mx-4 mb-2 flex items-center justify-between rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          <span>{error}</span>
          {canRetry && (
            <button type="button" onClick={onRetry} className="ml-2 rounded border border-red-300 px-2 py-0.5">
              {t.errors.retry}
            </button>
          )}
        </div>
      )}

      {messages.length <= 1 && (
        <div className="px-4 pb-2">
          <p className="mb-1 text-xs font-medium uppercase text-slate-500">{t.examples}</p>
          <div className="flex flex-wrap gap-2">
            {EXAMPLES[language].map((ex) => (
              <button key={ex} type="button" onClick={() => setDraft(ex)}
                className="rounded-full border border-rail-100 bg-rail-50 px-3 py-1 text-left text-sm text-rail-700 hover:bg-rail-100">
                {ex}
              </button>
            ))}
          </div>
        </div>
      )}

      <form onSubmit={submit} className="border-t border-slate-200 p-3">
        <label htmlFor="chat-input" className="sr-only">{t.inputLabel}</label>
        {mic.state === 'listening' && (
          <p className="mb-1 text-xs font-medium text-red-700" role="status">{t.mic.listeningHint}</p>
        )}
        {fromVoice && mic.state !== 'listening' && <p className="mb-1 text-xs text-amber-800">{t.mic.review}</p>}
        <div className="flex items-end gap-2">
          <textarea
            id="chat-input"
            ref={inputRef}
            rows={2}
            maxLength={1000}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) submit(e)
            }}
            placeholder={t.inputPlaceholder}
            className="flex-1 resize-none rounded border border-slate-300 px-3 py-2 text-slate-900"
          />
          <MicButton t={t} state={mic.state} onStart={() => mic.start(draft)} onStop={mic.stop} />
          <button type="submit" disabled={loading || !draft.trim() || mic.state === 'listening'}
            className="rounded bg-rail-600 px-4 py-2 font-medium text-white hover:bg-rail-700 disabled:cursor-not-allowed disabled:opacity-50">
            {t.send}
          </button>
        </div>
        {mic.state === 'unsupported' && <p className="mt-1 text-xs text-slate-500">{t.mic.unsupported}</p>}
        {mic.state === 'error' && <p className="mt-1 text-xs text-red-700" role="alert">{t.mic.errors[mic.errorCode ?? 'start_failed']}</p>}
        {tts.supported && tts.voice === 'missing' && <p className="mt-1 text-xs text-slate-500">{t.noVoice}</p>}
      </form>
    </section>
  )
}
