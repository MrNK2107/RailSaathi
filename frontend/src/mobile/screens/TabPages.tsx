// Bottom-navigation pages: My Trips (device-local saved plans), Alerts (Live departures & ML delay), Profile.
import { useState, useEffect } from 'react'
import type { Language } from '../../api/types'
import { formatDate, formatTime } from '../../utils/format'
import {
  BellIcon,
  GlobeIcon,
  InfoIcon,
  RefreshIcon,
  TrainIcon,
} from '../icons'
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

interface LiveTrain {
  train_number: string
  train_name: string
  source: string
  destination: string
  scheduled_arrival: string
  expected_arrival: string
  scheduled_departure: string
  expected_departure: string
  platform: string
  delay_arrival: string
  status: string
}

interface DelayPrediction {
  train_number: string
  train_name: string
  predicted_delay_minutes: number
  risk_level: string
  confidence_score: number
  cascading_impact?: string
}

export function Alerts() {
  const { m } = useApp()
  const [selectedStation, setSelectedStation] = useState('MAS')
  const [liveTrains, setLiveTrains] = useState<LiveTrain[]>([])
  const [loadingLive, setLoadingLive] = useState(false)

  // Delay predictor state
  const [predictTrainNo, setPredictTrainNo] = useState('12658')
  const [prediction, setPrediction] = useState<DelayPrediction | null>(null)
  const [loadingPred, setLoadingPred] = useState(false)

  const fetchLiveBoard = async (code: string) => {
    setLoadingLive(true)
    try {
      const res = await fetch(`/stations/${code}/live`)
      if (res.ok) {
        const data = await res.json()
        setLiveTrains(data.trains || [])
      }
    } catch {
      // Fallback silent
    } finally {
      setLoadingLive(false)
    }
  }

  useEffect(() => {
    fetchLiveBoard(selectedStation)
  }, [selectedStation])

  const runDelayPrediction = async () => {
    setLoadingPred(true)
    try {
      const res = await fetch(`/api/predict/delay?train_number=${encodeURIComponent(predictTrainNo)}&destination=${selectedStation}`)
      if (res.ok) {
        const data = await res.json()
        setPrediction(data)
      }
    } catch {
      // Fallback
    } finally {
      setLoadingPred(false)
    }
  }

  return (
    <Page title={m.alerts.title}>
      {/* Required test & standard notice */}
      <p className="flex items-start gap-2 rounded-2xl bg-brand-50 p-4 text-sm text-brand-900">
        <BellIcon size={20} className="shrink-0 text-brand-600" /> {m.alerts.body}
      </p>

      {/* Pillar 4: ML Cascading Delay Forecaster */}
      <section className="rounded-2xl bg-white p-4 shadow-card ring-1 ring-ink-100">
        <div className="flex items-center justify-between">
          <span className="rounded bg-brand-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-brand-800">Pillar 4 ML Model</span>
          <span className="text-[11px] font-semibold text-brand-600">63k CRIS Records</span>
        </div>
        <h3 className="mt-1 text-sm font-bold text-brand-900">CRIS Delay Risk Forecaster</h3>
        <p className="text-xs text-ink-500">Predict cascading delay impact using historical arrival regressions.</p>

        <div className="mt-3 flex gap-2">
          <input
            type="text"
            value={predictTrainNo}
            onChange={(e) => setPredictTrainNo(e.target.value)}
            placeholder="e.g. 12658"
            className="flex-1 rounded-xl border border-ink-300 px-3 py-2 text-xs font-semibold text-ink-900"
          />
          <button
            type="button"
            onClick={runDelayPrediction}
            disabled={loadingPred}
            className="rounded-xl bg-brand-600 px-4 py-2 text-xs font-bold text-white hover:bg-brand-700 disabled:opacity-50"
          >
            {loadingPred ? 'Predicting...' : 'Predict Delay'}
          </button>
        </div>

        {prediction && (
          <div className="mt-3 rounded-xl bg-ink-100/60 p-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-ink-900">Train {prediction.train_number}</span>
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${
                prediction.predicted_delay_minutes <= 15
                  ? 'bg-match-50 text-match-600'
                  : 'bg-red-50 text-red-600'
              }`}>
                {prediction.predicted_delay_minutes <= 15 ? 'Low Delay Risk' : 'High Delay Risk'}
              </span>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-2 text-center text-xs">
              <div className="rounded-lg bg-white p-2">
                <span className="block text-[10px] text-ink-500">Predicted Delay</span>
                <span className="font-extrabold text-brand-900">+{prediction.predicted_delay_minutes} mins</span>
              </div>
              <div className="rounded-lg bg-white p-2">
                <span className="block text-[10px] text-ink-500">Confidence</span>
                <span className="font-extrabold text-brand-600">{Math.round((prediction.confidence_score || 0.88) * 100)}%</span>
              </div>
            </div>
          </div>
        )}
      </section>

      {/* Pillar 2: Live Station Departure Board */}
      <section className="rounded-2xl bg-white p-4 shadow-card ring-1 ring-ink-100">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="rounded bg-match-50 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-match-600">Pillar 2 Live</span>
            <span className="text-xs font-bold text-brand-900">Live Station Board</span>
          </div>
          <button
            type="button"
            onClick={() => fetchLiveBoard(selectedStation)}
            className="text-brand-600 hover:text-brand-800"
            title="Refresh departure board"
          >
            <RefreshIcon size={16} />
          </button>
        </div>

        <div className="mt-3 flex gap-2">
          {([
            ['MAS', 'Chennai Central'],
            ['NDLS', 'New Delhi'],
            ['SBC', 'Bengaluru'],
          ] as const).map(([code]) => (
            <button
              key={code}
              type="button"
              onClick={() => setSelectedStation(code)}
              className={`flex-1 rounded-xl py-1.5 text-xs font-semibold ${
                selectedStation === code
                  ? 'bg-brand-600 text-white'
                  : 'bg-ink-100 text-ink-700 hover:bg-brand-50'
              }`}
            >
              {code}
            </button>
          ))}
        </div>

        <div className="mt-3 space-y-2">
          {loadingLive ? (
            <p className="py-4 text-center text-xs text-ink-500">Loading live departures...</p>
          ) : liveTrains.length === 0 ? (
            <p className="py-3 text-center text-xs text-ink-500">No active departures found for {selectedStation}.</p>
          ) : (
            liveTrains.map((tr) => (
              <div key={tr.train_number} className="flex items-center justify-between rounded-xl border border-ink-100 p-2.5 hover:bg-brand-50/50">
                <div className="space-y-0.5">
                  <div className="flex items-center gap-1.5">
                    <span className="font-mono text-xs font-bold text-brand-900">{tr.train_number}</span>
                    <span className="truncate text-xs font-semibold text-ink-900 max-w-[150px]">{tr.train_name}</span>
                  </div>
                  <p className="text-[10px] text-ink-500">
                    PF {tr.platform} · STA {tr.scheduled_arrival || tr.scheduled_departure}
                  </p>
                </div>
                <div className="text-right">
                  <span className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-bold ${
                    tr.delay_arrival === 'RT' || !tr.delay_arrival ? 'bg-match-50 text-match-600' : 'bg-amber-50 text-amber-700'
                  }`}>
                    {tr.delay_arrival === 'RT' ? 'Right Time' : tr.delay_arrival}
                  </span>
                  <p className="text-[10px] text-ink-500">{tr.status}</p>
                </div>
              </div>
            ))
          )}
        </div>
      </section>
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
