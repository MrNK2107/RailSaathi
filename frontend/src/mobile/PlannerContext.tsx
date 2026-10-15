import { createContext, useContext, type ReactNode } from 'react'
import type { Planner } from '../hooks/usePlanner'
import type { Route } from './router'
import { MOBILE_STRINGS, type MobileStrings } from './strings'

export interface AppContextValue {
  planner: Planner
  route: Route
  go: (route: Route) => void
  back: () => void
  m: MobileStrings
}

const AppContext = createContext<AppContextValue | null>(null)

export function AppProvider({ value, children }: { value: Omit<AppContextValue, 'm'>; children: ReactNode }) {
  const m = MOBILE_STRINGS[value.planner.language]
  return <AppContext.Provider value={{ ...value, m }}>{children}</AppContext.Provider>
}

/** For shared components that also render outside the mobile app (classic view): null there. */
export function useOptionalApp(): AppContextValue | null {
  return useContext(AppContext)
}

export function useApp(): AppContextValue {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used inside AppProvider')
  return ctx
}
