import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import { ApiError, type ApiClient } from '../api/client'
import type { GoalEvaluation, GoalPlanResponse } from '../api/types'
import { response } from './fixtures'

const provenance = { mode: 'demo' as const, source: 'RailSaathi sample timetable', as_of: '2026-10-01T00:00:00+05:30', note: 'Illustrative demo journeys.' }

function evaluation(train: string, feasible: boolean, lastMile: number | null): GoalEvaluation {
  return {
    candidate_id: `cand-${train}`,
    candidate: {
      option_id: `${train}@2026-10-10`, legs: [], departure: '2026-10-10T22:30:00+05:30', arrival: '2026-10-11T06:45:00+05:30',
      duration_minutes: 495, transfers: 0, classes: ['SL'], fares: { SL: 295 }, provenance, train_number: train,
      train_name: `Demo ${train}`, origin_code: 'CBE', destination_code: 'MAS',
    },
    journey_date: '2026-10-10', meeting_datetime: '2026-10-11T10:00:00+05:30', last_mile_duration_minutes: lastMile,
    last_mile_distance_km: lastMile === null ? null : 11, last_mile_mode: lastMile === null ? null : 'cab',
    latest_acceptable_station_arrival: '2026-10-11T08:37:00+05:30', actual_arrival_buffer_minutes: feasible ? 137 : -20,
    is_feasible: feasible, hard_constraint_violations: feasible ? [] : ['Reaches Chennai Central too late.'],
    soft_preference_matches: [], soft_preference_penalties: [], rank: 1,
    match_category: feasible ? 'best_match' : 'infeasible', explanation: '', recommended_class: 'SL', recommended_fare: 295,
    booking_handoff: feasible ? {
      official_provider: 'IRCTC Official Railway Reservation', booking_url: 'https://www.irctc.co.in/nget/train-search?fromStation=CBE',
      journey_date: '2026-10-10', recommended_class: 'SL', estimated_fare_inr: 295, disclaimer: '',
    } : null,
  }
}

const base: GoalPlanResponse = {
  status: 'answered', summary: 'Found 1 train option that reaches Tidel Park before 10:00.', plan_id: 'plan_abcdefghijkl', provenance,
  trip_requirements: null, best_match: evaluation('D103', true, 38), feasible_alternatives: [],
  infeasible_options: [evaluation('D105', false, null)], clarification_question: null, missing_fields: [],
  place_candidates: [], tradeoff_explanation: null, sources: [], trace_id: 't',
}

function client(planGoal: ApiClient['planGoal']): ApiClient {
  return {
    baseUrl: 'http://test',
    health: vi.fn().mockResolvedValue({ status: 'ok', api_version: '1', data_mode: 'demo', data_provider: { requested: 'demo', active: 'demo', reason: null }, ai: {} }),
    reference: vi.fn().mockResolvedValue({ places: [], classes: [], passenger_needs: [], budget_priorities: [], transfer_preferences: [], disruption_events: [], data_notice: '' }),
    createSession: vi.fn().mockResolvedValue(response({}, 'Hello')),
    planGoal,
  } as unknown as ApiClient
}

async function openGoal(planGoal: ApiClient['planGoal']) {
  window.location.hash = '/home'
  const user = userEvent.setup()
  const c = client(planGoal)
  render(<App client={c} />)
  await waitFor(() => expect(c.createSession).toHaveBeenCalled())
  await user.click(await screen.findByRole('button', { name: 'Reach a Meeting' }))
  await screen.findByText('Reach a meeting on time')
  return { user, c }
}

async function fillAndSubmit(user: ReturnType<typeof userEvent.setup>, venue = 'Tidel Park', date = '2026-10-11') {
  await user.type(screen.getByLabelText('Starting from (city or station)'), 'Coimbatore')
  await user.type(screen.getByLabelText('Meeting venue'), venue)
  await user.type(screen.getByLabelText('Meeting date'), date)
  await user.type(screen.getByLabelText('Meeting time'), '10:00')
  await user.selectOptions(screen.getByLabelText('Preferred class (optional)'), 'SL')
  await user.click(screen.getByRole('button', { name: 'Find trains' }))
}

describe('Goal planner screen', () => {
  it('plans from the form and shows feasibility, buffer, last mile, booking link and provenance', async () => {
    const planGoal = vi.fn().mockResolvedValue(base)
    const { user } = await openGoal(planGoal)
    await fillAndSubmit(user)
    expect(planGoal).toHaveBeenCalledWith({
      origin: 'Coimbatore', destination_venue: 'Tidel Park', meeting_date: '2026-10-11', meeting_time: '10:00',
      required_arrival_buffer_minutes: 45, preferred_class: 'SL',
    })
    const best = await screen.findByRole('article', { name: /D103/ })
    expect(best).toHaveTextContent('Reaches in time')
    expect(best).toHaveTextContent('137 min')
    expect(best).toHaveTextContent('~38 min (estimate)')
    expect(within(best).getByRole('link', { name: /Open on IRCTC/ })).toHaveAttribute('href', expect.stringContaining('https://www.irctc.co.in/'))
    const late = screen.getByRole('article', { name: /D105/ })
    expect(late).toHaveTextContent('Misses the deadline')
    expect(late).toHaveTextContent('not known (not included in the buffer)')
    expect(within(late).queryByRole('link')).toBeNull()
    expect(screen.queryByTestId('provenance-badge')).not.toBeInTheDocument()  // demo data is not labelled
  })

  it('shows the clarification question for an unknown venue', async () => {
    const planGoal = vi.fn().mockResolvedValue({
      ...base, status: 'clarification_required', plan_id: null, best_match: null, infeasible_options: [],
      missing_fields: ['destination_station'],
      clarification_question: 'Acme Park is not in my venue list. Which railway station should I plan your arrival at?',
    })
    const { user } = await openGoal(planGoal)
    await fillAndSubmit(user, 'Acme Park')
    const ask = await screen.findByTestId('goal-clarification')
    expect(ask).toHaveTextContent('Which railway station should I plan your arrival at?')
    expect(screen.queryByRole('article')).toBeNull()
  })

  it('renders a provider outage as the unavailable empty state, never as trains', async () => {
    const planGoal = vi.fn().mockResolvedValue({
      ...base, status: 'provider_unavailable', best_match: null, infeasible_options: [],
      provenance: { ...provenance, mode: 'unavailable', note: 'The live train data source is rate limited right now.' },
    })
    const { user } = await openGoal(planGoal)
    await fillAndSubmit(user)
    const empty = await screen.findByRole('status')
    expect(empty).toHaveTextContent('Data unavailable')
    expect(empty).toHaveTextContent('rate limited')
    expect(screen.queryByRole('article')).toBeNull()
  })

  it('shows the error envelope message for a past meeting (422)', async () => {
    const planGoal = vi.fn().mockRejectedValue(
      new ApiError(422, 'meeting_in_past', 'The meeting time has already passed. Choose a future date and time.'))
    const { user } = await openGoal(planGoal)
    await fillAndSubmit(user, 'Tidel Park', '2026-10-01')
    expect(await screen.findByRole('alert')).toHaveTextContent('The meeting time has already passed.')
  })
})
