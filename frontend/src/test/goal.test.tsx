import { render, screen } from '@testing-library/react'
import { ApiError, createApiClient } from '../api/client'
import type { GoalPlanResponse } from '../api/types'
import { ProvenanceBadge } from '../components/ProvenanceBadge'

const json = (status: number, body: unknown) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))

const call = (fetchImpl: ReturnType<typeof vi.fn>, n: number) => {
  const [url, init] = fetchImpl.mock.calls[n] as unknown as [string, RequestInit]
  return { url, init, headers: init.headers as Record<string, string>, body: init.body ? JSON.parse(String(init.body)) : undefined }
}

const provenance = { mode: 'demo' as const, source: 'RailSaathi demo dataset (simulated)', as_of: '2026-10-01T00:00:00+05:30', note: 'Illustrative.' }

const plan: GoalPlanResponse = {
  status: 'answered', summary: 'Found 2 train options.', plan_id: 'plan_abcdefghijkl', provenance,
  trip_requirements: {
    origin: 'Coimbatore', destination_venue: 'Tidel Park', destination_station: null, meeting_date: '2026-10-11',
    meeting_time: '10:00', required_arrival_buffer_minutes: 45, preferred_train_name_or_number: null,
    preferred_class: null, budget_max: null, assumptions: [],
  },
  best_match: null, feasible_alternatives: [], infeasible_options: [], clarification_question: null,
  missing_fields: [], place_candidates: [], tradeoff_explanation: null, sources: [], trace_id: 'plan-1',
}

describe('goal planner flow', () => {
  it('plans with the session token, then refines the server-issued plan id', async () => {
    const fetchImpl = vi.fn()
      .mockImplementationOnce(() => json(200, { session_id: 's1', session_token: 's1.sig', state: {} }))
      .mockImplementationOnce(() => json(200, plan))
      .mockImplementationOnce(() => json(200, { ...plan, trip_requirements: { ...plan.trip_requirements!, required_arrival_buffer_minutes: 90 } }))
    const api = createApiClient({ baseUrl: 'http://api', fetchImpl })
    await api.createSession('en')

    const res = await api.planGoal({ origin: 'Coimbatore', destination_venue: 'Tidel Park', meeting_date: '2026-10-11', meeting_time: '10:00' })
    expect(res.plan_id).toBe('plan_abcdefghijkl')
    expect(res.provenance.mode).toBe('demo')
    const first = call(fetchImpl, 1)
    expect(first.url).toBe('http://api/api/journey/plan')
    expect(first.init.method).toBe('POST')
    expect(first.headers['X-Session-Token']).toBe('s1.sig')

    const refined = await api.refineGoal({ plan_id: res.plan_id!, required_arrival_buffer_minutes: 90 })
    expect(refined.trip_requirements?.required_arrival_buffer_minutes).toBe(90)
    const second = call(fetchImpl, 2)
    expect(second.url).toBe('http://api/api/journey/refine')
    expect(second.body).toEqual({ plan_id: 'plan_abcdefghijkl', required_arrival_buffer_minutes: 90 })
    expect(second.headers['X-Session-Token']).toBe('s1.sig')
  })

  it('surfaces a foreign or expired plan id as a typed plan_not_found error and never retries a refine', async () => {
    const fetchImpl = vi.fn(() => json(404, { error: { code: 'plan_not_found', message: 'This plan does not exist or has expired.', details: {} }, request_id: 'r1' }))
    const api = createApiClient({ baseUrl: 'http://api', fetchImpl, retryDelayMs: 0 })
    const err = await api.refineGoal({ plan_id: 'plan_someoneelse', meeting_time: '11:00' }).catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 404, code: 'plan_not_found', requestId: 'r1' })
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })

  it('fetches a stored plan by id', async () => {
    const fetchImpl = vi.fn(() => json(200, plan))
    const api = createApiClient({ baseUrl: 'http://api', fetchImpl })
    await api.goalPlan('plan_abcdefghijkl')
    expect(call(fetchImpl, 0).url).toBe('http://api/api/journey/options/plan_abcdefghijkl')
  })

  it('a provider outage plan renders as an explicit unavailable state', () => {
    const outage: GoalPlanResponse = {
      ...plan, status: 'provider_unavailable', plan_id: 'plan_abcdefghijkl',
      provenance: { ...provenance, mode: 'unavailable', note: 'The live train data source is not configured.' },
    }
    render(<ProvenanceBadge provenance={outage.provenance} />)
    expect(screen.getByRole('status')).toHaveTextContent('The live train data source is not configured.')
  })
})
