// Bottom-navigation pages: My Trips (device-local saved plans), Alerts (Live departures & ML delay), Profile.
import { useState, useEffect, useRef } from 'react'
import { ApiError } from '../../api/client'
import { errorText } from '../../api/errorText'
import type { DelayPrediction, DepartureBoard, Language } from '../../api/types'
import { formatDate, formatTime } from '../../utils/format'
import { fill } from '../strings'
import {
  BellIcon,
  GlobeIcon,
  InfoIcon,
  RefreshIcon,
  TrainIcon,
} from '../icons'
import { useApp } from '../PlannerContext'
import { loadTrips, removeTrip, type SavedTrip } from '../trips'
import { ProvenanceBadge } from '../../components/ProvenanceBadge'
import { Logo, Screen } from '../ui'

function Page({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Screen nav header={<header className="px-4 py-3"><Logo /></header>}>
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
                  {trip.journeyDate ? formatDate(trip.journeyDate) : ''} · {formatTime(trip.departure)} → {formatTime(trip.arrival)} · {trip.passengers ?? '?'} {trip.passengers === 1 ? m.options.passenger : m.options.passengers}
                </p>
                <p className="mt-1 text-[11px] text-ink-500">{m.trips.ref} {trip.confirmationId}</p>
              </div>
              <ProvenanceBadge provenance={null} mode={trip.dataMode} labels={{ live: m.live }} />
            </div>
            <button type="button" onClick={() => setTrips(removeTrip(trip.confirmationId))}
              className="mt-2 text-xs font-semibold text-red-700">{m.trips.remove}</button>
          </li>
        ))}
      </ul>
    </Page>
  )
}

/** Passenger copy for a failed call in the screen's language; `fallback` when there is no specific copy. */
function failureMessage(err: unknown, fallback: string, m: Parameters<typeof errorText>[1], lang: Language): string {
  const text = errorText(err, m, lang)
  return text === m.errors.generic ? fallback : text
}

