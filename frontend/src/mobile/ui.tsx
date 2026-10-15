// Shared building blocks for the mobile screens.
import type { ReactNode } from 'react'
import type { Category, DataProvenance, Recommendation, SessionState } from '../api/types'
import { formatDay, formatTime } from '../utils/format'
import {
  AlertIcon, ArrowLeft, BellIcon, BoltIcon, HomeIcon, RefreshIcon, TagIcon, TrainIcon, TripsIcon,
  TrophyIcon, UserIcon,
} from './icons'
import { useApp } from './PlannerContext'
import type { Route } from './router'

export function Logo({ compact = false }: { compact?: boolean }) {
  const { m } = useApp()
  return (
    <div className="flex items-center gap-2">
      <span className="grid h-9 w-9 place-items-center rounded-xl bg-brand-600 text-white">
        <TrainIcon size={22} />
      </span>
      <span className="leading-tight">
        <span className="block text-lg font-extrabold tracking-tight text-brand-900">
          Rail<span className="text-brand-600">Saathi</span>
        </span>
        {!compact && <span className="block text-[10px] font-medium text-ink-500">{m.tagline}</span>}
      </span>
    </div>
  )
}

/** Screen header with a back button, as in the reference screens 2-7. */
export function AppHeader({ right }: { right?: ReactNode }) {
  const { back, m } = useApp()
  return (
    <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-ink-100 bg-white/95 px-4 py-3 backdrop-blur">
      <button type="button" onClick={back} aria-label={m.back} className="-ml-1 rounded-full p-1.5 text-brand-900 hover:bg-ink-100">
        <ArrowLeft size={22} />
      </button>
      <Logo compact />
      <div className="ml-auto">{right}</div>
    </header>
  )
}

const NAV: { route: Route; key: 'home' | 'trips' | 'alerts' | 'profile'; Icon: typeof HomeIcon }[] = [
  { route: 'home', key: 'home', Icon: HomeIcon },
  { route: 'trips', key: 'trips', Icon: TripsIcon },
  { route: 'alerts', key: 'alerts', Icon: BellIcon },
  { route: 'profile', key: 'profile', Icon: UserIcon },
]

export function BottomNav() {
  const { route, go, m } = useApp()
  return (
    <nav aria-label={m.nav.main} className="sticky bottom-0 z-20 grid grid-cols-4 border-t border-ink-100 bg-white pb-[env(safe-area-inset-bottom)]">
      {NAV.map(({ route: target, key, Icon }) => {
        const active = route === target
        return (
          <button key={target} type="button" onClick={() => go(target)} aria-current={active ? 'page' : undefined}
            className={`flex flex-col items-center gap-0.5 py-2 text-[11px] font-medium ${active ? 'text-brand-600' : 'text-ink-500'}`}>
            <Icon size={22} />
            {m.nav[key]}
          </button>
        )
      })}
    </nav>
  )
}

/** Phone-width column: full width on phones, centred "device" on larger screens. */
export function Screen({ children, nav = false, footer }: { children: ReactNode; nav?: boolean; footer?: ReactNode }) {
  return (
    <div className="mx-auto flex min-h-screen w-full max-w-[440px] flex-col bg-white shadow-card sm:my-4 sm:min-h-[calc(100vh-2rem)] sm:overflow-hidden sm:rounded-[28px]">
      <div className="flex flex-1 flex-col">{children}</div>
      {footer && <div className="sticky bottom-0 z-10 border-t border-ink-100 bg-white p-4">{footer}</div>}
      {nav && <BottomNav />}
    </div>
  )
}

/** "Source: … · retrieved 10 Oct 15:21 IST" — from the backend's provenance fields. */
export function SourceLine({ provenance }: { provenance: DataProvenance }) {
  const { m } = useApp()
  const when = provenance.mode === 'live' ? m.options.retrieved : m.options.datasetAsOf
  return (
    <p className="text-[11px] text-ink-500" data-testid="source-line">
      {m.options.source}: {provenance.source} · {when} {formatDay(provenance.as_of)} {formatTime(provenance.as_of)} IST
    </p>
  )
}

const CATEGORY_STYLE: Record<Category, { cls: string; Icon: typeof TrophyIcon }> = {
  best_overall: { cls: 'bg-match-600 text-white', Icon: TrophyIcon },
  lowest_cost: { cls: 'bg-cheap-600 text-white', Icon: TagIcon },
  fastest: { cls: 'bg-fast-500 text-white', Icon: BoltIcon },
}

export function CategoryBadge({ category }: { category: Category }) {
  const { m } = useApp()
  const { cls, Icon } = CATEGORY_STYLE[category]
  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-semibold ${cls}`}>
      <Icon size={13} /> {m.options.tabs[category]}
    </span>
  )
}

export function ErrorBanner() {
  const { planner, m } = useApp()
  if (!planner.error) return null
  return (
    <div role="alert" className="mx-4 my-2 flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800">
      <AlertIcon size={18} className="mt-0.5 shrink-0" />
      <span className="flex-1">{planner.error}</span>
      {planner.canRetry && (
        <button type="button" onClick={() => planner.retry()} className="inline-flex items-center gap-1 font-semibold underline">
          <RefreshIcon size={14} /> {m.errors.retry}
        </button>
      )}
    </div>
  )
}

export function PrimaryButton({ children, onClick, disabled, type = 'button' }: {
  children: ReactNode; onClick?: () => void; disabled?: boolean; type?: 'button' | 'submit'
}) {
  return (
    <button type={type} onClick={onClick} disabled={disabled}
      className="flex w-full items-center justify-center gap-2 rounded-2xl bg-brand-600 px-4 py-3.5 text-base font-semibold text-white shadow-card hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50">
      {children}
    </button>
  )
}

export function SecondaryButton({ children, onClick, disabled }: { children: ReactNode; onClick?: () => void; disabled?: boolean }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled}
      className="flex w-full items-center justify-center gap-2 rounded-2xl border border-ink-300 bg-white px-4 py-3 text-base font-semibold text-brand-700 hover:bg-brand-50 disabled:opacity-50">
      {children}
    </button>
  )
}

export function selectedRecommendation(state: SessionState | null): Recommendation | null {
  if (!state?.recommendations) return null
  const id = state.selected_option_id ?? state.confirmation?.selected_option_id
  return state.recommendations.recommendations.find((r) => r.option.option_id === id) ?? null
}
