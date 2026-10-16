// Goal-based planner: "reach my meeting on time". Uses /api/journey/plan with the planner session token.
import { useState, type FormEvent } from 'react'
import { ApiError } from '../../api/client'
import { errorText } from '../../api/errorText'
import type { GoalEvaluation, GoalPlanRequest, GoalPlanResponse, TravelClass } from '../../api/types'
import { ProvenanceBadge } from '../../components/ProvenanceBadge'
import { formatDay, formatTime } from '../../utils/format'
import { AlertIcon, ArrowRight, CheckIcon, TrainIcon } from '../icons'
import { useApp } from '../PlannerContext'
import { AppHeader, PrimaryButton, Screen } from '../ui'

const CLASSES: TravelClass[] = ['SL', '3A', '2A', 'CC', 'EC', '2S']

interface Form {
  origin: string
  venue: string
  station: string
  date: string
  time: string
  buffer: string
  travelClass: TravelClass | ''
}

const EMPTY: Form = { origin: '', venue: '', station: '', date: '', time: '', buffer: '45', travelClass: '' }

function toRequest(f: Form): GoalPlanRequest {
  const req: GoalPlanRequest = {}
  if (f.origin.trim()) req.origin = f.origin.trim()
  if (f.venue.trim()) req.destination_venue = f.venue.trim()
  if (f.station.trim()) req.destination_station = f.station.trim()
  if (f.date) req.meeting_date = f.date
  if (f.time) req.meeting_time = f.time
  if (f.buffer.trim() !== '' && Number.isFinite(Number(f.buffer))) req.required_arrival_buffer_minutes = Number(f.buffer)
  if (f.travelClass) req.preferred_class = f.travelClass
  return req
}

