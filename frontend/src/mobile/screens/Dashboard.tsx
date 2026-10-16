import { useState } from 'react'
import heroJpg from '../../assets/hero-station.jpg'
import heroWebp from '../../assets/hero-station.webp'
import type { Language } from '../../api/types'
import { POPULAR_ROUTES } from '../config'
import { AccessibleIcon, ArrowRight, ClockIcon, HelpIcon, LiveIcon, PinIcon, TagIcon } from '../icons'
import { ProvenanceBadge } from '../../components/ProvenanceBadge'
import { useApp } from '../PlannerContext'
import { ErrorBanner, Logo, Screen } from '../ui'
import { LiveAlertsPromo } from './LiveAlertsPromo'
import { RouteCard } from './RouteCard'

const COLLAPSED_ROUTES = 4

/**
 * Landing hero: station photo supplied by the team. The photo already contains the English
 * "Hello, Plan, navigate and travel…" text, so the same words are kept for screen readers only.
 * In Tamil the baked-in English is covered by an opaque panel with the Tamil greeting.
 */
function Hero({ hello, intro, tamil }: { hello: string; intro: string; tamil: boolean }) {
  return (
    <section className="relative aspect-square w-full overflow-hidden bg-brand-100" aria-labelledby="hero-title">
      <picture>
        <source srcSet={heroWebp} type="image/webp" />
        {/* React 18 only knows the lowercase DOM attribute; the camelCase prop logs a warning. */}
        <img src={heroJpg} alt="" width={880} height={880} decoding="async" {...{ fetchpriority: 'high' }}
          className="absolute inset-0 h-full w-full object-cover" />
      </picture>
      {tamil ? (
        // The photo's English text spans roughly the top 47% of the image; cover all of it.
        <div className="absolute inset-x-0 top-0 h-[54%] px-4 pt-8"
          style={{ background: 'linear-gradient(to bottom, rgb(255,255,255) 0%, rgb(255,255,255) 86%, rgba(255,255,255,0) 100%)' }}>
          <h1 id="hero-title" className="text-3xl font-extrabold text-brand-900">{hello}</h1>
          <p className="mt-1 text-sm font-medium text-ink-700">{intro}</p>
        </div>
      ) : (
        <div className="sr-only">
          <h1 id="hero-title">{hello}</h1>
          <p>{intro}</p>
        </div>
      )}
    </section>
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
            aria-label={m.dashboard.sosTitle}
            title={m.dashboard.sosTitle}
          >
            {m.dashboard.sos}
          </button>
          <div role="group" aria-label={m.dashboard.language} className="flex overflow-hidden rounded-full border border-ink-300 text-xs font-semibold">
            {(['en', 'ta'] as Language[]).map((code) => (
              <button key={code} type="button" onClick={() => planner.setLanguage(code)} aria-pressed={lang === code}
                className={`px-2.5 py-1 ${lang === code ? 'bg-brand-600 text-white' : 'text-ink-700'}`}>
                {code === 'en' ? 'EN' : 'தமிழ்'}
              </button>
            ))}
          </div>
        </div>
      </header>

      <div className="relative">
        <Hero hello={m.dashboard.hello} intro={m.dashboard.intro} tamil={lang === 'ta'} />
        <div className="absolute right-3 top-3">{planner.health && <ProvenanceBadge provenance={null} mode={planner.health.data_mode} labels={{ live: m.live }} />}</div>
      </div>

      <button type="button" onClick={() => go('plan')}
        className="relative z-10 mx-4 -mt-8 flex items-center gap-3 rounded-2xl bg-white p-4 text-left shadow-card ring-1 ring-ink-100 hover:ring-brand-200">
        <span className="flex-1">
          <span className="block text-lg font-bold text-brand-900">{m.dashboard.planTitle}</span>
          <span className="mt-0.5 block text-sm text-ink-500">{m.dashboard.planBody}</span>
        </span>
        <span className="grid h-11 w-11 place-items-center rounded-full bg-brand-600 text-white"><ArrowRight size={22} /></span>
      </button>

      <ErrorBanner />

      <section aria-label={m.dashboard.services} className="grid grid-cols-2 gap-3 p-4">
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
        <ul className="grid grid-cols-2 gap-3">
          {routes.map((r) => (
            <li key={`${r.from}-${r.to}`} className="min-w-0">
              <RouteCard title={lang === 'ta' ? r.ta : `${r.from} → ${r.to}`} codes={r.codes} station={lang === 'ta' ? r.stationTa : r.station}
                image={r.image} cta={m.dashboard.routeCta} disabled={planner.loading} onClick={() => startRoute(r.from, r.to)} />
            </li>
          ))}
        </ul>
      </section>

      <LiveAlertsPromo />
    </Screen>
  )
}
