import { act, renderHook } from '@testing-library/react'
import { hasVoiceFor, useSpeechSynthesis } from '../hooks/useSpeech'

type Voice = { lang: string; name: string }
type Utterance = { text: string; lang: string; onend: (() => void) | null; onerror: (() => void) | null }

/** Minimal speechSynthesis: the test controls which voices the device has and when it reports them. */
class FakeSynth {
  voices: Voice[] = []
  listeners = new Set<() => void>()
  spoken: { text: string; lang: string }[] = []
  last: Utterance | null = null
  cancel = vi.fn()
  getVoices = () => this.voices
  addEventListener = (_: string, fn: () => void) => { this.listeners.add(fn) }
  removeEventListener = (_: string, fn: () => void) => { this.listeners.delete(fn) }
  speak = (u: Utterance) => { this.spoken.push({ text: u.text, lang: u.lang }); this.last = u }
  setVoices(v: Voice[]) { this.voices = v; this.listeners.forEach((fn) => fn()) }
}

class FakeUtterance {
  onend: (() => void) | null = null
  onerror: (() => void) | null = null
  lang = ''
  constructor(public text: string) {}
}

let synth: FakeSynth
beforeEach(() => {
  synth = new FakeSynth()
  Object.defineProperty(window, 'speechSynthesis', { value: synth, configurable: true })
  ;(globalThis as Record<string, unknown>).SpeechSynthesisUtterance = FakeUtterance
})
afterEach(() => {
  Reflect.deleteProperty(window, 'speechSynthesis')
  Reflect.deleteProperty(globalThis, 'SpeechSynthesisUtterance')
})

describe('hasVoiceFor', () => {
  it('matches the exact tag or the same language with another region', () => {
    expect(hasVoiceFor([{ lang: 'ta-IN' }], 'ta-IN')).toBe(true)
    expect(hasVoiceFor([{ lang: 'ta_IN' }], 'ta-IN')).toBe(true)
    expect(hasVoiceFor([{ lang: 'ta-LK' }], 'ta-IN')).toBe(true)
    expect(hasVoiceFor([{ lang: 'en-IN' }, { lang: 'hi-IN' }], 'ta-IN')).toBe(false)
    expect(hasVoiceFor([], 'ta-IN')).toBe(false)
  })
})

describe('useSpeechSynthesis', () => {
  it('speaks in the requested language when the device has a voice for it', () => {
    synth.voices = [{ lang: 'en-IN', name: 'English' }, { lang: 'ta-IN', name: 'Tamil' }]
    const { result } = renderHook(() => useSpeechSynthesis('ta-IN'))
    expect(result.current.voice).toBe('available')
    act(() => result.current.speak('வணக்கம்'))
    expect(synth.spoken).toEqual([{ text: 'வணக்கம்', lang: 'ta-IN' }])
    expect(result.current.speaking).toBe(true)
    act(() => synth.last?.onend?.())
    expect(result.current.speaking).toBe(false)
  })

  it('reports a missing voice and does not read Tamil with another language voice', () => {
    synth.voices = [{ lang: 'en-IN', name: 'English' }]
    const { result } = renderHook(() => useSpeechSynthesis('ta-IN'))
    expect(result.current.voice).toBe('missing')
    act(() => result.current.speak('வணக்கம்'))
    expect(synth.spoken).toEqual([])
    expect(result.current.speaking).toBe(false)
  })

  it('treats a not-yet-listed voice set as unknown and still speaks, then updates when voices arrive', () => {
    const { result } = renderHook(() => useSpeechSynthesis('ta-IN'))
    expect(result.current.voice).toBe('unknown')
    act(() => result.current.speak('வணக்கம்'))
    expect(synth.spoken).toHaveLength(1)
    act(() => synth.setVoices([{ lang: 'en-IN', name: 'English' }]))
    expect(result.current.voice).toBe('missing')
    act(() => synth.setVoices([{ lang: 'en-IN', name: 'English' }, { lang: 'ta-IN', name: 'Tamil' }]))
    expect(result.current.voice).toBe('available')
  })

  it('stop cancels speech and clears the speaking flag; empty text is ignored', () => {
    synth.voices = [{ lang: 'en-IN', name: 'English' }]
    const { result } = renderHook(() => useSpeechSynthesis('en-IN'))
    act(() => result.current.speak(''))
    expect(synth.spoken).toEqual([])
    act(() => result.current.speak('Hello'))
    expect(result.current.speaking).toBe(true)
    act(() => result.current.stop())
    expect(synth.cancel).toHaveBeenCalled()
    expect(result.current.speaking).toBe(false)
  })

  it('does nothing when the browser has no speech synthesis', () => {
    Reflect.deleteProperty(window, 'speechSynthesis')
    const { result } = renderHook(() => useSpeechSynthesis('en-IN'))
    expect(result.current.supported).toBe(false)
    act(() => result.current.speak('Hello'))
    expect(result.current.speaking).toBe(false)
  })

  it('removes its voiceschanged listener on unmount', () => {
    const { unmount } = renderHook(() => useSpeechSynthesis('en-IN'))
    expect(synth.listeners.size).toBe(1)
    unmount()
    expect(synth.listeners.size).toBe(0)
  })
})
