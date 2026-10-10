// "Understanding your request…" checklist. Each step reflects real backend state, not a timer.
import type { SessionState } from '../../api/types'
import { CheckCircle } from '../icons'
import { useApp } from '../PlannerContext'

export function planningSteps(state: SessionState) {
  const j = state.journey
  const searched = ['presenting_recommendations', 'awaiting_confirmation', 'confirmed', 'no_feasible_options'].includes(state.status)
  return [
    { key: 'places', done: Boolean(j.origin && j.destination) },
    { key: 'datePax', done: Boolean(j.journey_date && j.passenger_count) },
    { key: 'prefs', done: searched },
  ] as const
}

export function ProgressSteps({ state }: { state: SessionState }) {
  const { m } = useApp()
  const labels = { places: m.plan.stepPlaces, datePax: m.plan.stepDatePax, prefs: m.plan.stepPrefs }
  const steps = planningSteps(state)
  const allDone = steps.every((s) => s.done)
  return (
    <section aria-labelledby="progress-title" className="mx-4 mt-4 rounded-2xl bg-brand-50 p-4 ring-1 ring-brand-100">
      <h2 id="progress-title" className="text-sm font-bold text-brand-900">{allDone ? m.plan.stepDone : m.plan.understanding}</h2>
      <ul className="mt-2 space-y-2">
        {steps.map((s) => (
          <li key={s.key} className="flex items-center gap-2 text-sm" data-done={s.done}>
            {s.done
              ? <CheckCircle size={20} className="text-match-600" />
              : <span aria-hidden className="h-5 w-5 rounded-full border-2 border-brand-200" />}
            <span className={s.done ? 'text-ink-900' : 'text-ink-500'}>{labels[s.key]}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
