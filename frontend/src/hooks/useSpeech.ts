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

// Errors that mean the mic cannot be used at all; stop instead of auto-restarting.
const FATAL_ERRORS = new Set(['not-allowed', 'service-not-allowed', 'audio-capture', 'network', 'language-not-supported'])

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
  const recRef = useRef<Recognition | null>(null)
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
      if (FATAL_ERRORS.has(e.error)) {
        wantRef.current = false
        setState('error')
      }
      // 'no-speech' and 'aborted' are harmless: onend restarts or finishes.
    }
    rec.onend = () => {
      committedRef.current = join(committedRef.current, sessionRef.current)
      sessionRef.current = ''
      if (wantRef.current) {
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
      setState('error')
    }
  }, [Ctor, lang, onTranscript])

  const start = useCallback((existingText = '') => {
    wantRef.current = true
    committedRef.current = existingText.trim()
    listen()
  }, [listen])

  const stop = useCallback(() => {
    wantRef.current = false
    setState('processing')
    recRef.current?.stop()
  }, [])

  return { state, start, stop, supported: Boolean(Ctor) }
}

/** Optional read-aloud. Never blocks the main workflow. */
export function useSpeechSynthesis(lang: string) {
  const supported = typeof window !== 'undefined' && 'speechSynthesis' in window
  const [speaking, setSpeaking] = useState(false)

  const speak = useCallback((text: string) => {
    if (!supported || !text) return
    window.speechSynthesis.cancel()
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.lang = lang
    utterance.onend = () => setSpeaking(false)
    utterance.onerror = () => setSpeaking(false)
    setSpeaking(true)
    window.speechSynthesis.speak(utterance)
  }, [lang, supported])

  const stop = useCallback(() => {
    if (supported) window.speechSynthesis.cancel()
    setSpeaking(false)
  }, [supported])

  return { supported, speaking, speak, stop }
}
