import type { SessionState } from '../api/types'
import type { Strings } from '../i18n/strings'
import { formatDay, formatTime } from '../utils/format'
import { JourneyCard } from './JourneyCard'

interface Props {
  t: Strings
  state: SessionState
  disabled: boolean
  onSelect: (optionId: string) => void
  onRelax: (constraint: string) => void
}

export function RecommendationPanel({ t, state, disabled, onSelect, onRelax }: Props) {
  const rs = state.recommendations
  if (!rs) {
    return (
      <section aria-labelledby="recs-title" className="rounded-lg border border-dashed border-slate-300 bg-white p-4">
        <h2 id="recs-title" className="font-semibold text-slate-800">{t.recsTitle}</h2>
        <p className="mt-1 text-sm text-slate-500">{t.recsEmpty}</p>
      </section>
    )
  }
  return (
    <section aria-labelledby="recs-title" className="space-y-3">
      <h2 id="recs-title" className="font-semibold text-slate-800">
        {t.recsTitle} <span className="text-sm font-normal text-slate-500">({rs.eligible_count}/{rs.considered_count})</span>
      </h2>
      <p className="text-xs text-slate-600" data-testid="data-source">
        {t.dataSource}: {rs.provenance.source} · {rs.provenance.mode === 'live' ? t.retrievedAt : t.datasetAsOf}{' '}
        {formatDay(rs.provenance.as_of)} {formatTime(rs.provenance.as_of)} IST
      </p>
      {rs.recommendations.length === 0 && (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-900">
          <h3 className="font-semibold">{t.noOptionsTitle}</h3>
          {rs.relax_suggestions.length > 0 && (
            <>
              <p className="mt-2">{t.relaxTitle}</p>
              <div className="mt-1 flex flex-wrap gap-2">
                {rs.relax_suggestions.map((s) => (
                  <button key={s.constraint} type="button" disabled={disabled} onClick={() => onRelax(s.constraint)}
                    className="rounded border border-red-300 bg-white px-2 py-1 hover:bg-red-100">
                    {s.message} ({s.excluded_count})
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      )}
      {rs.notes.map((n) => <p key={n} className="rounded bg-slate-100 px-3 py-2 text-sm text-slate-700">{n}</p>)}
      {rs.recommendations.map((rec) => (
        <JourneyCard key={rec.option.option_id} t={t} rec={rec} passengers={state.journey.passenger_count ?? 1}
          selected={state.selected_option_id === rec.option.option_id} disabled={disabled}
          onSelect={() => onSelect(rec.option.option_id)} />
      ))}
      {rs.excluded.length > 0 && (
        <details className="rounded-lg border border-slate-200 bg-white p-3 text-sm">
          <summary className="cursor-pointer font-medium text-slate-700">{t.excludedTitle} ({rs.excluded.length})</summary>
          <ul className="mt-2 space-y-1">
            {rs.excluded.map((e) => (
              <li key={e.option_id}><span className="text-slate-900">{e.summary}</span> — <span className="text-red-700">{e.reasons.join(' ')}</span></li>
            ))}
          </ul>
        </details>
      )}
      <ul className="text-xs text-slate-500">
        {rs.limitations.map((l) => <li key={l}>• {l}</li>)}
      </ul>
    </section>
  )
}
