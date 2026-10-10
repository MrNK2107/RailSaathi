import { useState, type FormEvent } from 'react'
import type { JourneyDetails, JourneyPatch, PassengerNeed, ReferenceData } from '../api/types'
import type { Strings } from '../i18n/strings'

export type EditableField =
  | 'origin' | 'destination' | 'journey_date' | 'passenger_count' | 'arrival_deadline'
  | 'departure_window' | 'budget' | 'class_preference' | 'passenger_needs' | 'transfer_preference'

interface Props {
  field: EditableField
  journey: JourneyDetails
  reference: ReferenceData | null
  t: Strings
  onSave: (patch: JourneyPatch) => void
  onClose: () => void
}

const input = 'rounded border border-slate-300 px-2 py-1 text-sm'

export function FieldEditor({ field, journey: j, reference, t, onSave, onClose }: Props) {
  const [v, setV] = useState<Record<string, unknown>>(() => initial(field, j))
  const set = (k: string, val: unknown) => setV((prev) => ({ ...prev, [k]: val }))
  const submit = (e: FormEvent) => {
    e.preventDefault()
    onSave(toPatch(field, v))
    onClose()
  }
  const id = `edit-${field}`
  return (
    <form onSubmit={submit} className="mt-2 space-y-2 rounded border border-rail-100 bg-rail-50 p-2" aria-label={`${t.edit} ${field}`}>
      {(field === 'origin' || field === 'destination') && (
        <select id={id} aria-label={t.labels[field]} className={input} value={String(v.place ?? '')} onChange={(e) => set('place', e.target.value)}>
          <option value="">{t.notSet}</option>
          {reference?.places.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
        </select>
      )}
      {field === 'journey_date' && (
        <div className="flex flex-wrap gap-2">
          <input id={id} aria-label={t.labels.journey_date} type="date" className={input} value={String(v.date ?? '')} onChange={(e) => set('date', e.target.value)} />
          <select aria-label="date meaning" className={input} value={String(v.anchor)} onChange={(e) => set('anchor', e.target.value)}>
            <option value="departure">{t.dateMeans.departure}</option>
            <option value="arrival">{t.dateMeans.arrival}</option>
          </select>
        </div>
      )}
      {field === 'passenger_count' && (
        <input id={id} aria-label={t.labels.passenger_count} type="number" min={1} max={6} className={input} value={String(v.count ?? '')} onChange={(e) => set('count', e.target.value)} />
      )}
      {field === 'arrival_deadline' && (
        <div className="flex flex-wrap items-center gap-2">
          <input id={id} aria-label={t.labels.arrival_deadline} type="time" className={input} value={String(v.time ?? '')} onChange={(e) => set('time', e.target.value)} />
          <Check label={t.strict} checked={Boolean(v.strict)} onChange={(c) => set('strict', c)} />
        </div>
      )}
      {field === 'departure_window' && (
        <div className="flex flex-wrap gap-2">
          <input aria-label="from" type="time" className={input} value={String(v.start ?? '')} onChange={(e) => set('start', e.target.value)} />
          <input aria-label="to" type="time" className={input} value={String(v.end ?? '')} onChange={(e) => set('end', e.target.value)} />
        </div>
      )}
      {field === 'budget' && (
        <div className="flex flex-wrap items-center gap-2">
          <input id={id} aria-label={t.labels.budget} type="number" min={1} placeholder="₹" className={`${input} w-28`} value={String(v.limit ?? '')} onChange={(e) => set('limit', e.target.value)} />
          <Check label={t.strict} checked={Boolean(v.strict)} onChange={(c) => set('strict', c)} />
          <select aria-label={t.labels.budget_priority} className={input} value={String(v.priority ?? '')} onChange={(e) => set('priority', e.target.value)}>
            <option value="">{t.notSet}</option>
            {Object.entries(t.priorities).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
        </div>
      )}
      {field === 'class_preference' && (
        <div className="flex flex-wrap items-center gap-2">
          <select id={id} aria-label={t.labels.class_preference} className={input} value={String(v.cls ?? '')} onChange={(e) => set('cls', e.target.value)}>
            <option value="">{t.notSet}</option>
            {(reference?.classes ?? []).map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <Check label={t.strict} checked={Boolean(v.strict)} onChange={(c) => set('strict', c)} />
        </div>
      )}
      {field === 'transfer_preference' && (
        <div className="flex flex-wrap items-center gap-2">
          <select id={id} aria-label={t.labels.transfer_preference} className={input} value={String(v.pref ?? '')} onChange={(e) => set('pref', e.target.value)}>
            <option value="">{t.notSet}</option>
            {Object.entries(t.transfers).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
          <Check label={t.strict} checked={Boolean(v.strict)} onChange={(c) => set('strict', c)} />
        </div>
      )}
      {field === 'passenger_needs' && (
        <fieldset className="grid gap-1 sm:grid-cols-2">
          <legend className="sr-only">{t.labels.passenger_needs}</legend>
          {Object.entries(t.needs).map(([k, label]) => (
            <Check key={k} label={label} checked={(v.needs as string[]).includes(k)}
              onChange={(c) => set('needs', c ? [...(v.needs as string[]), k] : (v.needs as string[]).filter((n) => n !== k))} />
          ))}
          <Check label={`${t.needs.assistance_requested}: ${t.strict}`} checked={Boolean(v.mandatory)} onChange={(c) => set('mandatory', c)} />
        </fieldset>
      )}
      <div className="flex gap-2">
        <button type="submit" className="rounded bg-rail-600 px-3 py-1 text-sm text-white hover:bg-rail-700">{t.save}</button>
        <button type="button" onClick={onClose} className="rounded border border-slate-300 px-3 py-1 text-sm">{t.cancel}</button>
      </div>
    </form>
  )
}

function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (c: boolean) => void }) {
  return (
    <label className="flex items-center gap-1.5 text-sm">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  )
}

function initial(field: EditableField, j: JourneyDetails): Record<string, unknown> {
  switch (field) {
    case 'origin': return { place: j.origin?.id ?? '' }
    case 'destination': return { place: j.destination?.id ?? '' }
    case 'journey_date': return { date: j.journey_date ?? '', anchor: j.date_anchor }
    case 'passenger_count': return { count: j.passenger_count ?? '' }
    case 'arrival_deadline': return { time: j.arrival_deadline ?? '', strict: j.deadline_strict }
    case 'departure_window': return { start: j.departure_window?.start ?? '', end: j.departure_window?.end ?? '' }
    case 'budget': return { limit: j.budget_limit ?? '', strict: j.budget_strict, priority: j.budget_priority ?? '' }
    case 'class_preference': return { cls: j.class_preference ?? '', strict: j.class_strict }
    case 'transfer_preference': return { pref: j.transfer_preference ?? '', strict: j.transfer_strict }
    case 'passenger_needs': return { needs: [...j.passenger_needs], mandatory: j.assistance_mandatory }
  }
}

const orNull = (x: unknown) => (x === '' || x === undefined ? null : x)

export function toPatch(field: EditableField, v: Record<string, unknown>): JourneyPatch {
  switch (field) {
    case 'origin':
    case 'destination': return { [field]: orNull(v.place) as string | null }
    case 'journey_date': return { journey_date: orNull(v.date) as string | null, date_anchor: v.anchor as 'departure' | 'arrival' }
    case 'passenger_count': return { passenger_count: v.count === '' ? null : Number(v.count) }
    case 'arrival_deadline': return { arrival_deadline: orNull(v.time) as string | null, deadline_strict: Boolean(v.strict) }
    case 'departure_window':
      return { departure_window: v.start && v.end ? { start: String(v.start), end: String(v.end) } : null }
    case 'budget':
      return {
        budget_limit: v.limit === '' ? null : Number(v.limit),
        budget_strict: Boolean(v.strict),
        budget_priority: orNull(v.priority) as JourneyPatch['budget_priority'],
      }
    case 'class_preference': return { class_preference: orNull(v.cls) as JourneyPatch['class_preference'], class_strict: Boolean(v.strict) }
    case 'transfer_preference':
      return { transfer_preference: orNull(v.pref) as JourneyPatch['transfer_preference'], transfer_strict: Boolean(v.strict) }
    case 'passenger_needs':
      return { passenger_needs: v.needs as PassengerNeed[], assistance_mandatory: Boolean(v.mandatory) }
  }
}