function Option({ ev, best }: { ev: GoalEvaluation; best: boolean }) {
  const { m } = useApp()
  const c = ev.candidate
  const lm = ev.last_mile_duration_minutes
  return (
    <article aria-label={`${c.train_number} ${c.train_name}`}
      className={`rounded-2xl bg-white p-4 shadow-card ring-1 ${best ? 'ring-2 ring-brand-500' : 'ring-ink-100'}`}>
      <div className="flex flex-wrap items-center gap-1.5">
        {best && <span className="rounded-md bg-match-700 px-2 py-1 text-xs font-semibold text-white">{m.goal.best}</span>}
        <span className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-semibold ${ev.is_feasible ? 'bg-match-50 text-match-700' : 'bg-red-50 text-red-700'}`}>
          {ev.is_feasible ? <CheckIcon size={13} /> : <AlertIcon size={13} />} {ev.is_feasible ? m.goal.onTime : m.goal.missesDeadline}
        </span>
        <span className="ml-auto"><ProvenanceBadge provenance={c.provenance} labels={{ live: m.live }} unavailableTitle={m.dataUnavailable} /></span>
      </div>
      <p className="mt-2 flex items-center gap-2 text-base font-bold text-brand-900"><TrainIcon size={18} className="text-brand-600" /> {c.train_number}</p>
      <p className="text-sm text-ink-700">{c.train_name}</p>
      <p className="mt-1 flex items-center gap-2 text-sm font-semibold text-ink-900">
        {c.origin_code} {formatTime(c.departure)} ({formatDay(c.departure)}) <ArrowRight size={14} className="text-ink-500" /> {c.destination_code} {formatTime(c.arrival)} ({formatDay(c.arrival)})
      </p>
      <dl className="mt-2 grid grid-cols-2 gap-x-2 gap-y-1 text-xs">
        <dt className="text-ink-500">{m.goal.bufferLabel}</dt>
        <dd className="font-semibold text-ink-900">{ev.actual_arrival_buffer_minutes} {m.goal.minutes}</dd>
        <dt className="text-ink-500">{m.goal.lastMile}</dt>
        <dd className="font-semibold text-ink-900">{lm !== null ? `~${lm} ${m.goal.minutes} (${m.goal.lastMileEstimate})` : m.goal.lastMileUnknown}</dd>
      </dl>
      {ev.hard_constraint_violations.length > 0 && (
        <ul className="mt-2 list-disc pl-5 text-xs text-red-700">{ev.hard_constraint_violations.map((v) => <li key={v}>{v}</li>)}</ul>
      )}
      {ev.booking_handoff && (
        <a href={ev.booking_handoff.booking_url} target="_blank" rel="noopener noreferrer"
          className="mt-3 inline-flex items-center gap-1 rounded-full bg-brand-50 px-3 py-1.5 text-xs font-semibold text-brand-700">
          {m.goal.book} <ArrowRight size={12} />
        </a>
      )}
    </article>
  )
}

export default function GoalPlanner() {
  const { planner, m } = useApp()
  const [form, setForm] = useState<Form>(EMPTY)
  const [plan, setPlan] = useState<GoalPlanResponse | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const set = (key: keyof Form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [key]: e.target.value }))

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    const body = toRequest(form)
    try {
      // The goal planner binds plans to the planner session token; make sure a session exists first.
      if (!planner.response) await planner.restart()
      try {
        setPlan(await planner.client.planGoal(body))
      } catch (err) {
        if (!(err instanceof ApiError && err.code === 'invalid_session_token')) throw err
        await planner.restart()
        setPlan(await planner.client.planGoal(body))
      }
    } catch (err) {
      setPlan(null)
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  const evaluations = plan ? [...(plan.best_match ? [plan.best_match] : []), ...plan.feasible_alternatives, ...plan.infeasible_options] : []
  const input = 'mt-1 w-full rounded-xl border border-ink-300 px-3 py-2 text-sm'

  return (
    <Screen header={<AppHeader />}>
      <div className="space-y-4 p-4">
        <h1 className="text-2xl font-extrabold text-brand-900">{m.goal.title}</h1>
        <p className="text-sm text-ink-700">{m.goal.intro}</p>

        <form onSubmit={submit} className="space-y-3 rounded-2xl bg-white p-4 shadow-card ring-1 ring-ink-100">
          <label className="block text-xs font-semibold text-ink-700">{m.goal.origin}
            <input className={input} value={form.origin} onChange={set('origin')} maxLength={120} />
          </label>
          <label className="block text-xs font-semibold text-ink-700">{m.goal.venue}
            <input className={input} value={form.venue} onChange={set('venue')} maxLength={120} />
          </label>
          <label className="block text-xs font-semibold text-ink-700">{m.goal.station}
            <input className={input} value={form.station} onChange={set('station')} maxLength={120} />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-xs font-semibold text-ink-700">{m.goal.date}
              <input type="date" className={input} value={form.date} onChange={set('date')} />
            </label>
            <label className="block text-xs font-semibold text-ink-700">{m.goal.time}
              <input type="time" className={input} value={form.time} onChange={set('time')} />
            </label>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-xs font-semibold text-ink-700">{m.goal.buffer}
              <input type="number" min={0} max={720} className={input} value={form.buffer} onChange={set('buffer')} />
            </label>
            <label className="block text-xs font-semibold text-ink-700">{m.goal.travelClass}
              <select className={input} value={form.travelClass} onChange={set('travelClass')}>
                <option value="">{m.goal.anyClass}</option>
                {CLASSES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>
          </div>
          <PrimaryButton type="submit" disabled={busy}>{busy ? m.goal.planning : m.goal.submit}</PrimaryButton>
        </form>

        {error !== null && (
          <div role="alert" className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            <AlertIcon size={18} className="mt-0.5 shrink-0" /> <span>{errorText(error, m, planner.language)}</span>
          </div>
        )}

        {plan && (
          <section aria-label={m.goal.title} className="space-y-3">
            <ProvenanceBadge provenance={plan.provenance} variant="full" labels={{ live: m.live }} unavailableTitle={m.dataUnavailable} />
            {plan.status === 'clarification_required' ? (
              <div data-testid="goal-clarification" className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
                <p className="font-bold">{m.goal.needMore}</p>
                <p className="mt-1">{plan.clarification_question}</p>
                {plan.place_candidates.length > 0 && (
                  <ul className="mt-1 list-disc pl-5 text-xs">{plan.place_candidates.map((p) => <li key={p}>{p}</li>)}</ul>
                )}
              </div>
            ) : plan.status !== 'provider_unavailable' && (
              <>
                <p className="text-sm font-semibold text-ink-900">{plan.summary}</p>
                {plan.trip_requirements?.assumptions.map((a) => <p key={a} className="text-xs text-ink-500">{a}</p>)}
                {!plan.best_match && <p className="rounded-xl bg-red-50 p-3 text-sm text-red-900">{m.goal.noTrains}</p>}
                {evaluations.map((ev) => <Option key={ev.candidate_id} ev={ev} best={ev === plan.best_match} />)}
                {plan.tradeoff_explanation && <p className="rounded-xl bg-ink-100 p-3 text-xs text-ink-700">{plan.tradeoff_explanation}</p>}
              </>
            )}
          </section>
        )}
      </div>
    </Screen>
  )
}
