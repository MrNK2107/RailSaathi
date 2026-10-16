import { useRef, useState } from 'react'
import { RELAX_PATCHES } from '../../api/relax'
import type { Category, Recommendation } from '../../api/types'
import { formatDate, formatDuration, formatRupees, formatTime } from '../../utils/format'
import { AlertIcon, ArrowRight, ChevronRight, EditIcon, RefreshIcon, SeatIcon, TrainIcon } from '../icons'
import { useApp } from '../PlannerContext'
import { ProvenanceBadge } from '../../components/ProvenanceBadge'
import { AppHeader, CategoryBadge, ErrorBanner, PrimaryButton, Screen, SourceLine } from '../ui'

const ORDER: Category[] = ['best_overall', 'lowest_cost', 'fastest']

function OptionCard({ rec, highlighted, onChoose, disabled }: {
  rec: Recommendation; highlighted: boolean; onChoose: () => void; disabled: boolean
}) {
  const { m } = useApp()
  const o = rec.option
  const leg = o.legs[0]
  const last = o.legs[o.legs.length - 1]
  const classes = rec.selected_class ? [rec.selected_class] : o.classes
  return (
    <article id={`opt-${o.option_id}`} aria-label={`${leg.train_no} ${leg.train_name}`}
      className={`rounded-2xl bg-white p-4 shadow-card ring-1 transition ${highlighted ? 'ring-2 ring-brand-500' : 'ring-ink-100'}`}>
      <div className="flex flex-wrap items-center gap-1.5">
        {rec.labels.length
          ? rec.labels.map((l) => <CategoryBadge key={l} category={l} />)
          : <span className="rounded-md bg-ink-100 px-2 py-1 text-xs font-semibold text-ink-700">{m.options.tabs.also}</span>}
        <span className="ml-auto"><ProvenanceBadge showSource provenance={o.provenance} labels={{ live: m.live }} unavailableTitle={m.dataUnavailable} /></span>
      </div>
      <button type="button" onClick={onChoose} disabled={disabled}
        className="mt-3 flex w-full items-start gap-3 text-left disabled:opacity-60">
        {/* Named by its visible text, prefixed for screen readers ("View details: D103 …"), never by a shorter label. */}
        <span className="sr-only">{m.options.choose}: </span>
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand-50 text-brand-600"><TrainIcon size={22} /></span>
        <span className="flex-1">
          <span className="flex items-start justify-between gap-2">
            <span>
              <span className="block text-base font-bold text-brand-900">{o.legs.map((l) => l.train_no).join(' + ')}</span>
              <span className="block text-sm text-ink-700">{o.legs.map((l) => l.train_name).join(' → ')}</span>
            </span>
            {rec.fare_per_passenger !== null ? (
              <span className="text-right">
                <span className="block text-lg font-extrabold text-brand-900">{formatRupees(rec.fare_per_passenger)}</span>
                <span className="block text-[11px] text-ink-500">{m.options.perPassenger}</span>
              </span>
            ) : (
              <span className="text-right text-xs font-semibold text-amber-700">{m.options.fareUnknown}</span>
            )}
          </span>
          <span className="mt-2 flex items-center gap-2 text-lg font-bold text-ink-900">
            {formatTime(o.departure)} <ArrowRight size={16} className="text-ink-500" /> {formatTime(o.arrival)}
            <ChevronRight size={18} className="ml-auto text-ink-500" />
          </span>
          <span className="block text-xs text-ink-500">
            {leg.from_code} → {last.to_code} · {formatDuration(o.duration_minutes)} · {o.transfers ? `${o.transfers} ${m.options.changes}` : m.options.direct}
          </span>
        </span>
      </button>
      <div className="mt-3 flex flex-wrap gap-1.5 text-[11px]">
        <span className="inline-flex items-center gap-1 rounded-full bg-ink-100 px-2 py-0.5 text-ink-700">
          <SeatIcon size={12} /> {classes.length ? classes.join(', ') : m.options.classesUnknown}
        </span>
        {rec.unverified.length > 0 && (
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-amber-800">
            <AlertIcon size={12} /> {rec.unverified.length} {m.options.unverified}
          </span>
        )}
      </div>
      {o.simulated_change && <p className="mt-2 rounded-lg bg-red-50 px-2 py-1 text-xs text-red-800">{o.simulated_change}</p>}
      <p className="mt-2 text-xs text-ink-700">{rec.explanation}</p>
    </article>
  )
}

