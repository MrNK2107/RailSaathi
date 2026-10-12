// UI preview only. No navigation, map, GPS or platform data is connected (out of scope).
import { useState } from 'react'
import { formatDay, formatTime } from '../../utils/format'
import {
  AccessibleIcon,
  ArrowRight,
  ChevronRight,
  CompassIcon,
  MapIcon,
  PinIcon,
  SearchIcon,
  StepsIcon,
  TrainIcon,
  WalkIcon,
} from '../icons'
import { useApp } from '../PlannerContext'
import { AppHeader, PreviewNotice, Screen, selectedRecommendation } from '../ui'
import StationBlueprintModal from '../../components/StationBlueprintModal'

const PLACEHOLDER_PLATFORMS = [12, 11, 10, 9, 8, 7]

const GATES = [
  { id: 'gate_1', name: 'Wall Tax Rd (Gate 1)', desc: 'Near Suburban Entry', distBase: 240 },
  { id: 'gate_main', name: 'Main Porch (Central)', desc: 'Main Concourse & Ticket Hall', distBase: 180 },
  { id: 'gate_ev', name: 'EV Cab Drop (South)', desc: 'Direct Ramp Access', distBase: 290 },
]

const COACHES = ['ENG', 'GEN', 'S1', 'S2', 'S3', 'B1', 'B2', 'B3', 'B4', 'A1', 'A2', 'H1', 'SLR']

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
  const [blueprintOpen, setBlueprintOpen] = useState(false)
  const [selectedGate, setSelectedGate] = useState(GATES[1].id)
  const [targetCoach, setTargetCoach] = useState('B4')
  const [showArCompass, setShowArCompass] = useState(false)

  const rec = selectedRecommendation(planner.state)
  const leg = rec?.option.legs[0]
  const gateObj = GATES.find((g) => g.id === selectedGate) || GATES[1]
  const coachIndex = COACHES.indexOf(targetCoach)
  const calculatedDistance = gateObj.distBase + Math.max(0, coachIndex * 24)
  const walkMinutes = (calculatedDistance / 75).toFixed(1)
  const pillarHaltingNumber = Math.max(1, Math.min(24, Math.round(coachIndex * 1.8) + 2))

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

      {/* 2D Concourse Blueprint Launch Card (Pillar 5) */}
      <section className="mx-4 mb-3 rounded-2xl border border-brand-200 bg-brand-50/70 p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="rounded bg-brand-600 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white">Pillar 5 Map</span>
            <span className="text-xs font-bold text-brand-900">Station Concourse Blueprint</span>
          </div>
          <span className="flex items-center gap-1 text-[11px] font-semibold text-brand-700">
            <AccessibleIcon size={14} /> Step-free
          </span>
        </div>
        <p className="mt-1.5 text-xs text-ink-700">
          Interactive 2D concourse layout showing ramps, elevators, restrooms, and accessible paths.
        </p>
        <button
          type="button"
          onClick={() => setBlueprintOpen(true)}
          className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl bg-brand-600 px-4 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-brand-700"
        >
          <MapIcon size={16} /> Open 2D Station Blueprint
        </button>
      </section>

      {/* Curbside-to-Coach Wayfinder & Pillar Halting Decoder (Pillar 3) */}
      <section className="mx-4 mb-3 rounded-2xl bg-white p-4 shadow-card ring-1 ring-ink-100">
        <div className="flex items-center justify-between">
          <span className="rounded bg-brand-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-brand-800">Pillar 3 Wayfinder</span>
          <span className="text-[11px] font-medium text-ink-500">600m Pillar Decoder</span>
        </div>
        <h3 className="mt-1 text-sm font-bold text-brand-900">Curbside Entry & Coach Halting</h3>

        <div className="mt-3 space-y-2">
          <label className="block text-xs font-semibold text-ink-700">
            Entry Curbside Gate:
            <select
              value={selectedGate}
              onChange={(e) => setSelectedGate(e.target.value)}
              className="mt-1 w-full rounded-xl border border-ink-300 bg-white px-3 py-2 text-xs font-medium text-ink-900 shadow-sm focus:border-brand-600 focus:outline-none"
            >
              {GATES.map((g) => (
                <option key={g.id} value={g.id}>{g.name} — {g.desc}</option>
              ))}
            </select>
          </label>

          <label className="block text-xs font-semibold text-ink-700">
            Target Coach:
            <div className="mt-1 flex flex-wrap gap-1">
              {COACHES.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setTargetCoach(c)}
                  className={`rounded-lg px-2.5 py-1 text-xs font-semibold ${
                    targetCoach === c
                      ? 'bg-brand-600 text-white'
                      : 'bg-ink-100 text-ink-700 hover:bg-brand-50'
                  }`}
                >
                  {c}
                </button>
              ))}
            </div>
          </label>
        </div>

        {/* Decoder Output Metric Badges */}
        <div className="mt-4 grid grid-cols-3 gap-2 rounded-xl bg-ink-100/60 p-2.5 text-center">
          <div>
            <span className="block text-[10px] font-semibold text-ink-500">Walk Distance</span>
            <span className="text-xs font-extrabold text-brand-900">{calculatedDistance} m</span>
          </div>
          <div>
            <span className="block text-[10px] font-semibold text-ink-500">Est. Walk</span>
            <span className="text-xs font-extrabold text-brand-900">{walkMinutes} mins</span>
          </div>
          <div>
            <span className="block text-[10px] font-semibold text-ink-500">Stop Position</span>
            <span className="text-xs font-extrabold text-brand-600">Pillar #{pillarHaltingNumber}</span>
          </div>
        </div>

        {/* AR Bearing HUD Toggle */}
        <div className="mt-3">
          <button
            type="button"
            onClick={() => setShowArCompass(!showArCompass)}
            className="flex w-full items-center justify-between rounded-xl border border-ink-200 bg-white px-3 py-2 text-xs font-semibold text-ink-700 hover:bg-brand-50"
          >
            <span className="flex items-center gap-1.5"><CompassIcon size={16} className="text-brand-600" /> AR Bearing Compass HUD</span>
            <span className="text-[11px] text-brand-600">{showArCompass ? 'Hide' : 'Show'}</span>
          </button>
          {showArCompass && (
            <div className="mt-2 flex items-center justify-between rounded-xl bg-ink-900 p-3 text-white">
              <div className="flex items-center gap-3">
                <div className="grid h-10 w-10 place-items-center rounded-full bg-brand-600 font-mono text-xs font-bold text-white shadow-inner">
                  035°
                </div>
                <div>
                  <p className="text-xs font-bold text-white">Heading: NNE (Platform 10)</p>
                  <p className="text-[10px] text-ink-300">Walk straight through central concourse</p>
                </div>
              </div>
              <WalkIcon size={20} className="text-brand-300" />
            </div>
          )}
        </div>
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

      <StationBlueprintModal
        isOpen={blueprintOpen}
        onClose={() => setBlueprintOpen(false)}
        initialStation="chennai_central"
        initialTargetPlatform="10"
      />
    </Screen>
  )
}
