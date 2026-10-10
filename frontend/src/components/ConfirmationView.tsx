import type { SessionState } from '../api/types'
import type { Strings } from '../i18n/strings'
import { formatDate, formatDay, formatDuration, formatRupees, formatTime } from '../utils/format'

interface Props {
  t: Strings
  state: SessionState
  disabled: boolean
  onConfirm: () => void
  onBack: () => void
}

export function ConfirmationView({ t, state, disabled, onConfirm, onBack }: Props) {
  const rec = state.recommendations?.recommendations.find((r) => r.option.option_id === state.selected_option_id)
  if (!rec) return null
  const j = state.journey
  const o = rec.option
  return (
    <section aria-labelledby="confirm-title" className="rounded-lg border-2 border-rail-600 bg-white p-4 shadow">
      <h2 id="confirm-title" className="font-semibold text-slate-900">{t.confirmTitle}</h2>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <dt className="text-slate-500">{t.labels.origin} → {t.labels.destination}</dt>
        <dd>{j.origin?.label} → {j.destination?.label}</dd>
        <dt className="text-slate-500">{t.labels.journey_date}</dt>
        <dd>{j.journey_date && formatDate(j.journey_date)}</dd>
        <dt className="text-slate-500">{t.labels.passenger_count}</dt>
        <dd>{j.passenger_count}</dd>
        <dt className="text-slate-500">Train(s)</dt>
        <dd>{o.legs.map((l) => `${l.train_no} ${l.train_name}`).join(' → ')}</dd>
        <dt className="text-slate-500">Timing</dt>
        <dd>{formatTime(o.departure)} {formatDay(o.departure)} → {formatTime(o.arrival)} {formatDay(o.arrival)} ({formatDuration(o.duration_minutes)})</dd>
        <dt className="text-slate-500">{t.labels.class_preference}</dt>
        <dd>{rec.selected_class ?? (o.classes.join(', ') || t.classesUnknown)}</dd>
        <dt className="text-slate-500">{t.total}</dt>
        <dd>
          {rec.total_fare !== null ? formatRupees(rec.total_fare) : t.fareUnknown}{' '}
          <span className="text-xs text-amber-800">({o.provenance.mode === 'live' ? t.fareSourceLive : t.fareSourceListed})</span>
        </dd>
      </dl>
      {rec.unverified.map((u) => <p key={u} className="mt-2 rounded bg-amber-50 px-2 py-1 text-sm text-amber-900">⚠ {u}</p>)}
      <p className="mt-3 rounded bg-slate-100 px-3 py-2 text-sm font-medium text-slate-800">{t.noBooking}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" onClick={onConfirm} disabled={disabled}
          className="rounded bg-emerald-700 px-4 py-2 font-medium text-white hover:bg-emerald-800 disabled:opacity-60">
          {t.confirmBtn}
        </button>
        <button type="button" onClick={onBack} disabled={disabled} className="rounded border border-slate-300 px-4 py-2 hover:bg-slate-50">
          {t.backToOptions}
        </button>
      </div>
    </section>
  )
}

export function ConfirmedView({ t, state }: { t: Strings; state: SessionState }) {
  const conf = state.confirmation
  if (!conf) return null
  return (
    <section aria-labelledby="confirmed-title" className="rounded-lg border border-emerald-300 bg-emerald-50 p-4">
      <h2 id="confirmed-title" className="font-semibold text-emerald-900">✓ {t.confirmedTitle} — {conf.confirmation_id}</h2>
      <p className="mt-1 text-sm font-medium text-emerald-900">{t.confirmedNoBooking}</p>
      <details className="mt-2 text-sm">
        <summary className="cursor-pointer text-emerald-900">{t.handoffPayload}</summary>
        <pre className="mt-2 max-h-80 overflow-auto rounded bg-white p-2 text-xs text-slate-800">{JSON.stringify(conf.handoff, null, 2)}</pre>
      </details>
    </section>
  )
}
