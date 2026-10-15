import { useCallback, useEffect, useRef, useState } from 'react'

// Minimal typings for the (non-standard) Web Speech recognition API.
interface RecognitionResultEvent {
  results: ArrayLike<ArrayLike<{ transcript: string; confidence: number }> & { isFinal: boolean }>
}
interface Recognition {
  lang: string
  interimResults: boolean
  continuous: boolean
  start(): void
  stop(): void
  abort(): void
  onresult: ((e: RecognitionResultEvent) => void) | null
  onerror: ((e: { error: string }) => void) | null
  onend: (() => void) | null
}
type RecognitionCtor = new () => Recognition

export type MicState = 'idle' | 'listening' | 'processing' | 'error' | 'unsupported'

/** Why voice input failed. Each code has its own message in the string tables (`plan.micErrors`, `mic.errors`). */
export type MicErrorCode =
  | 'insecure'
  | 'not_allowed'
  | 'no_microphone'
  | 'network'
  | 'language_unsupported'
  | 'service_unavailable'
  | 'start_failed'
  | 'restart_limit'

/** Browser error names that mean the mic cannot be used at all (stop instead of auto-restarting), with our code. */
const FATAL_ERRORS: Record<string, MicErrorCode> = {
  'not-allowed': 'not_allowed',
  'service-not-allowed': 'service_unavailable',
  'audio-capture': 'no_microphone',
  network: 'network',
  'language-not-supported': 'language_unsupported',
}

/**
 * Browsers end a continuous session after a pause. The hook restarts it, but gives up after this many restarts in a
 * row that produced no speech at all, so a silent or broken engine cannot loop forever.
 */
export const MAX_EMPTY_RESTARTS = 6

function getRecognition(): RecognitionCtor | null {
  const w = globalThis as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

const join = (...parts: string[]) => parts.map((p) => p.trim()).filter(Boolean).join(' ')

/**
 * Voice input that keeps listening until the user presses Stop.
 * Browsers end a recognition session after a pause, so the hook restarts it
 * automatically while the user still wants to listen, keeping the words so far.
 * The live transcript is passed to onTranscript for review; it is never auto-submitted.
 */
export function useSpeechRecognition(lang: string, onTranscript: (text: string) => void) {
  const Ctor = getRecognition()
  const [state, setState] = useState<MicState>(Ctor ? 'idle' : 'unsupported')
  const [errorCode, setErrorCode] = useState<MicErrorCode | null>(null)
  const recRef = useRef<Recognition | null>(null)
  const emptyRestartsRef = useRef(0) // consecutive restarts that heard nothing
  const wantRef = useRef(false) // true between the user's Start and Stop presses
  const committedRef = useRef('') // text from earlier, already-ended sessions
  const sessionRef = useRef('') // final text from the current session

  useEffect(() => () => {
    wantRef.current = false
    recRef.current?.abort()
  }, [])

  const listen = useCallback(() => {
    if (!Ctor) return
    const rec = new Ctor()
    rec.lang = lang
    rec.interimResults = true
    rec.continuous = true
    sessionRef.current = ''
    rec.onresult = (e) => {
      emptyRestartsRef.current = 0
      let finalText = ''
      let interim = ''
      for (const result of Array.from(e.results)) {
        const text = result[0]?.transcript ?? ''
        if (result.isFinal) finalText = join(finalText, text)
        else interim = join(interim, text)
      }
      sessionRef.current = finalText
      onTranscript(join(committedRef.current, finalText, interim))
    }
    rec.onerror = (e) => {
      const code = FATAL_ERRORS[e.error]
      if (code) {
        wantRef.current = false
        setErrorCode(code)
        setState('error')
      }
      // 'no-speech' and 'aborted' are harmless: onend restarts or finishes.
    }
    rec.onend = () => {
      committedRef.current = join(committedRef.current, sessionRef.current)
      sessionRef.current = ''
      if (wantRef.current) {
        emptyRestartsRef.current += 1 // any result in this session has reset the counter
        if (emptyRestartsRef.current > MAX_EMPTY_RESTARTS) {
          wantRef.current = false
          setErrorCode('restart_limit')
          setState('error')
          onTranscript(committedRef.current)
          return
        }
        listen() // browser stopped on its own (pause/timeout): keep listening
        return
      }
      onTranscript(committedRef.current)
      setState((s) => (s === 'error' ? 'error' : 'idle'))
    }
    recRef.current = rec
    try {
      rec.start()
      setState('listening')
    } catch {
      wantRef.current = false
      setErrorCode('start_failed')
      setState('error')
    }
  }, [Ctor, lang, onTranscript])

  const start = useCallback((existingText = '') => {
    // Browsers only give the microphone to secure contexts (https or localhost).
    if (typeof window !== 'undefined' && window.isSecureContext === false) {
      setErrorCode('insecure')
      setState('error')
      return
    }
    setErrorCode(null)
    emptyRestartsRef.current = 0
    wantRef.current = true
    committedRef.current = existingText.trim()
    listen()
  }, [listen])

  const stop = useCallback(() => {
    wantRef.current = false
    setState('processing')
    recRef.current?.stop()
  }, [])

  return { state, errorCode, start, stop, supported: Boolean(Ctor) }
}

/** Does the browser offer a voice for `lang` (exact tag, or the same language such as any `ta-*`)? */
export function hasVoiceFor(voices: readonly { lang: string }[], lang: string): boolean {
  const want = lang.toLowerCase()
  const primary = want.split('-')[0]
  return voices.some((v) => {
    const have = v.lang.toLowerCase().replace('_', '-')
    return have === want || have.split('-')[0] === primary
  })
}

export type VoiceStatus = 'unknown' | 'available' | 'missing'

/**
 * Optional read-aloud. Never blocks the main workflow. Speaking a language the device has no voice for would be read
 * with the wrong (usually English) voice, so `voice` reports `missing` once the browser has listed its voices and
 * none matches; until then (some browsers list voices late or never) it is `unknown` and speaking is allowed.
 */
export function useSpeechSynthesis(lang: string) {
  const supported = typeof window !== 'undefined' && 'speechSynthesis' in window
  const [speaking, setSpeaking] = useState(false)
  const [voices, setVoices] = useState<readonly { lang: string }[]>(() => (supported ? window.speechSynthesis.getVoices() : []))

  useEffect(() => {
    if (!supported) return undefined
    const synth = window.speechSynthesis
    const refresh = () => setVoices(synth.getVoices())
    refresh()
    synth.addEventListener?.('voiceschanged', refresh)
    return () => synth.removeEventListener?.('voiceschanged', refresh)
  }, [supported])

  const voice: VoiceStatus = voices.length === 0 ? 'unknown' : hasVoiceFor(voices, lang) ? 'available' : 'missing'

  const speak = useCallback((text: string) => {
    if (!supported || !text || voice === 'missing') return
    window.speechSynthesis.cancel()
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.lang = lang
    utterance.onend = () => setSpeaking(false)
    utterance.onerror = () => setSpeaking(false)
    setSpeaking(true)
    window.speechSynthesis.speak(utterance)
  }, [lang, supported, voice])

  const stop = useCallback(() => {
    if (supported) window.speechSynthesis.cancel()
    setSpeaking(false)
  }, [supported])

  return { supported, speaking, voice, speak, stop }
}
