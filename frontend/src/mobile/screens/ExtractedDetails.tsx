// Shows what the backend extracted (authoritative state) with per-field edit via the existing FieldEditor.
import { useState, type ReactNode } from 'react'
import type { JourneyDetails, JourneyPatch, SessionState } from '../../api/types'
import { FieldEditor, type EditableField } from '../../components/FieldEditor'
import type { Strings } from '../../i18n/strings'
import { formatDate, formatRupees } from '../../utils/format'
import { useApp } from '../PlannerContext'

interface Props {
  state: SessionState
  t: Strings
  disabled: boolean
  onPatch: (patch: JourneyPatch) => void
}

function strictness(strict: boolean, m: ReturnType<typeof useApp>['m']) {
  return strict ? m.fields.strict : m.fields.preferred
}

export function fieldRows(j: JourneyDetails, m: ReturnType<typeof useApp>['m'], t: Strings): [EditableField, string, ReactNode][] {
  const budget = [
    j.budget_limit !== null ? `${formatRupees(j.budget_limit)} (${strictness(j.budget_strict, m)})` : null,
    j.budget_priority ? t.priorities[j.budget_priority] : null,
  ].filter(Boolean).join(' · ')
  return [
    ['origin', m.fields.origin, j.origin?.label],
    ['destination', m.fields.destination, j.destination?.label],
    ['journey_date', m.fields.journey_date, j.journey_date && `${formatDate(j.journey_date)} · ${t.dateMeans[j.date_anchor]}`],
    ['passenger_count', m.fields.passenger_count, j.passenger_count],
    ['budget', m.fields.budget, budget || null],
    ['arrival_deadline', m.fields.arrival_deadline, j.arrival_deadline && `${j.arrival_deadline} (${strictness(j.deadline_strict, m)})`],
    ['class_preference', m.fields.class_preference, j.class_preference && `${j.class_preference} (${strictness(j.class_strict, m)})`],
    ['transfer_preference', m.fields.transfer_preference,
      j.transfer_preference && `${t.transfers[j.transfer_preference]} (${strictness(j.transfer_strict, m)})`],
    ['passenger_needs', m.fields.passenger_needs, j.passenger_needs.length ? j.passenger_needs.map((n) => t.needs[n]).join(', ') : null],
  ]
}

export function ExtractedDetails({ state, t, disabled, onPatch }: Props) {
  const { planner, m } = useApp()
  const [editing, setEditing] = useState<EditableField | null>(null)
  const j = state.journey
  return (
    <section aria-labelledby="extracted-title" className="mx-4 mt-4 rounded-2xl bg-white p-4 shadow-card ring-1 ring-ink-100">
      <h2 id="extracted-title" className="text-base font-bold text-brand-900">{m.plan.extracted}</h2>
      <p className="text-xs text-ink-500">{m.plan.editHint}</p>
      {state.validation_errors.length > 0 && (
        <ul role="alert" className="mt-2 space-y-1">
          {state.validation_errors.map((e) => (
            <li key={`${e.field}-${e.code}`} className="rounded-lg bg-red-50 px-2 py-1 text-xs text-red-800">{e.message}</li>
          ))}
        </ul>
      )}
      <dl className="mt-2 divide-y divide-ink-100">
        {fieldRows(j, m, t).map(([field, label, value]) => {
          const missing = value === null || value === undefined || value === ''
          const required = state.missing_fields.includes(field)
          return (
            <div key={field} className="py-2">
              <div className="flex items-center gap-2">
                <dt className="w-24 shrink-0 text-xs font-medium text-ink-500">{label}</dt>
                <dd className={`flex-1 text-sm ${missing ? (required ? 'font-semibold text-amber-700' : 'text-ink-300') : 'text-ink-900'}`}>
                  {missing ? (required ? `${m.fields.notSet} *` : m.fields.notSet) : value}
                </dd>
                <button type="button" disabled={disabled} onClick={() => setEditing(editing === field ? null : field)}
                  aria-label={`${m.fields.edit} ${label}`} className="text-xs font-semibold text-brand-600 disabled:opacity-40">
                  {m.fields.edit}
                </button>
              </div>
              {editing === field && (
                <FieldEditor field={field} journey={j} reference={planner.reference} t={t}
                  onSave={onPatch} onClose={() => setEditing(null)} />
              )}
            </div>
          )
        })}
      </dl>
    </section>
  )
}
