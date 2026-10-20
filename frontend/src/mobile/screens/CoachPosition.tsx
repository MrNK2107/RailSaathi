// Where to stand for a coach. Shown only when a coach order is known (the passenger enters it, and the backend's
// parse_rake_composition places the coach); otherwise the position is explicitly "unknown".
import { useState, type FormEvent } from 'react'
import type { ApiClient } from '../../api/client'
import { errorText, type ErrorCopy } from '../../api/errorText'
import type { Language, RakeCoach } from '../../api/types'
import type { MobileStrings } from '../strings'

type State = { kind: 'idle' } | { kind: 'busy' } | { kind: 'found'; coach: RakeCoach; total: number }
  | { kind: 'missing' } | { kind: 'error'; message: string }

export default function CoachPosition({ client, m, errors, lang }: {
  client: ApiClient; m: MobileStrings['navigation']; errors: ErrorCopy; lang: Language
}) {
  const [order, setOrder] = useState('')
  const [target, setTarget] = useState('')
  const [state, setState] = useState<State>({ kind: 'idle' })

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!order.trim() || !target.trim()) return
    setState({ kind: 'busy' })
    try {
      const res = await client.rakePosition(order.trim(), target.trim())
      setState(res.target_coach_info ? { kind: 'found', coach: res.target_coach_info, total: res.total_coaches } : { kind: 'missing' })
    } catch (err) {
      setState({ kind: 'error', message: errorText(err, { errors }, lang) })
    }
  }

  const found = state.kind === 'found' ? state : null
  const input = 'mt-1 w-full rounded-xl border border-ink-300 bg-white px-3 py-2 text-xs text-ink-900 focus:border-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-600/30'
  return (
    <section aria-labelledby="coach-title" className="mx-4 mb-3 rounded-2xl bg-white p-4 shadow-card ring-1 ring-ink-100">
      <h2 id="coach-title" className="text-sm font-bold text-brand-900">{m.coachTitle}</h2>
      <p className="mt-1 text-xs text-ink-500">{m.coachIntro}</p>
      <form onSubmit={submit} className="mt-3 space-y-2">
        <label className="block text-xs font-semibold text-ink-700">
          {m.coachOrder}
          <input value={order} onChange={(e) => setOrder(e.target.value)} maxLength={400} className={input} />
        </label>
        <label className="block text-xs font-semibold text-ink-700">
          {m.coachTarget}
          <input value={target} onChange={(e) => setTarget(e.target.value)} maxLength={8} className={input} />
        </label>
        <button type="submit" disabled={state.kind === 'busy' || !order.trim() || !target.trim()}
          className="w-full rounded-xl bg-brand-600 px-4 py-2 text-xs font-bold text-white hover:bg-brand-700 disabled:bg-ink-300">
          {m.coachFind}
        </button>
      </form>
      <div className="mt-3" aria-live="polite">
        {found ? (
          <p data-testid="coach-position" className="rounded-xl bg-brand-50 p-3 text-xs text-brand-900">
            {m.coachFound
              .replace('{coach}', found.coach.coach_code).replace('{index}', String(found.coach.index))
              .replace('{total}', String(found.total)).replace('{metres}', String(found.coach.distance_from_engine_meters))
              .replace('{section}', found.coach.platform_section)}
          </p>
        ) : (
          <div data-testid="coach-unknown" className="rounded-xl bg-ink-100/60 p-3 text-xs text-ink-700">
            <p className="font-bold">{m.coachUnknown}</p>
            <p>
              {state.kind === 'missing' ? m.coachNotFound
                : state.kind === 'error' ? `${m.coachFailed} ${state.message}`
                  : m.coachUnknownWhy}
            </p>
          </div>
        )}
      </div>
    </section>
  )
}
