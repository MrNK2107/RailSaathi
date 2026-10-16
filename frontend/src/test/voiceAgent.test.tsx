// Voice agent screen: strings come from the string table, recognition follows the UI language, mic failures say why.
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import type { ApiClient } from '../api/client'
import { saveState } from '../mobile/persist'
import { MOBILE_STRINGS } from '../mobile/strings'
import { response } from './fixtures'

class FakeRecognition {
  static instances: FakeRecognition[] = []
  lang = ''
  continuous = false
  interimResults = false
  onresult: ((e: unknown) => void) | null = null
  onerror: ((e: { error: string }) => void) | null = null
  onend: (() => void) | null = null
  constructor() { FakeRecognition.instances.push(this) }
  start() {}
  stop() { this.onend?.() }
  abort() {}
}
const latest = () => FakeRecognition.instances[FakeRecognition.instances.length - 1]

function fakeClient(source: string | null = 'gemini'): ApiClient {
  return {
    baseUrl: 'http://test',
    health: vi.fn().mockResolvedValue({ status: 'ok', api_version: '1', data_mode: 'demo', data_provider: { requested: 'demo', active: 'demo', reason: null }, ai: {} }),
    reference: vi.fn().mockResolvedValue({ places: [], classes: [], passenger_needs: [], budget_priorities: [], transfer_preferences: [], disruption_events: [], data_notice: '' }),
    createSession: vi.fn().mockResolvedValue({ ...response({}, 'Hello'), extraction: source ? { source, fallback_reason: null } : null }),
  } as unknown as ApiClient
}

beforeEach(() => {
  FakeRecognition.instances = []
  ;(globalThis as Record<string, unknown>).webkitSpeechRecognition = FakeRecognition
  window.location.hash = '/plan'
})
afterEach(() => { Reflect.deleteProperty(globalThis, 'webkitSpeechRecognition') })

describe('Voice agent screen', () => {
  it('listens in en-IN for the English UI and ta-IN for the Tamil UI, and the mic button is labelled in each', async () => {
    const user = userEvent.setup()
    const { unmount } = render(<App client={fakeClient()} />)
    await user.click(await screen.findByRole('button', { name: MOBILE_STRINGS.en.plan.startVoice }))
    expect(latest().lang).toBe('en-IN')
    expect(screen.getByRole('button', { name: MOBILE_STRINGS.en.plan.stopVoice })).toHaveAttribute('aria-pressed', 'true')
    unmount()

    saveState({ language: 'ta' })
    FakeRecognition.instances = []
    render(<App client={fakeClient()} />)
    await user.click(await screen.findByRole('button', { name: MOBILE_STRINGS.ta.plan.startVoice }))
    expect(latest().lang).toBe('ta-IN')
  })

  it('a manual choice of recognition language is respected for that visit', async () => {
    const user = userEvent.setup()
    render(<App client={fakeClient()} />)
    const group = await screen.findByRole('group', { name: MOBILE_STRINGS.en.plan.speakIn })
    expect(within(group).getByRole('button', { name: 'English' })).toHaveAttribute('aria-pressed', 'true')
    await user.click(within(group).getByRole('button', { name: 'தமிழ்' }))
    expect(within(group).getByRole('button', { name: 'தமிழ்' })).toHaveAttribute('aria-pressed', 'true')
    await user.click(screen.getByRole('button', { name: MOBILE_STRINGS.en.plan.startVoice }))
    expect(latest().lang).toBe('ta-IN')
  })

  it('shows the specific reason a microphone failed, in the UI language', async () => {
    const user = userEvent.setup()
    render(<App client={fakeClient()} />)
    await user.click(await screen.findByRole('button', { name: MOBILE_STRINGS.en.plan.startVoice }))
    act(() => { latest().onerror?.({ error: 'not-allowed' }); latest().onend?.() })
    expect(screen.getByText(MOBILE_STRINGS.en.plan.micErrors.not_allowed)).toBeInTheDocument()
    // The mic button stays usable so the user can try again after allowing the microphone.
    expect(screen.getByRole('button', { name: MOBILE_STRINGS.en.plan.startVoice })).toBeEnabled()
  })

  it('explains an insecure context instead of a generic failure', async () => {
    const original = Object.getOwnPropertyDescriptor(window, 'isSecureContext')
    Object.defineProperty(window, 'isSecureContext', { value: false, configurable: true })
    try {
      render(<App client={fakeClient()} />)
      await userEvent.setup().click(await screen.findByRole('button', { name: MOBILE_STRINGS.en.plan.startVoice }))
      expect(screen.getByText(MOBILE_STRINGS.en.plan.micErrors.insecure)).toBeInTheDocument()
    } finally {
      if (original) Object.defineProperty(window, 'isSecureContext', original)
      else Reflect.deleteProperty(window, 'isSecureContext')
    }
  })

  it('announces replies in a polite log region and names the engine without claiming Bedrock', async () => {
    render(<App client={fakeClient('gemini')} />)
    const log = await screen.findByRole('log', { name: MOBILE_STRINGS.en.plan.conversation })
    expect(log).toHaveAttribute('aria-live', 'polite')
    expect(log).toHaveTextContent('Hello')
    expect(screen.getByText(MOBILE_STRINGS.en.plan.understoodBy.ai)).toBeInTheDocument()
    expect(document.body).not.toHaveTextContent(/Bedrock/)
  })

  it('says the built-in parser understood the request when the rule fallback ran', async () => {
    render(<App client={fakeClient('rules')} />)
    expect(await screen.findByText(MOBILE_STRINGS.en.plan.understoodBy.rules)).toBeInTheDocument()
  })

  it('uses a short one-line placeholder that never wraps or scrolls while empty, in both languages', async () => {
    const user = userEvent.setup()
    const { unmount } = render(<App client={fakeClient()} />)
    const box = await screen.findByLabelText(MOBILE_STRINGS.en.plan.inputLabel)
    expect(box).toHaveAttribute('placeholder', 'Where do you want to go?')
    expect(box).toHaveAttribute('rows', '1')
    expect(box).toHaveAttribute('data-empty', 'true')
    const classes = () => box.className.split(/\s+/)
    expect(classes()).toEqual(expect.arrayContaining(['overflow-hidden', 'whitespace-nowrap', 'text-ellipsis']))
    await user.type(box, 'Chennai to Madurai')
    expect(box).not.toHaveAttribute('data-empty')
    expect(classes()).not.toContain('whitespace-nowrap')  // typed text wraps and the box grows as before
    unmount()

    saveState({ language: 'ta' })
    render(<App client={fakeClient()} />)
    expect(await screen.findByLabelText(MOBILE_STRINGS.ta.plan.inputLabel)).toHaveAttribute('placeholder', 'எங்கே செல்ல வேண்டும்?')
  })
})