function DelayResult({ prediction }: { prediction: DelayPrediction }) {
  const { m } = useApp()
  const d = m.alerts.delay
  const p = prediction
  return (
    <div className="mt-3 rounded-xl bg-ink-100/60 p-3" data-testid="delay-result">
      <div className="flex items-center justify-between">
        <span className="text-xs font-bold text-ink-900">{d.train} {p.train_number} {fill(d.atStation, { station: p.station_code })}</span>
        {p.risk_level && (
          <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${
            p.risk_level === 'LOW' ? 'bg-match-50 text-match-700'
              : p.risk_level === 'MODERATE' ? 'bg-amber-50 text-amber-800' : 'bg-red-50 text-red-700'
          }`}>
            {d.risk[p.risk_level]}
          </span>
        )}
      </div>
      {p.predicted_delay_minutes === null ? (
        <p className="mt-2 text-xs text-ink-500">{d.noData}</p>
      ) : (
        <div className="mt-2 grid grid-cols-2 gap-2 text-center text-xs">
          <div className="rounded-lg bg-white p-2">
            <span className="block text-[10px] text-ink-500">{d.typical}</span>
            <span className="font-extrabold text-brand-900">{fill(d.typicalValue, { n: p.predicted_delay_minutes })}</span>
          </div>
          {p.on_time_probability !== null && (
            <div className="rounded-lg bg-white p-2">
              <span className="block text-[10px] text-ink-500">{fill(d.onTime, { n: p.on_time_threshold_minutes })}</span>
              <span className="font-extrabold text-brand-600">{Math.round(p.on_time_probability * 100)}%</span>
            </div>
          )}
        </div>
      )}
      <dl className="mt-2 space-y-0.5 text-[11px] text-ink-500" data-testid="delay-basis">
        <div className="flex justify-between"><dt>{d.basis[p.basis]}</dt><dd>{d.modelVersion} {p.model_version}</dd></div>
        {p.mae_minutes !== null && (
          <div className="flex justify-between"><dt>{d.mae}</dt><dd>{fill(d.maeValue, { n: p.mae_minutes })}</dd></div>
        )}
      </dl>
      <ProvenanceBadge provenance={p.provenance} variant="full" className="mt-2" unavailableTitle={d.unavailableTitle} />
    </div>
  )
}

export function Alerts() {
  const { m, planner } = useApp()
  const client = planner.client
  const [selectedStation, setSelectedStation] = useState('MAS')
  const [board, setBoard] = useState<DepartureBoard | null>(null)
  const [boardError, setBoardError] = useState<string | null>(null)
  const [loadingLive, setLoadingLive] = useState(false)

  // Delay predictor state
  const [predictTrainNo, setPredictTrainNo] = useState('12658')
  const [prediction, setPrediction] = useState<DelayPrediction | null>(null)
  const [predictionError, setPredictionError] = useState<string | null>(null)
  const [loadingPred, setLoadingPred] = useState(false)
  const boardCall = useRef<AbortController | null>(null)

  const fetchLiveBoard = async (code: string) => {
    boardCall.current?.abort() // a slower earlier station must not overwrite the current one
    const call = new AbortController()
    boardCall.current = call
    setLoadingLive(true)
    setBoardError(null)
    try {
      const res = await client.departures(code, { signal: call.signal })
      if (!call.signal.aborted) setBoard(res)
    } catch (err) {
      if (call.signal.aborted || (err instanceof ApiError && err.isAborted)) return
      setBoard(null)
      setBoardError(failureMessage(err, fill(m.alerts.board.loadFailed, { station: code }), m, planner.language))
    } finally {
      if (!call.signal.aborted) setLoadingLive(false)
    }
  }

  useEffect(() => {
    fetchLiveBoard(selectedStation)
    // A delay estimate is for one station: never leave the previous station's result under the new board.
    setPrediction(null)
    setPredictionError(null)
    return () => boardCall.current?.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedStation])

  const runDelayPrediction = async () => {
    setLoadingPred(true)
    setPredictionError(null)
    try {
      setPrediction(await client.predictDelay(predictTrainNo.trim(), selectedStation))
    } catch (err) {
      setPrediction(null)
      setPredictionError(failureMessage(err, m.alerts.delay.unavailableTitle, m, planner.language))
    } finally {
      setLoadingPred(false)
    }
  }

  const d = m.alerts.delay
  return (
    <Page title={m.alerts.title}>
      {/* Required test & standard notice */}
      <p className="flex items-start gap-2 rounded-2xl bg-brand-50 p-4 text-sm text-brand-900">
        <BellIcon size={20} className="shrink-0 text-brand-600" /> {m.alerts.body}
      </p>

      {/* Delay estimate from historical records */}
      <section className="rounded-2xl bg-white p-4 shadow-card ring-1 ring-ink-100">
        <span className="rounded bg-brand-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-brand-800">{d.badge}</span>
        <h2 className="mt-1 text-sm font-bold text-brand-900">{d.title}</h2>
        <p className="text-xs text-ink-500">{d.intro}</p>

        <div className="mt-3 flex gap-2">
          <input
            type="text"
            value={predictTrainNo}
            onChange={(e) => setPredictTrainNo(e.target.value)}
            placeholder={d.trainPlaceholder}
            aria-label={d.train}
            className="flex-1 rounded-xl border border-ink-300 px-3 py-2 text-xs font-semibold text-ink-900"
          />
          <button
            type="button"
            onClick={runDelayPrediction}
            disabled={loadingPred}
            className="rounded-xl bg-brand-600 px-4 py-2 text-xs font-bold text-white hover:bg-brand-700 disabled:opacity-50"
          >
            {loadingPred ? d.predicting : d.predict}
          </button>
        </div>

        {predictionError && (
          <div className="mt-3">
            <ProvenanceBadge provenance={null} variant="full" unavailableTitle={d.unavailableTitle} reason={predictionError} />
          </div>
        )}
        {prediction && <DelayResult prediction={prediction} />}
      </section>

      {/* Live station departure board */}
      <section className="rounded-2xl bg-white p-4 shadow-card ring-1 ring-ink-100">
        <div className="flex items-center justify-between">
          <span className="text-xs font-bold text-brand-900">{m.alerts.board.title}</span>
          <button
            type="button"
            onClick={() => fetchLiveBoard(selectedStation)}
            className="text-brand-600 hover:text-brand-800"
            title={m.alerts.board.refresh}
            aria-label={m.alerts.board.refresh}
          >
            <RefreshIcon size={16} />
          </button>
        </div>

        <div className="mt-3 flex gap-2">
          {(['MAS', 'NDLS', 'SBC'] as const).map((code) => (
            <button
              key={code}
              type="button"
              aria-pressed={selectedStation === code}
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
            <p className="py-4 text-center text-xs text-ink-500">{m.alerts.board.loading}</p>
          ) : !board ? (
            <ProvenanceBadge provenance={null} variant="full" unavailableTitle={m.alerts.board.unavailableTitle}
              reason={boardError ?? fill(m.alerts.board.loadFailed, { station: selectedStation })} />
          ) : board.provenance.mode === 'unavailable' ? (
            <ProvenanceBadge provenance={{ ...board.provenance, note: board.reason ?? board.provenance.note }}
              variant="full" unavailableTitle={m.alerts.board.unavailableTitle} />
          ) : board.departures.length === 0 ? (
            <p className="py-3 text-center text-xs text-ink-500">{m.alerts.board.empty}</p>
          ) : (
            board.departures.map((tr) => (
              <div key={tr.train_no} className="flex items-center justify-between rounded-xl border border-ink-100 p-2.5 hover:bg-brand-50/50">
                <div className="space-y-0.5">
                  <div className="flex items-center gap-1.5">
                    <span className="font-mono text-xs font-bold text-brand-900">{tr.train_no}</span>
                    <span className="truncate text-xs font-semibold text-ink-900 max-w-[150px]">{tr.train_name}</span>
                  </div>
                  <p className="text-[10px] text-ink-500">
                    {fill(m.alerts.board.departsTowards, { time: formatTime(tr.scheduled_departure), places: tr.towards.map((t) => t.name).join(', ') })}
                  </p>
                </div>
                <span className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-bold ${
                  tr.cancelled ? 'bg-red-50 text-red-600' : tr.delay_minutes ? 'bg-amber-50 text-amber-700' : 'bg-ink-100 text-ink-700'
                }`}>
                  {tr.cancelled ? m.alerts.board.cancelled : tr.delay_minutes === null ? m.alerts.board.statusUnknown
                    : tr.delay_minutes === 0 ? m.alerts.board.onTime : fill(m.alerts.board.delayed, { n: tr.delay_minutes })}
                </span>
              </div>
            ))
          )}
          {!loadingLive && board && board.provenance.mode !== 'unavailable' && (
            <>
              {!board.complete && (
                <p role="alert" data-testid="board-incomplete" className="rounded-lg bg-amber-50 p-2 text-[11px] text-amber-800">
                  {m.alerts.board.incomplete}
                </p>
              )}
              <p className="text-[11px] text-ink-500">{m.alerts.board.coverage}</p>
              <ProvenanceBadge provenance={board.provenance} variant="full" />
            </>
          )}
        </div>
      </section>
    </Page>
  )
}

export function Profile() {
  const { planner, m } = useApp()
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
          <span className="flex items-center gap-2">{provider?.active === 'demo' ? m.profile.builtInData : (provider?.active ?? '—')} {h && <ProvenanceBadge provenance={null} mode={h.data_mode} labels={{ live: m.live }} />}</span></p>
        {provider?.reason && <p className="text-xs text-red-700">{provider.reason}</p>}
        <p className="flex items-center justify-between"><span className="text-ink-500">{m.profile.ai}</span>
          <span>{h?.ai?.active ? fill(m.profile.aiActive, { provider: String(h.ai.provider ?? '') }) : m.profile.aiInactive}</span></p>
      </section>
      <p className="flex items-start gap-2 text-xs text-ink-500"><InfoIcon size={16} className="shrink-0" /> {m.profile.noAccount}</p>
    </Page>
  )
}
