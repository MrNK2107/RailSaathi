import { act, renderHook } from '@testing-library/react'
import { MAX_EMPTY_RESTARTS, useSpeechRecognition } from '../hooks/useSpeech'

type Result = { transcript: string; isFinal: boolean }

/** Fake browser recognition engine: the test drives results and session ends. */
class FakeRecognition {
  static instances: FakeRecognition[] = []
  lang = ''
  interimResults = false
  continuous = false
  onresult: ((e: unknown) => void) | null = null
  onerror: ((e: { error: string }) => void) | null = null
  onend: (() => void) | null = null
  started = 0
  stopped = 0
  constructor() { FakeRecognition.instances.push(this) }
  start() { this.started += 1 }
  stop() { this.stopped += 1; this.onend?.() }
  abort() {}
  emit(results: Result[]) {
    this.onresult?.({ results: results.map((r) => Object.assign([{ transcript: r.transcript, confidence: 0.9 }], { isFinal: r.isFinal })) })
  }
}

const latest = () => FakeRecognition.instances[FakeRecognition.instances.length - 1]

beforeEach(() => {
  FakeRecognition.instances = []
  ;(globalThis as Record<string, unknown>).webkitSpeechRecognition = FakeRecognition
})
afterEach(() => {
  delete (globalThis as Record<string, unknown>).webkitSpeechRecognition
})

describe('useSpeechRecognition', () => {
  it('keeps listening across browser pauses until Stop is pressed', () => {
    const onTranscript = vi.fn()
    const { result } = renderHook(() => useSpeechRecognition('en-IN', onTranscript))
    act(() => result.current.start())
    expect(result.current.state).toBe('listening')
    expect(latest().continuous).toBe(true)
    expect(latest().interimResults).toBe(true)

    act(() => latest().emit([{ transcript: 'I need to reach Chennai', isFinal: true }, { transcript: 'before', isFinal: false }]))
    expect(onTranscript).toHaveBeenLastCalledWith('I need to reach Chennai before')

    // Browser ends the session on its own after a pause: hook must restart, not stop.
    act(() => latest().onend?.())
    expect(FakeRecognition.instances).toHaveLength(2)
    expect(result.current.state).toBe('listening')

    act(() => latest().emit([{ transcript: 'nine AM tomorrow', isFinal: true }]))
    expect(onTranscript).toHaveBeenLastCalledWith('I need to reach Chennai nine AM tomorrow')

    act(() => result.current.stop())
    expect(result.current.state).toBe('idle')
    expect(FakeRecognition.instances).toHaveLength(2) // no restart after Stop
    expect(onTranscript).toHaveBeenLastCalledWith('I need to reach Chennai nine AM tomorrow')
  })

  it('appends to text already in the box', () => {
    const onTranscript = vi.fn()
    const { result } = renderHook(() => useSpeechRecognition('en-IN', onTranscript))
    act(() => result.current.start('from Coimbatore'))
    act(() => latest().emit([{ transcript: 'to Chennai', isFinal: true }]))
    expect(onTranscript).toHaveBeenLastCalledWith('from Coimbatore to Chennai')
  })

  it('stops with an error when microphone permission is denied', () => {
    const { result } = renderHook(() => useSpeechRecognition('en-IN', vi.fn()))
    act(() => result.current.start())
    act(() => { latest().onerror?.({ error: 'not-allowed' }); latest().onend?.() })
    expect(result.current.state).toBe('error')
    expect(FakeRecognition.instances).toHaveLength(1)
  })

  it('ignores silence and keeps listening', () => {
    const { result } = renderHook(() => useSpeechRecognition('en-IN', vi.fn()))
    act(() => result.current.start())
    act(() => { latest().onerror?.({ error: 'no-speech' }); latest().onend?.() })
    expect(result.current.state).toBe('listening')
    expect(FakeRecognition.instances).toHaveLength(2)
  })
})

describe('useSpeechRecognition errors and limits', () => {
  it.each([
    ['not-allowed', 'not_allowed'],
    ['service-not-allowed', 'service_unavailable'],
    ['audio-capture', 'no_microphone'],
    ['network', 'network'],
    ['language-not-supported', 'language_unsupported'],
  ])('maps the browser error %s to the distinct code %s and stops', (browserError, code) => {
    const { result } = renderHook(() => useSpeechRecognition('ta-IN', vi.fn()))
    act(() => result.current.start())
    act(() => { latest().onerror?.({ error: browserError }); latest().onend?.() })
    expect(result.current.state).toBe('error')
    expect(result.current.errorCode).toBe(code)
    expect(FakeRecognition.instances).toHaveLength(1) // no restart after a fatal error
  })

  it('refuses to start outside a secure context and says why', () => {
    const original = Object.getOwnPropertyDescriptor(window, 'isSecureContext')
    Object.defineProperty(window, 'isSecureContext', { value: false, configurable: true })
    try {
      const { result } = renderHook(() => useSpeechRecognition('en-IN', vi.fn()))
      act(() => result.current.start())
      expect(result.current.state).toBe('error')
      expect(result.current.errorCode).toBe('insecure')
      expect(FakeRecognition.instances).toHaveLength(0)
    } finally {
      if (original) Object.defineProperty(window, 'isSecureContext', original)
      else Reflect.deleteProperty(window, 'isSecureContext')
    }
  })

  it('reports start_failed when the engine throws on start, and clears the code on the next attempt', () => {
    const { result } = renderHook(() => useSpeechRecognition('en-IN', vi.fn()))
    const start = vi.spyOn(FakeRecognition.prototype, 'start').mockImplementationOnce(() => { throw new Error('already started') })
    act(() => result.current.start())
    expect(result.current.errorCode).toBe('start_failed')
    start.mockRestore()
    act(() => result.current.start())
    expect(result.current.state).toBe('listening')
    expect(result.current.errorCode).toBeNull()
  })

  it('gives up after too many restarts that heard nothing, but keeps the words already captured', () => {
    const onTranscript = vi.fn()
    const { result } = renderHook(() => useSpeechRecognition('en-IN', onTranscript))
    act(() => result.current.start('from Salem'))
    for (let i = 0; i < MAX_EMPTY_RESTARTS; i += 1) {
      act(() => latest().onend?.())
      expect(result.current.state).toBe('listening')
    }
    act(() => latest().onend?.())
    expect(result.current.state).toBe('error')
    expect(result.current.errorCode).toBe('restart_limit')
    expect(onTranscript).toHaveBeenLastCalledWith('from Salem')
    expect(FakeRecognition.instances).toHaveLength(MAX_EMPTY_RESTARTS + 1)
  })

  it('does not count a restart after the user spoke, so a long dictation with pauses keeps going', () => {
    const { result } = renderHook(() => useSpeechRecognition('en-IN', vi.fn()))
    act(() => result.current.start())
    for (let i = 0; i < MAX_EMPTY_RESTARTS * 2; i += 1) {
      act(() => latest().emit([{ transcript: `word${i}`, isFinal: true }]))
      act(() => latest().onend?.())
    }
    expect(result.current.state).toBe('listening')
    expect(result.current.errorCode).toBeNull()
  })

  it('uses the language it is given', () => {
    const { result } = renderHook(() => useSpeechRecognition('ta-IN', vi.fn()))
    act(() => result.current.start())
    expect(latest().lang).toBe('ta-IN')
  })
})
