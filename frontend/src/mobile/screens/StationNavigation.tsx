// UI preview only. No navigation, map, GPS or platform data is connected (out of scope).
import { useState } from 'react'
import { formatDay, formatTime } from '../../utils/format'
import { AccessibleIcon, ArrowRight, ChevronRight, MapIcon, PinIcon, SearchIcon, StepsIcon, TrainIcon } from '../icons'
import { useApp } from '../PlannerContext'
import { AppHeader, PreviewNotice, Screen, selectedRecommendation } from '../ui'

const PLACEHOLDER_PLATFORMS = [12, 11, 10, 9, 8, 7]

function PlaceholderMap() {
  return (
    <div className="relative mt-3 h-72 overflow-hidden rounded-2xl bg-[#e8eef8] ring-1 ring-ink-100" aria-label="Illustrative map placeholder">
      <div className="absolute right-6 top-4 space-y-2.5">
        {PLACEHOLDER_PLATFORMS.map((p) => (
          <div key={p} className="w-40 rounded-md bg-brand-100 px-3 py-1.5 text-center text-xs font-semibold text-brand-900 ring-1 ring-brand-200">
            Platform {p}
          </div>
        ))}
      </div>
      <svg aria-hidden viewBox="0 0 300 280" className="absolute inset-0 h-full w-full">
        <path d="M40 200 V150 H170 Q190 150 190 130 V95" fill="none" stroke="#1a56db" strokeWidth="4" strokeDasharray="2 0" />
        <circle cx="40" cy="200" r="7" fill="#1a56db" /><circle cx="190" cy="92" r="7" fill="#ef4444" />
      </svg>
      <span className="absolute bottom-16 left-3 rounded bg-white/90 px-2 py-0.5 text-[10px] font-semibold text-ink-700">Entrance</span>
      <span className="absolute bottom-2 left-2 rounded bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-900">Illustration — not a real station map</span>
    </div>
  )
}

export default function StationNavigation() {
  const { planner, m } = useApp()
  const [view, setView] = useState<'map' | 'steps'>('map')
  const rec = selectedRecommendation(planner.state)
  const leg = rec?.option.legs[0]

  return (
    <Screen>
      <AppHeader />
      <PreviewNotice>{m.navigation.preview}</PreviewNotice>

      <section className="m-4 flex items-start gap-3 rounded-2xl bg-white p-4 shadow-card ring-1 ring-ink-100">
        <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand-50 text-brand-600"><TrainIcon size={22} /></span>
        {leg ? (
          <div className="text-sm">
            <p className="font-bold text-brand-900">{leg.train_no} {leg.train_name}</p>
            <p className="text-ink-500">{m.navigation.platform}: — · {formatTime(leg.departure)} ({formatDay(leg.departure)})</p>
          </div>
        ) : <p className="text-sm text-ink-500">{m.navigation.noTrain}</p>}
      </section>

      <div role="tablist" className="mx-4 flex gap-2">
        {([['map', m.navigation.mapView, MapIcon], ['steps', m.navigation.steps, StepsIcon]] as const).map(([key, label, Icon]) => (
          <button key={key} type="button" role="tab" aria-selected={view === key} onClick={() => setView(key)}
            className={`flex flex-1 items-center justify-center gap-1.5 rounded-xl py-2 text-sm font-semibold ${view === key ? 'bg-brand-600 text-white' : 'bg-white text-ink-700 ring-1 ring-ink-300'}`}>
            <Icon size={16} /> {label}
          </button>
        ))}
      </div>

      <section className="px-4 pt-3">
        <div className="flex items-center gap-2 text-sm">
          <PinIcon size={18} className="text-brand-600" />
          <span className="flex-1 font-semibold text-ink-900">{leg ? `${leg.from_name} (${leg.from_code})` : 'Station'}</span>
          <button type="button" disabled title={m.navigation.notAvailable} className="rounded-full bg-ink-100 px-2 py-0.5 text-[11px] text-ink-500">{m.navigation.changeStation}</button>
        </div>
        <label className="mt-2 flex items-center gap-2 rounded-xl bg-ink-100 px-3 py-2 text-sm text-ink-500">
          <SearchIcon size={16} />
          <input disabled placeholder={m.navigation.search} aria-label={m.navigation.search} className="flex-1 bg-transparent" />
        </label>
        {view === 'map' ? <PlaceholderMap /> : (
          <ol className="mt-3 space-y-2">
            {m.navigation.placeholderSteps.map((s, i) => (
              <li key={s} className="flex items-center gap-3 rounded-xl bg-white p-3 text-sm shadow-card ring-1 ring-ink-100">
                <span className="grid h-7 w-7 place-items-center rounded-full bg-brand-50 text-xs font-bold text-brand-700">{i + 1}</span> {s}
              </li>
            ))}
          </ol>
        )}
      </section>

      <div className="space-y-3 p-4">
        <button type="button" disabled aria-disabled
          className="flex w-full items-center justify-center gap-2 rounded-2xl bg-ink-300 px-4 py-3.5 text-base font-semibold text-white">
          {m.navigation.start} <ArrowRight size={20} /> <span className="text-xs font-normal">({m.navigation.notAvailable})</span>
        </button>
        <button type="button" disabled className="flex w-full items-center gap-3 rounded-2xl bg-white p-3 text-sm font-semibold text-ink-500 ring-1 ring-ink-100">
          <AccessibleIcon size={20} /> <span className="flex-1 text-left">{m.navigation.accessibility}</span>
          <span className="text-[11px] font-normal">{m.navigation.notAvailable}</span> <ChevronRight size={18} />
        </button>
      </div>
    </Screen>
  )
}
