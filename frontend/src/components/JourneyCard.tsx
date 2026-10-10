import { useState } from 'react'
import type { Recommendation } from '../api/types'
import type { Strings } from '../i18n/strings'
import { formatDay, formatDuration, formatRupees, formatTime } from '../utils/format'

interface Props {
  t: Strings
  rec: Recommendation
  passengers: number
  selected: boolean
  disabled: boolean
  onSelect: () => void
}

const CHECK_STYLE = { met: 'text-emerald-700', violated: 'text-red-700', unverified: 'text-amber-700', not_applicable: 'text-slate-500' }
const NEED_STYLE = { verified_supported: 'bg-emerald-50 text-emerald-800', not_supported: 'bg-red-50 text-red-800', unknown: 'bg-amber-50 text-amber-900' }

export function JourneyCard({ t, rec, passengers, selected, disabled, onSelect }: Props) {
  const [open, setOpen] = useState(false)
  const o = rec.option
  const trains = o.legs.map((l) => `${l.train_no} ${l.train_name}`).join(' → ')
  return (
    <article
      aria-label={`${rec.labels.map((l) => t.categories[l]).join(', ')}: ${trains}`}
      className={`rounded-lg border bg-white p-4 shadow-sm ${selected ? 'border-rail-600 ring-2 ring-rail-600' : 'border-slate-200'}`}
    >
      <div className="mb-2 flex flex-wrap gap-1.5">
        {rec.labels.map((l) => (
          <span key={l} className="rounded-full bg-rail-50 px-2 py-0.5 text-xs font-semibold text-rail-700">{t.categories[l]}</span>
        ))}
        {o.provenance.mode === 'live' && (
          <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-900">{t.liveBadge}</span>
        )}
        {!rec.fully_compliant && (
          <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-900">{t.notFullyCompliant}</span>
        )}
      </div>
      <h3 className="font-medium text-slate-900">{trains}</h3>
      <div className="mt-1 grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
        <div><span className="text-slate-500">{o.legs[0].from_name}</span><br />{formatTime(o.departure)} · {formatDay(o.departure)}</div>
        <div><span className="text-slate-500">{o.legs[o.legs.length - 1].to_name}</span><br />{formatTime(o.arrival)} · {formatDay(o.arrival)}</div>
        <div><span className="text-slate-500">{formatDuration(o.duration_minutes)}</span><br />{o.transfers ? `${o.transfers} ${t.changes}` : t.direct}</div>
        <div>
          {rec.total_fare !== null && rec.fare_per_passenger !== null ? (
            <>
              <span className="text-slate-500">{rec.selected_class} · {formatRupees(rec.fare_per_passenger)} {t.perPassenger}</span><br />
              <strong>{t.total} {formatRupees(rec.total_fare)}</strong> <span className="text-xs text-slate-500">({passengers})</span>
            </>
          ) : (
            <>
              <span className="text-slate-500">{o.classes.length ? o.classes.join(' · ') : t.classesUnknown}</span><br />
              <strong className="text-amber-800">{t.fareUnknown}</strong>
            </>
          )}
        </div>
      </div>
      {o.provenance.mode === 'live' && (
        <p className="mt-1 text-xs text-emerald-800">
          {o.provenance.source} · {t.retrievedAt} {formatTime(o.provenance.as_of)} IST · {t.scheduledTimes}
        </p>
      )}
      {o.simulated_change && <p className="mt-2 rounded bg-red-50 px-2 py-1 text-sm text-red-800">{o.simulated_change}</p>}
      <p className="mt-2 text-sm text-slate-700">{rec.explanation}</p>
      {rec.unverified.map((u) => (
        <p key={u} className="mt-1 rounded bg-amber-50 px-2 py-1 text-sm text-amber-900">⚠ {u}</p>
      ))}

      {open && (
        <div className="mt-3 space-y-2 text-sm">
          <Section title={t.hardConstraints}>
            {rec.hard_constraints.map((c) => <li key={c.name} className={CHECK_STYLE[c.status]}>{c.status === 'met' ? '✓' : c.status === 'violated' ? '✗' : '?'} {c.detail}</li>)}
          </Section>
          {rec.need_statuses.length > 0 && (
            <Section title={t.labels.passenger_needs}>
              {rec.need_statuses.map((n) => (
                <li key={n.need}><span className={`rounded px-1.5 ${NEED_STYLE[n.status]}`}>{t.verification[n.status]}</span> {n.detail}</li>
              ))}
            </Section>
          )}
          {rec.preference_matches.length > 0 && <Section title={t.preferenceMatches}>{rec.preference_matches.map((m) => <li key={m}>{m}</li>)}</Section>}
          {rec.tradeoffs.length > 0 && <Section title={t.tradeoffs}>{rec.tradeoffs.map((m) => <li key={m}>{m}</li>)}</Section>}
          {o.legs.length > 1 && (
            <Section title="Legs">
              {o.legs.map((l) => <li key={l.train_no}>{l.train_no}: {l.from_name} {formatTime(l.departure)} → {l.to_name} {formatTime(l.arrival)}</li>)}
            </Section>
          )}
          <p className="text-xs text-slate-500">{t.dataSource}: {o.provenance.source}. {o.provenance.note}</p>
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" onClick={onSelect} disabled={disabled || selected} aria-pressed={selected}
          className="rounded bg-rail-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-rail-700 disabled:opacity-60">
          {selected ? t.selected : t.select}
        </button>
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
          className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50">
          {open ? t.hideDetails : t.details}
        </button>
      </div>
    </article>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="font-medium text-slate-700">{title}</h4>
      <ul className="ml-4 list-none space-y-0.5">{children}</ul>
    </div>
  )
}
