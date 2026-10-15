// Catches a screen that fails to render, notably a lazy chunk that cannot be fetched (offline, or an old hashed
// chunk removed by a newer deploy), and shows the reason with a reload button instead of a blank app.
import { Component, type ReactNode } from 'react'

export interface ScreenBoundaryProps {
  message: string
  reloadLabel: string
  children: ReactNode
  /** Defaults to a full page reload, which also fetches the current chunk names after a deploy. */
  onReload?: () => void
}

export class ScreenBoundary extends Component<ScreenBoundaryProps, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  render() {
    if (!this.state.failed) return this.props.children
    const reload = this.props.onReload ?? (() => window.location.reload())
    return (
      <div role="alert" data-code="screen_load_failed" className="mx-auto max-w-[440px] space-y-3 p-6 text-center text-sm text-red-900">
        <p>{this.props.message}</p>
        <button type="button" onClick={reload}
          className="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700">
          {this.props.reloadLabel}
        </button>
      </div>
    )
  }
}
