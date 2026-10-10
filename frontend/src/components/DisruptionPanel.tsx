import { useState } from 'react'
import type { DisruptionEvent, SessionState } from '../api/types'
import type { Strings } from '../i18n/strings'

interface Props {
  t: Strings
  state: SessionState
  events: DisruptionEvent[]
  disabled: boolean
  live?: boolean
  onReassess: (eventId: string | null) => void
}

export function DisruptionPanel({ t, state, events, disabled, live = false, onReassess }: Props) {
  const [eventId, setEventId] = useState('')
  const info = state.reassessment
  return (
    <section aria-labelledby="disruption-title" className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h2 id="disruption-title" className="font-semibold text-slate-800">{live ? t.disruptionTitleLive : t.disruptionTitle}</h2>
      <p className="mt-1 text-sm text-slate-600">{live ? t.disruptionHelpLive : t.disruptionHelp}</p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <label htmlFor="event-select" className="sr-only">Event</label>
        <select id="event-select" value={eventId} onChange={(e) => setEventId(e.target.value)}
          className="max-w-full rounded border border-slate-300 px-2 py-1 text-sm">
          <option value="">{live ? t.autoEventLive : t.autoEvent}</option>
          {events.map((e) => <option key={e.id} value={e.id}>{e.label}</option>)}
        </select>
        <button type="button" disabled={disabled} onClick={() => onReassess(eventId || null)}
          className="rounded bg-slate-800 px-3 py-1.5 text-sm text-white hover:bg-slate-900 disabled:opacity-50">
          {t.runCheck}
        </button>
      </div>

      {info && (
        <div className="mt-3 space-y-2 text-sm" role="status">
          <p className="rounded bg-red-50 px-2 py-1 font-medium text-red-900">
            {info.simulated && <span className="mr-1 rounded bg-red-200 px-1 text-xs">SIMULATED</span>}
            {info.event_label}
          </p>
          {info.previous_selection && (
            <p className="text-slate-700">
              Previous selection: {info.previous_selection.option.legs.map((l) => l.train_no).join(' → ')} —{' '}
              <strong className={info.original_still_valid ? 'text-emerald-700' : 'text-red-700'}>
                {info.original_still_valid ? t.stillValid : t.noLongerValid}
              </strong>
            </p>
          )}
          <ul className="ml-4 list-disc text-slate-700">{info.changes.map((c) => <li key={c}>{c}</li>)}</ul>
          {state.confirmation && !state.confirmation.superseded && (
            <p className="text-slate-700">
              Earlier confirmation <strong>{state.confirmation.confirmation_id}</strong> remains on record until you confirm a replacement.
            </p>
          )}
        </div>
      )}
    </section>
  )
}
