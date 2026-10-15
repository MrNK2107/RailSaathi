// The outermost error boundary: anything that throws outside a screen (the planner hook, the classic view, the
// router) lands here instead of unmounting to a blank page. It sits above the planner, so it reads the language the
// planner persisted rather than the live planner state. "Try again" forgets the stored planning session first, so a
// session that causes the crash is not resumed straight into the same crash.
import type { ReactNode } from 'react'
import { loadState, saveState } from '../mobile/persist'
import { MOBILE_STRINGS } from '../mobile/strings'
import { ScreenBoundary } from './ScreenBoundary'

const errors = () => MOBILE_STRINGS[loadState().language].errors

export function AppBoundary({ children }: { children: ReactNode }) {
  return (
    <ScreenBoundary code="app_failed" message={() => errors().appFailed} retryLabel={() => errors().tryAgain}
      reloadLabel={() => errors().reload} onRetry={() => saveState({ session: null })}>
      {children}
    </ScreenBoundary>
  )
}
