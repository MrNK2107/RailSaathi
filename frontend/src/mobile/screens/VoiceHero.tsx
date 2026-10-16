import type { MicPermission } from '../../hooks/useMicPermission'
import type { MicErrorCode, MicState } from '../../hooks/useSpeech'
import { AlertIcon, CheckCircle, StopIcon } from '../icons'
import { useApp } from '../PlannerContext'
import { SPEECH_OPTIONS, type MobileStrings, type SpeechOptionId } from '../strings'
import { VOICE_ART, type Art } from '../voiceAssets'

export interface MicProps {
  micState: MicState
  /** Why the microphone failed, when micState is 'error'. */
  errorCode: MicErrorCode | null
  permission: MicPermission
  /** A voice transcript is in the box, waiting for the user to check and send it. */
  transcriptReady: boolean
  speech: SpeechOptionId
  onSpeechChange: (id: SpeechOptionId) => void
  onMicToggle: () => void
}

type DataAttrs = { 'data-testid'?: string; 'data-listening'?: string }

export function Picture({ art, alt, className, ...rest }: { art: Art; alt: string; className?: string } & DataAttrs) {
  return (
    <picture>
      <source srcSet={art.webp} type="image/webp" />
      <img src={art.png} alt={alt} width={art.width} height={art.height} decoding="async" className={className} {...rest} />
    </picture>
  )
}

export function VoiceWave({ listening, mirrored, size = 'md' }: { listening: boolean; mirrored?: boolean; size?: 'sm' | 'md' }) {
  return (
    <span aria-hidden className={`block min-w-0 flex-1 ${mirrored ? 'scale-x-[-1]' : ''}`}>
      <Picture art={VOICE_ART.voiceWave} alt="" data-testid="voice-wave" data-listening={String(listening)}
        className={`mx-auto w-full object-contain drop-shadow transition-opacity duration-300 ${size === 'sm' ? 'h-6 max-w-[110px]' : 'h-10 max-w-[150px]'} ${listening ? 'animate-wave opacity-100' : 'opacity-70'}`} />
    </span>
  )
}

export type Tone = 'neutral' | 'listening' | 'processing' | 'success' | 'error'
export const TONE_CLASS: Record<Tone, string> = {
  neutral: 'text-ink-900',
  listening: 'text-brand-700',
  processing: 'text-amber-800',
  success: 'text-match-700',
  error: 'text-red-700',
}

/** One line describing the microphone, chosen from the real recognition + permission state. */
export function micStatus(
  p: MobileStrings['plan'], micState: MicState, errorCode: MicErrorCode | null, permission: MicPermission, transcriptReady: boolean,
): [Tone, string] {
  if (micState === 'unsupported') return ['error', p.micUnsupported]
  if (micState === 'error') return ['error', p.micErrors[errorCode ?? 'start_failed']]
  if (permission === 'denied') return ['error', p.permissionDenied]
  if (micState === 'listening') return ['listening', p.listening]
  if (micState === 'processing') return ['processing', p.processing]
  if (transcriptReady) return ['success', p.transcriptReady]
  if (permission === 'prompt') return ['neutral', p.permissionPrompt]
  return ['neutral', p.tapToSpeak]
}

export function StatusLine({ tone, text, compact = false }: { tone: Tone; text: string; compact?: boolean }) {
  return (
    <p role="status" aria-live="polite"
      className={`mx-auto flex w-fit max-w-full items-start justify-center gap-1.5 rounded-2xl bg-white/90 shadow-card backdrop-blur ${compact ? 'px-3 py-1 text-xs' : 'px-4 py-2 text-sm'} font-medium ${TONE_CLASS[tone]}`}>
      {tone === 'success' && <CheckCircle size={compact ? 14 : 16} className="mt-0.5 shrink-0" />}
      {tone === 'error' && <AlertIcon size={compact ? 14 : 16} className="mt-0.5 shrink-0" />}
      <span>{text}</span>
    </p>
  )
}

