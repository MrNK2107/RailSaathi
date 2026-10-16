import { useEffect, type FormEvent, type RefObject } from 'react'
import type { MicState } from '../../hooks/useSpeech'
import { ArrowRight, StopIcon } from '../icons'
import { useApp } from '../PlannerContext'
import { VOICE_ART } from '../voiceAssets'
import { Picture } from './VoiceHero'

interface Props {
  draft: string
  onDraft: (text: string) => void
  onSubmit: () => void
  sending: boolean
  inputRef: RefObject<HTMLTextAreaElement>
  /** True while any mic (hero or composer) is recording: the transcript must be reviewed before sending. */
  listening: boolean
  /** Mic in the composer (shown once the big hero mic has gone). */
  mic?: { state: MicState; onToggle: () => void }
}

const MAX_ROWS_PX = 128

/** Message bar pinned to the bottom of the chat: optional mic, growing textarea, round send button. */
export function Composer({ draft, onDraft, onSubmit, sending, inputRef, listening, mic }: Props) {
  const { m } = useApp()
  const canSend = draft.trim().length > 0 && !sending && !listening

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (canSend) onSubmit()
  }

  const grow = (el: HTMLTextAreaElement) => {
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, MAX_ROWS_PX)}px`
  }
  const empty = draft.length === 0

  // Back to one line once the box is cleared (after Send, or a new plan), so the placeholder never sits in a tall box.
  useEffect(() => {
    if (empty && inputRef.current) inputRef.current.style.height = ''
  }, [empty, inputRef])

  return (
    <form onSubmit={submit} aria-label={m.plan.composer} className="flex items-end gap-2">
      {mic && (
        <button type="button" onClick={mic.onToggle} disabled={mic.state === 'unsupported' || mic.state === 'processing'}
          aria-label={listening ? m.plan.stopVoice : m.plan.startVoice} aria-pressed={listening} data-state={mic.state}
          className="relative h-12 w-12 shrink-0 rounded-full disabled:cursor-not-allowed">
          {listening && <span aria-hidden className="absolute inset-1 animate-ping rounded-full ring-2 ring-red-400/70 motion-reduce:animate-none" />}
          <Picture art={VOICE_ART.micButton} alt="" className={`relative h-full w-full object-contain ${mic.state === 'unsupported' ? 'opacity-40 grayscale' : ''}`} />
          {listening && (
            <span className="absolute -bottom-0.5 -right-0.5 grid h-5 w-5 place-items-center rounded-full bg-red-600 text-white shadow-card"><StopIcon size={10} /></span>
          )}
        </button>
      )}
      <div className="flex min-w-0 flex-1 items-end gap-1 rounded-3xl border border-ink-300 bg-white px-3 py-0.5 shadow-card focus-within:border-brand-500">
        {/* While empty the box is exactly one line: the placeholder is cut with an ellipsis, never wrapped or scrolled. */}
        <label htmlFor="voice-input" className="sr-only">{m.plan.inputLabel}</label>
        <textarea id="voice-input" ref={inputRef} rows={1} maxLength={1000} value={draft}
          onChange={(e) => { onDraft(e.target.value); grow(e.target) }}
          placeholder={m.plan.inputPlaceholder}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (canSend) onSubmit() } }}
          data-empty={empty || undefined}
          className={`max-h-32 min-w-0 flex-1 resize-none bg-transparent py-1.5 text-sm text-ink-900 outline-none placeholder:text-ink-500 ${
            empty ? 'overflow-hidden text-ellipsis whitespace-nowrap placeholder:text-ellipsis placeholder:whitespace-nowrap' : ''}`} />
        <button type="submit" disabled={!canSend} aria-label={m.plan.send}
          className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-brand-600 text-white transition hover:bg-brand-700 disabled:opacity-40">
          <ArrowRight size={18} className="-rotate-90" />
        </button>
      </div>
    </form>
  )
}