export default function JourneyOptions() {
  const { planner, go, m } = useApp()
  const state = planner.state
  const rs = state?.recommendations ?? null
  const [active, setActive] = useState<Category | null>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const j = state?.journey

  const present = ORDER.filter((c) => rs?.recommendations.some((r) => r.labels.includes(c)))
  const choose = async (optionId: string) => {
    if (await planner.select(optionId)) go('details')
  }
  const focusTab = (c: Category) => {
    setActive(c)
    const rec = rs?.recommendations.find((r) => r.labels.includes(c))
    if (rec) document.getElementById(`opt-${rec.option.option_id}`)?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
  }

  return (
    <Screen header={<AppHeader />}>
      <h1 className="sr-only">{m.options.title}</h1>
      {j?.origin && j.destination && (
        <section className="flex items-start gap-2 border-b border-ink-100 px-4 py-3">
          <div className="flex-1">
            <p className="font-bold text-brand-900">{j.origin.label} → {j.destination.label}</p>
            <p className="text-xs text-ink-500">
              {j.journey_date ? formatDate(j.journey_date) : ''} · {j.passenger_count ?? '?'} {j.passenger_count === 1 ? m.options.passenger : m.options.passengers}
            </p>
          </div>
          <button type="button" onClick={() => go('plan')} className="inline-flex items-center gap-1 rounded-full bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-700">
            <EditIcon size={14} /> {m.fields.edit}
          </button>
        </section>
      )}

      <ErrorBanner />

      {present.length > 0 && (
        <div role="tablist" aria-label={m.options.title} className="flex gap-2 px-4 pt-3">
          {present.map((c) => (
            <button key={c} role="tab" type="button" aria-selected={(active ?? present[0]) === c} onClick={() => focusTab(c)}
              className={`flex-1 rounded-xl px-2 py-2 text-sm font-semibold ${(active ?? present[0]) === c ? 'bg-brand-600 text-white' : 'bg-white text-ink-700 ring-1 ring-ink-300'}`}>
              {m.options.tabs[c]}
            </button>
          ))}
        </div>
      )}

      <div ref={listRef} className="space-y-3 p-4">
        {rs && <SourceLine provenance={rs.provenance} />}
        {state?.reassessment && (
          <p className="rounded-xl bg-red-50 p-3 text-sm text-red-900">{state.reassessment.summary}</p>
        )}

        {rs?.recommendations.map((rec) => (
          <OptionCard key={rec.option.option_id} rec={rec} disabled={planner.loading}
            highlighted={Boolean(active && rec.labels.includes(active)) || state?.selected_option_id === rec.option.option_id}
            onChoose={() => choose(rec.option.option_id)} />
        ))}

        {rs && rs.recommendations.length === 0 && (
          <section role="alert" className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-900">
            <h2 className="font-bold">{m.options.noOptions}</h2>
            <ul className="mt-1 list-disc pl-5 text-xs">{[...new Set(rs.excluded.flatMap((e) => e.reasons))].slice(0, 3).map((r) => <li key={r}>{r}</li>)}</ul>
            <div className="mt-3 flex flex-wrap gap-2">
              {rs.relax_suggestions.map((s) => (
                <button key={s.constraint} type="button" disabled={planner.loading}
                  onClick={() => planner.patch(RELAX_PATCHES[s.constraint] ?? {})}
                  className="rounded-full bg-white px-3 py-1.5 text-xs font-semibold text-red-800 ring-1 ring-red-300">
                  {s.message}
                </button>
              ))}
            </div>
          </section>
        )}

        {!rs && state?.status === 'error' && (
          <section role="alert" className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-900">
            <p>{planner.messages.filter((x) => x.role === 'assistant').slice(-1)[0]?.text}</p>
            <button type="button" onClick={() => planner.send('show options')} disabled={planner.loading}
              className="mt-3 inline-flex items-center gap-1 rounded-full bg-white px-3 py-1.5 text-xs font-semibold ring-1 ring-red-300">
              <RefreshIcon size={14} /> {m.options.retry}
            </button>
          </section>
        )}

        {!rs && state?.status !== 'error' && (
          <section className="rounded-2xl bg-brand-50 p-4 text-center text-sm text-brand-900">
            <p>{m.options.empty}</p>
            <div className="mt-3"><PrimaryButton onClick={() => go('plan')}>{m.options.goPlan}</PrimaryButton></div>
          </section>
        )}

        {rs?.notes.map((n) => <p key={n} className="rounded-xl bg-ink-100 p-3 text-xs text-ink-700">{n}</p>)}
        {rs && rs.excluded.length > 0 && (
          <details className="rounded-2xl bg-white p-3 text-xs shadow-card ring-1 ring-ink-100">
            <summary className="cursor-pointer font-semibold text-ink-700">{m.options.excluded} ({rs.excluded.length})</summary>
            <ul className="mt-2 space-y-1">
              {rs.excluded.map((e) => <li key={e.option_id}>{e.summary} — <span className="text-red-700">{e.reasons.join(' ')}</span></li>)}
            </ul>
          </details>
        )}
        {rs && <ul className="space-y-0.5 text-[11px] text-ink-500">{rs.limitations.map((l) => <li key={l}>• {l}</li>)}</ul>}
      </div>
    </Screen>
  )
}