export function SpeechSelector({ speech, onSpeechChange, disabled, compact = false }: {
  speech: SpeechOptionId; onSpeechChange: (id: SpeechOptionId) => void; disabled: boolean; compact?: boolean
}) {
  const { m } = useApp()
  return (
    <div role="group" aria-label={m.plan.speakIn} className="inline-flex max-w-full rounded-full bg-white/90 p-1 shadow-card ring-1 ring-brand-100 backdrop-blur">
      {SPEECH_OPTIONS.map((o) => (
        <button key={o.id} type="button" onClick={() => onSpeechChange(o.id)} disabled={disabled} aria-pressed={speech === o.id}
          className={`rounded-full font-semibold transition-colors disabled:opacity-60 ${compact ? 'min-h-11 px-3 text-xs' : 'min-h-11 px-4 text-sm'} ${speech === o.id ? 'bg-brand-600 text-white' : 'text-brand-700 hover:bg-brand-50'}`}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

/** Opening hero: the robot, voice waves and supplied mic button laid directly over the station photo. */
export function VoiceHero({ micState, errorCode, permission, transcriptReady, speech, onSpeechChange, onMicToggle }: MicProps) {
  const { m } = useApp()
  const p = m.plan
  const listening = micState === 'listening'
  const processing = micState === 'processing'
  const [tone, status] = micStatus(p, micState, errorCode, permission, transcriptReady)

  const micImageClass = [
    'relative h-full w-full object-contain drop-shadow-lg transition-transform duration-300',
    listening ? 'scale-105' : 'hover:scale-105',
    micState === 'unsupported' ? 'opacity-40 grayscale' : '',
  ].join(' ')

  return (
    <section data-testid="voice-hero" data-bg={VOICE_ART.background.png} aria-labelledby="voice-title"
      className="relative overflow-hidden bg-brand-100">
      <Picture art={VOICE_ART.background} alt="" className="absolute inset-0 h-full w-full object-cover object-[center_70%]" />
      {/* Readability only: light at the top for the heading, fading to the page colour at the bottom. */}
      <div aria-hidden className="absolute inset-0 bg-gradient-to-b from-white/80 via-white/10 to-white" />

      <div className="relative px-4 pb-3 pt-4 text-center">
        <h1 id="voice-title" className="text-2xl font-extrabold text-brand-900">{p.title}</h1>
        <p className="mt-1 text-sm font-medium text-ink-900">{p.subtitle}</p>

        <div className="relative mt-4 flex items-center justify-center gap-1">
          <VoiceWave listening={listening} mirrored />
          <Picture art={VOICE_ART.robot} alt={p.robotAlt}
            className={`relative h-44 w-auto shrink-0 object-contain drop-shadow-xl transition-transform duration-500 ${listening ? 'scale-105' : ''}`} />
          <VoiceWave listening={listening} />
        </div>

        <button type="button" onClick={onMicToggle} disabled={micState === 'unsupported' || processing}
          aria-label={listening ? p.stopVoice : p.startVoice} aria-pressed={listening} data-state={micState}
          className="relative mx-auto -mt-4 block h-32 w-28 rounded-full outline-offset-4 disabled:cursor-not-allowed">
          {listening && <span aria-hidden className="absolute inset-5 animate-ping rounded-full ring-4 ring-red-400/70 motion-reduce:animate-none" />}
          <Picture art={VOICE_ART.micButton} alt="" className={micImageClass} />
          {listening && (
            <span className="absolute inset-x-0 bottom-2 mx-auto flex w-fit items-center gap-1 rounded-full bg-red-600 px-2.5 py-0.5 text-[11px] font-bold text-white shadow-card">
              <StopIcon size={11} /> {p.stop}
            </span>
          )}
          {processing && (
            <span aria-hidden className="absolute inset-x-0 bottom-2 mx-auto block h-5 w-5 animate-spin rounded-full border-2 border-amber-500 border-t-transparent motion-reduce:animate-none" />
          )}
          {(micState === 'error' || permission === 'denied') && micState !== 'unsupported' && (
            <span className="absolute right-3 top-6 grid h-6 w-6 place-items-center rounded-full bg-red-600 text-white shadow-card"><AlertIcon size={14} /></span>
          )}
        </button>

        <div className="mt-1"><StatusLine tone={tone} text={status} /></div>
        <div className="mt-3"><SpeechSelector speech={speech} onSpeechChange={onSpeechChange} disabled={listening} /></div>
      </div>
    </section>
  )
}
