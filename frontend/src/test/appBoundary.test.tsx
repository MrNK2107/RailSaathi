// The outermost boundary: a crash outside any screen shows a reason with Try again and Reload, in the language the
// planner persisted, and Try again resets the stored planning session before rendering the app again.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppBoundary } from '../components/AppBoundary'
import { ScreenBoundary } from '../components/ScreenBoundary'
import { loadState, saveState } from '../mobile/persist'
import { MOBILE_STRINGS } from '../mobile/strings'

let crash = true
function Flaky() {
  if (crash) throw new Error('boom')
  return <p>app is fine</p>
}

describe('AppBoundary', () => {
  let quiet: ReturnType<typeof vi.spyOn>
  beforeEach(() => {
    crash = true
    quiet = vi.spyOn(console, 'error').mockImplementation(() => undefined) // React reports the caught error
  })
  afterEach(() => quiet.mockRestore())

  it('renders its children when nothing fails', () => {
    crash = false
    render(<AppBoundary><Flaky /></AppBoundary>)
    expect(screen.getByText('app is fine')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows an alert with Try again and Reload instead of a blank page', () => {
    const e = MOBILE_STRINGS.en.errors
    render(<AppBoundary><Flaky /></AppBoundary>)
    const alert = screen.getByRole('alert')
    expect(alert).toHaveAttribute('data-code', 'app_failed')
    expect(alert).toHaveTextContent(e.appFailed)
    expect(screen.getByRole('button', { name: e.tryAgain })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: e.reload })).toBeInTheDocument()
  })

  it('uses the language persisted by the planner, read when the failure renders', () => {
    saveState({ language: 'ta' })
    const ta = MOBILE_STRINGS.ta.errors
    render(<AppBoundary><Flaky /></AppBoundary>)
    expect(screen.getByRole('alert')).toHaveTextContent(ta.appFailed)
    expect(ta.appFailed).not.toBe(MOBILE_STRINGS.en.errors.appFailed)
    expect(screen.getByRole('button', { name: ta.tryAgain })).toBeInTheDocument()
  })

  it('Try again forgets the stored session (keeping the language) and renders the app again', async () => {
    saveState({ language: 'ta', session: { sessionId: 'sid-1', token: 'tok-1' } })
    render(<AppBoundary><Flaky /></AppBoundary>)
    crash = false // the cause has gone by the time the user retries
    await userEvent.setup().click(screen.getByRole('button', { name: MOBILE_STRINGS.ta.errors.tryAgain }))
    expect(screen.getByText('app is fine')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(loadState()).toEqual({ language: 'ta', session: null })
  })

  it('shows the failure again if the retry crashes again', async () => {
    render(<AppBoundary><Flaky /></AppBoundary>)
    await userEvent.setup().click(screen.getByRole('button', { name: MOBILE_STRINGS.en.errors.tryAgain }))
    expect(screen.getByRole('alert')).toHaveAttribute('data-code', 'app_failed')
  })
})

describe('ScreenBoundary reload and retry buttons', () => {
  let quiet: ReturnType<typeof vi.spyOn>
  beforeEach(() => { crash = true; quiet = vi.spyOn(console, 'error').mockImplementation(() => undefined) })
  afterEach(() => quiet.mockRestore())

  it('offers no Try again unless asked, and calls the reload handler', async () => {
    const onReload = vi.fn()
    render(<ScreenBoundary message="failed" reloadLabel="Reload" onReload={onReload}><Flaky /></ScreenBoundary>)
    expect(screen.queryByRole('button', { name: /try again/i })).not.toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Reload' }))
    expect(onReload).toHaveBeenCalledTimes(1)
  })

  it('runs onRetry before rendering the children again', async () => {
    const order: string[] = []
    const onRetry = vi.fn(() => { order.push('retry'); crash = false })
    render(<ScreenBoundary message="failed" reloadLabel="Reload" retryLabel="Try again" onRetry={onRetry}><Flaky /></ScreenBoundary>)
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }))
    expect(onRetry).toHaveBeenCalledTimes(1)
    expect(screen.getByText('app is fine')).toBeInTheDocument()
  })
})
