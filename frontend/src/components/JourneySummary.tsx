import { useState, type ReactNode } from 'react'
import type { JourneyDetails, JourneyPatch, ReferenceData, SessionState } from '../api/types'
import type { Strings } from '../i18n/strings'
import { formatDate, formatRupees } from '../utils/format'
import { FieldEditor, type EditableField } from './FieldEditor'

interface Props {
  t: Strings
  state: SessionState
  reference: ReferenceData | null
  disabled: boolean
  onPatch: (patch: JourneyPatch) => void
}

export function JourneySummary({ t, state, reference, disabled, onPatch }: Props) {
  const [editing, setEditing] = useState<EditableField | null>(null)
  const j = state.journey
  const rows: [EditableField, string, ReactNode][] = [
    ['origin', t.labels.origin, j.origin?.label],
    ['destination', t.labels.destination, j.destination?.label],
    ['journey_date', t.labels.journey_date, j.journey_date && `${formatDate(j.journey_date)} (${t.dateMeans[j.date_anchor]})`],
    ['passenger_count', t.labels.passenger_count, j.passenger_count],
    ['arrival_deadline', t.labels.arrival_deadline, j.arrival_deadline && `${j.arrival_deadline} · ${j.deadline_strict ? t.strict : t.preferred}`],
    ['departure_window', t.labels.departure_window, j.departure_window && `${j.departure_window.start}–${j.departure_window.end}`],
    ['budget', t.labels.budget, budgetText(j, t)],
    ['class_preference', t.labels.class_preference, j.class_preference && `${j.class_preference} · ${j.class_strict ? t.strict : t.preferred}`],
    ['passenger_needs', t.labels.passenger_needs, needsText(j, t)],
    ['transfer_preference', t.labels.transfer_preference, j.transfer_preference && `${t.transfers[j.transfer_preference]} · ${j.transfer_strict ? t.strict : t.preferred}`],
  ]
  const missing = state.missing_fields
  return (
    <section aria-labelledby="summary-title" className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h2 id="summary-title" className="mb-2 font-semibold text-slate-800">{t.summaryTitle}</h2>
      {missing.length > 0 && (
        <p className="mb-2 rounded bg-amber-50 px-2 py-1 text-sm text-amber-900">
          {t.missing}: {missing.map((f) => t.labels[f as keyof Strings['labels']] ?? f).join(', ')}
        </p>
      )}
      {state.validation_errors.length > 0 && (
        <ul className="mb-2 space-y-1" role="alert">
          {state.validation_errors.map((e) => (
            <li key={`${e.field}-${e.code}`} className="rounded bg-red-50 px-2 py-1 text-sm text-red-800">{e.message}</li>
          ))}
        </ul>
      )}
      <dl className="divide-y divide-slate-100">
        {rows.map(([field, label, value]) => (
          <div key={field} className="py-1.5">
            <div className="flex items-start justify-between gap-2">
              <dt className="w-36 shrink-0 text-sm text-slate-500">{label}</dt>
              <dd className="flex-1 text-sm text-slate-900">
                {value ?? <span className="text-slate-400">{t.notSet}</span>}
                {j.field_sources[field] === 'inferred' && <span className="ml-1 text-xs text-amber-700">(inferred)</span>}
              </dd>
              <button type="button" disabled={disabled} onClick={() => setEditing(editing === field ? null : field)}
                aria-label={`${t.edit} ${label}`} className="text-sm text-rail-600 underline disabled:opacity-40">
                {t.edit}
              </button>
            </div>
            {editing === field && (
              <FieldEditor field={field} journey={j} reference={reference} t={t} onSave={onPatch} onClose={() => setEditing(null)} />
            )}
          </div>
        ))}
      </dl>
    </section>
  )
}

function budgetText(j: JourneyDetails, t: Strings): string | null {
  const parts: string[] = []
  if (j.budget_limit !== null) parts.push(`${formatRupees(j.budget_limit)} · ${j.budget_strict ? t.strict : t.preferred}`)
  if (j.budget_priority) parts.push(t.priorities[j.budget_priority])
  return parts.length ? parts.join(' · ') : null
}

function needsText(j: JourneyDetails, t: Strings): string | null {
  if (!j.passenger_needs.length) return null
  const list = j.passenger_needs.map((n) => t.needs[n]).join(', ')
  return j.assistance_mandatory ? `${list} (${t.strict})` : list
}
