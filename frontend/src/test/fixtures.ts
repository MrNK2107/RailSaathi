import type { PlannerResponse, Recommendation, SessionState } from '../api/types'

const provenance = { mode: 'demo' as const, source: 'RailSaathi sample timetable', as_of: '2026-10-01T00:00:00+05:30', note: 'Illustrative.' }

export const rec: Recommendation = {
  option: {
    option_id: 'CBE-MAS-D103@2026-10-10',
    legs: [{
      train_no: 'D103', train_name: 'Nilgiri Night Express', from_code: 'CBE', from_name: 'Coimbatore Junction',
      to_code: 'MAS', to_name: 'Chennai Central', departure: '2026-10-10T22:30:00+05:30', arrival: '2026-10-11T06:45:00+05:30',
    }],
    departure: '2026-10-10T22:30:00+05:30', arrival: '2026-10-11T06:45:00+05:30', duration_minutes: 495, transfers: 0,
    min_transfer_minutes: null, fares: { SL: 295 }, classes: ['SL'], station_codes: ['CBE', 'MAS'], provenance, simulated_change: null,
  },
  labels: ['best_overall', 'lowest_cost'], rank: 1, score: 0.9, score_breakdown: {}, selected_class: 'SL',
  fare_per_passenger: 295, total_fare: 590, fully_compliant: true,
  hard_constraints: [{ name: 'arrival_deadline', status: 'met', detail: 'Arrives 06:45 on 11 Oct, before the 09:00 deadline.' }],
  need_statuses: [], preference_matches: ['Lower fare prioritised as requested.'], tradeoffs: [],
  unverified: ['Assistance has been requested, but availability at Chennai Egmore has not been verified.'],
  explanation: 'Recommended because it has the lowest listed fare among eligible options (₹590 for 2).',
}

export const baseState: SessionState = {
  session_id: '11111111-1111-1111-1111-111111111111', status: 'collecting_details', language: 'en',
  journey: {
    origin: null, destination: null, journey_date: null, date_anchor: 'departure', passenger_count: null,
    arrival_deadline: null, deadline_strict: true, departure_window: null, budget_limit: null, budget_strict: false,
    budget_priority: null, class_preference: null, class_strict: false, passenger_needs: [], assistance_mandatory: false,
    transfer_preference: null, transfer_strict: false, field_sources: {},
  },
  missing_fields: ['origin', 'destination', 'journey_date', 'passenger_count'], validation_errors: [],
  pending_question: null, awaiting_confirmation: false, selected_option_id: null, recommendations: null,
  reassessment: null, confirmation: null, data_mode: 'demo', extraction_source: null, version: 0,
}

export function response(state: Partial<SessionState>, message = ''): PlannerResponse {
  const s = { ...baseState, ...state }
  return {
    session_id: s.session_id, assistant_message: message, status: s.status, state: s,
    missing_fields: s.missing_fields, validation_errors: s.validation_errors,
    recommendations_ready: Boolean(s.recommendations?.recommendations.length),
    confirmation_required: s.status === 'awaiting_confirmation', data_mode: 'demo', data_notice: 'DEMO DATA',
    extraction: null, handoff: s.confirmation?.handoff ?? null,
  }
}

export const withRecs: Partial<SessionState> = {
  status: 'presenting_recommendations',
  missing_fields: [],
  journey: {
    ...baseState.journey,
    origin: { id: 'coimbatore', label: 'Coimbatore', kind: 'city', station_codes: ['CBE'] },
    destination: { id: 'chennai', label: 'Chennai (any station)', kind: 'city', station_codes: ['MAS', 'MS'] },
    journey_date: '2026-10-11', date_anchor: 'arrival', passenger_count: 2, arrival_deadline: '09:00',
  },
  recommendations: {
    constraints_hash: 'abc', computed_at: '2026-10-10T10:00:00+05:30', considered_count: 6, eligible_count: 3,
    recommendations: [rec], excluded: [{ option_id: 'x', summary: 'D105 Cheran Late Passenger', reasons: ['Arrives after the 09:00 deadline.'] }],
    relax_suggestions: [], notes: [], limitations: ['No ticket is booked.'], provenance,
  },
}
