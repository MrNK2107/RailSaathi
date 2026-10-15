// Catches a screen (or the whole app) that fails to render, notably a lazy chunk that cannot be fetched (offline, or an
// old hashed chunk removed by a newer deploy), and shows the reason with buttons instead of a blank page.
// Reload fetches the current build; Try again (only when `retryLabel` is given) clears the failure and renders the
// children again, after `onRetry` has had the chance to reset whatever state caused it.
import { Component, type ReactNode } from 'react'

/** A fixed string, or a function evaluated when the fallback renders (so it follows a language change). */
type Text = string | (() => string)
const text = (t: Text) => (typeof t === 'function' ? t() : t)

export interface ScreenBoundaryProps {
  message: Text
  reloadLabel: Text
  children: ReactNode
  /** Defaults to a full page reload, which also fetches the current chunk names after a deploy. */
  onReload?: () => void
  retryLabel?: Text
  onRetry?: () => void
  /** `data-code` of the alert, for tests and support. */
  code?: string
}

export class ScreenBoundary extends Component<ScreenBoundaryProps, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  private retry = () => {
    this.props.onRetry?.()
    this.setState({ failed: false })
  }

  render() {
    if (!this.state.failed) return this.props.children
    const { message, reloadLabel, retryLabel, onReload, code = 'screen_load_failed' } = this.props
    const reload = onReload ?? (() => window.location.reload())
    const button = 'rounded-xl px-4 py-2 text-sm font-semibold'
    return (
      <div role="alert" data-code={code} className="mx-auto max-w-[440px] space-y-3 p-6 text-center text-sm text-red-900">
        <p>{text(message)}</p>
        <div className="flex justify-center gap-2">
          {retryLabel !== undefined && (
            <button type="button" onClick={this.retry} className={`${button} border border-ink-300 bg-white text-brand-700 hover:bg-brand-50`}>
              {text(retryLabel)}
            </button>
          )}
          <button type="button" onClick={reload} className={`${button} bg-brand-600 text-white hover:bg-brand-700`}>
            {text(reloadLabel)}
          </button>
        </div>
      </div>
    )
  }
}
