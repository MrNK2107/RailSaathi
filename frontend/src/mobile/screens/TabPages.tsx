// Bottom-navigation pages: My Trips (device-local saved plans), Alerts (not connected), Profile.
import { useState } from 'react'
import type { Language } from '../../api/types'
import { formatDate, formatTime } from '../../utils/format'
import { BellIcon, GlobeIcon, InfoIcon, TrainIcon } from '../icons'
import { useApp } from '../PlannerContext'
import { loadTrips, removeTrip, type SavedTrip } from '../trips'
import { Logo, ModeBadge, Screen } from '../ui'

function Page({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Screen nav>
      <header className="px-4 py-3"><Logo /></header>
      <div className="space-y-3 px-4 pb-6">
        <h1 className="text-2xl font-extrabold text-brand-900">{title}</h1>
        {children}
      </div>
    </Screen>
  )
}

export function MyTrips() {
  const { m } = useApp()
  const [trips, setTrips] = useState<SavedTrip[]>(() => loadTrips())
  return (
    <Page title={m.trips.title}>
      <p className="text-xs text-ink-500">{m.trips.deviceOnly}</p>
      {trips.length === 0 && <p className="rounded-2xl bg-brand-50 p-4 text-sm text-brand-900">{m.trips.empty}</p>}
      <ul className="space-y-3">
        {trips.map((trip) => (
          <li key={trip.confirmationId} className="rounded-2xl bg-white p-4 shadow-card ring-1 ring-ink-100">
            <div className="flex items-start gap-3">
              <TrainIcon size={22} className="mt-0.5 text-brand-600" />
              <div className="flex-1 text-sm">
                <p className="font-bold text-brand-900">{trip.trainNo} {trip.trainName}</p>
                <p className="text-ink-700">{trip.fromLabel} → {trip.toLabel}</p>
                <p className="text-xs text-ink-500">
                  {trip.journeyDate ? formatDate(trip.journeyDate) : ''} · {formatTime(trip.departure)} → {formatTime(trip.arrival)} · {trip.passengers ?? '?'} pax
                </p>
                <p className="mt-1 text-[11px] text-ink-500">Ref {trip.confirmationId}</p>
              </div>
              <ModeBadge mode={trip.dataMode} />
            </div>
            <button type="button" onClick={() => setTrips(removeTrip(trip.confirmationId))}
              className="mt-2 text-xs font-semibold text-red-700">{m.trips.remove}</button>
          </li>
        ))}
      </ul>
    </Page>
  )
}

export function Alerts() {
  const { m } = useApp()
  return (
    <Page title={m.alerts.title}>
      <p className="flex items-start gap-2 rounded-2xl bg-brand-50 p-4 text-sm text-brand-900">
        <BellIcon size={20} className="shrink-0 text-brand-600" /> {m.alerts.body}
      </p>
    </Page>
  )
}

export function Profile() {
  const { planner, go, m } = useApp()
  const h = planner.health
  const provider = h?.data_provider
  return (
    <Page title={m.profile.title}>
      <section className="rounded-2xl bg-white p-4 shadow-card ring-1 ring-ink-100">
        <h2 className="flex items-center gap-2 text-sm font-bold text-brand-900"><GlobeIcon size={18} /> {m.profile.language}</h2>
        <div className="mt-2 flex gap-2">
          {(['en', 'ta'] as Language[]).map((code) => (
            <button key={code} type="button" aria-pressed={planner.language === code} onClick={() => planner.setLanguage(code)}
              className={`flex-1 rounded-xl py-2 text-sm font-semibold ${planner.language === code ? 'bg-brand-600 text-white' : 'bg-ink-100 text-ink-700'}`}>
              {code === 'en' ? 'English' : 'தமிழ்'}
            </button>
          ))}
        </div>
      </section>
      <section className="space-y-2 rounded-2xl bg-white p-4 text-sm shadow-card ring-1 ring-ink-100">
        <p className="flex items-center justify-between"><span className="text-ink-500">{m.profile.dataSource}</span>
          <span className="flex items-center gap-2">{provider?.active ?? '—'} <ModeBadge mode={h?.data_mode} /></span></p>
        {provider?.reason && <p className="text-xs text-red-700">{provider.reason}</p>}
        <p className="flex items-center justify-between"><span className="text-ink-500">{m.profile.ai}</span>
          <span>{h?.ai?.active ? 'Claude (AWS Bedrock)' : 'Built-in parser'}</span></p>
      </section>
      <p className="flex items-start gap-2 text-xs text-ink-500"><InfoIcon size={16} className="shrink-0" /> {m.profile.noAccount}</p>
      <button type="button" onClick={() => go('classic')} className="text-sm font-semibold text-brand-600 underline">{m.profile.classic}</button>
    </Page>
  )
}
