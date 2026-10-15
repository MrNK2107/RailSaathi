import { useState } from 'react'
import type { Language } from '../../api/types'
import { POPULAR_ROUTES } from '../config'
import { AccessibleIcon, ArrowRight, ChevronRight, ClockIcon, HelpIcon, LiveIcon, PinIcon, TagIcon, TrainIcon } from '../icons'
import { ProvenanceBadge } from '../../components/ProvenanceBadge'
import { useApp } from '../PlannerContext'
import { ErrorBanner, Logo, Screen } from '../ui'

const COLLAPSED_ROUTES = 4

function HeroArt() {
  return (
    <svg aria-hidden viewBox="0 0 400 210" className="absolute inset-0 h-full w-full" preserveAspectRatio="xMidYMid slice">
      <defs>
        <linearGradient id="sky" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#dbe7ff" /><stop offset="1" stopColor="#f6d9b8" />
        </linearGradient>
        <linearGradient id="coach" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffffff" /><stop offset="1" stopColor="#dfe6f3" />
        </linearGradient>
      </defs>
      <rect width="400" height="210" fill="url(#sky)" />
      <rect x="0" y="150" width="400" height="60" fill="#c9d1e3" />
      <rect x="0" y="150" width="400" height="6" fill="#a4b0c9" />
      <g transform="translate(150 78)">
        <path d="M0 70 L20 18 Q26 6 40 6 H260 V70 Z" fill="url(#coach)" stroke="#94a3c4" />
        <path d="M0 70 L20 18 Q26 6 40 6 H64 V70 Z" fill="#f97316" opacity=".9" />
        <rect x="0" y="52" width="260" height="8" fill="#1a56db" />
        {[80, 120, 160, 200].map((x) => <rect key={x} x={x} y="20" width="28" height="18" rx="3" fill="#1f3b73" />)}
        <rect x="28" y="20" width="26" height="18" rx="3" fill="#1f3b73" />
        <circle cx="70" cy="72" r="6" fill="#33405e" /><circle cx="210" cy="72" r="6" fill="#33405e" />
      </g>
      <g fill="#1645b5" opacity=".18">
        <rect x="18" y="40" width="10" height="110" /><rect x="96" y="40" width="10" height="110" />
        <rect x="10" y="34" width="110" height="8" />
      </g>
    </svg>
  )
}

export default function Dashboard() {
  const { planner, go, m } = useApp()
  const [showAll, setShowAll] = useState(false)
  const lang = planner.language
  const routes = showAll ? POPULAR_ROUTES : POPULAR_ROUTES.slice(0, COLLAPSED_ROUTES)

  const startRoute = async (from: string, to: string) => {
    const ok = await planner.startWithMessage(`from ${from} to ${to}`)
    if (ok) go('plan')
  }

  const shortcuts = [
    { label: m.dashboard.liveUpdates, Icon: LiveIcon, onClick: () => go(planner.state?.confirmation ? 'confirmation' : 'alerts') },
    { label: m.dashboard.goalPlanner, Icon: ClockIcon, onClick: () => go('goal') },
    { label: m.dashboard.ticketing, Icon: TagIcon, onClick: () => go('ticketing') },
    { label: m.dashboard.stationNav, Icon: PinIcon, onClick: () => go('navigation') },
    { label: m.dashboard.accessible, Icon: AccessibleIcon, onClick: () => go('help') },
    { label: m.dashboard.help, Icon: HelpIcon, onClick: () => go('help') },
  ]

  return (
    <Screen nav>
      <header className="flex items-center justify-between px-4 py-3">
        <Logo />
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => go('help')}
            className="flex items-center gap-1 rounded-full border border-red-200 bg-red-50 px-2.5 py-1 text-xs font-bold text-red-600 hover:bg-red-100"
            title="Emergency SOS & Helplines"
          >
            SOS
          </button>
          <div role="group" aria-label="Language" className="flex overflow-hidden rounded-full border border-ink-300 text-xs font-semibold">
            {(['en', 'ta'] as Language[]).map((code) => (
              <button key={code} type="button" onClick={() => planner.setLanguage(code)} aria-pressed={lang === code}
                className={`px-2.5 py-1 ${lang === code ? 'bg-brand-600 text-white' : 'text-ink-700'}`}>
                {code === 'en' ? 'EN' : 'தமிழ்'}
              </button>
            ))}
          </div>
        </div>
      </header>

      <section className="relative mx-0 h-56 overflow-hidden">
        <HeroArt />
        <div className="relative max-w-[60%] p-4">
          <h1 className="text-3xl font-extrabold text-brand-900">{m.dashboard.hello}</h1>
          <p className="mt-1 text-sm font-medium text-ink-700">{m.dashboard.intro}</p>
        </div>
        <div className="absolute right-3 top-3">{planner.health && <ProvenanceBadge provenance={null} mode={planner.health.data_mode} labels={{ live: m.live }} />}</div>
      </section>

      <button type="button" onClick={() => go('plan')}
        className="relative z-10 mx-4 -mt-8 flex items-center gap-3 rounded-2xl bg-white p-4 text-left shadow-card ring-1 ring-ink-100 hover:ring-brand-200">
        <span className="flex-1">
          <span className="block text-lg font-bold text-brand-900">{m.dashboard.planTitle}</span>
          <span className="mt-0.5 block text-sm text-ink-500">{m.dashboard.planBody}</span>
        </span>
        <span className="grid h-11 w-11 place-items-center rounded-full bg-brand-600 text-white"><ArrowRight size={22} /></span>
      </button>

      <ErrorBanner />

      <section aria-label="Services" className="grid grid-cols-2 gap-3 p-4">
        {shortcuts.map(({ label, Icon, onClick }) => (
          <button key={label} type="button" onClick={onClick}
            className="flex items-center gap-3 rounded-2xl bg-white p-3 text-left text-sm font-semibold text-brand-900 shadow-card ring-1 ring-ink-100 hover:ring-brand-200">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand-50 text-brand-600"><Icon size={22} /></span>
            {label}
          </button>
        ))}
      </section>

      <section aria-labelledby="popular-title" className="px-4 pb-4">
        <div className="mb-2 flex items-center justify-between">
          <h2 id="popular-title" className="text-base font-bold text-brand-900">{m.dashboard.popular}</h2>
          <button type="button" onClick={() => setShowAll(!showAll)} className="text-sm font-semibold text-brand-600">
            {showAll ? m.dashboard.showLess : m.dashboard.viewAll}
          </button>
        </div>
        <ul className="divide-y divide-ink-100 rounded-2xl bg-white shadow-card ring-1 ring-ink-100">
          {routes.map((r) => (
            <li key={`${r.from}-${r.to}`}>
              <button type="button" disabled={planner.loading} onClick={() => startRoute(r.from, r.to)}
                className="flex w-full items-center gap-3 px-3 py-3 text-left text-sm text-ink-900 hover:bg-brand-50 disabled:opacity-60">
                <TrainIcon size={18} className="text-brand-600" />
                <span className="flex-1">{lang === 'ta' ? r.ta : `${r.from} → ${r.to}`}</span>
                <ChevronRight size={18} className="text-ink-500" />
              </button>
            </li>
          ))}
        </ul>
      </section>
    </Screen>
  )
}
