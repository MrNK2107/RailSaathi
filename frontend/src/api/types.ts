// Types mirroring the backend Pydantic schemas (see docs/API.md).

export type Language = 'en' | 'ta'
export type WorkflowStatus =
  | 'collecting_details'
  | 'needs_clarification'
  | 'validating_request'
  | 'searching_options'
  | 'presenting_recommendations'
  | 'awaiting_confirmation'
  | 'confirmed'
  | 'no_feasible_options'
  | 'cancelled'
  | 'error'
/** Mirrors backend `DataMode` (domain/enums.py). `cached` is part of the shared provenance contract. */
export type DataMode = 'live' | 'cached' | 'stale' | 'unavailable' | 'demo' | 'fallback' | 'unknown'
export type TravelClass = 'SL' | '3A' | '2A' | 'CC' | 'EC' | '2S'
export type PassengerNeed =
  | 'assistance_requested'
  | 'wheelchair'
  | 'reduced_walking'
  | 'travelling_with_children'
  | 'travelling_with_elderly'
  | 'daytime_departure'
  | 'longer_transfer_buffer'
export type Verification = 'verified_supported' | 'not_supported' | 'unknown'
export type BudgetPriority = 'minimize_cost' | 'minimize_time' | 'balanced'
export type TransferPreference = 'direct_only' | 'allow'
export type Category = 'best_overall' | 'lowest_cost' | 'fastest'
export type CheckStatus = 'met' | 'violated' | 'unverified' | 'not_applicable'

export interface Place {
  id: string
  label: string
  kind: 'city' | 'station'
  station_codes: string[]
}

export interface TimeWindow {
  start: string
  end: string
  label?: string | null
}

export interface JourneyDetails {
  origin: Place | null
  destination: Place | null
  journey_date: string | null
  date_anchor: 'departure' | 'arrival'
  passenger_count: number | null
  arrival_deadline: string | null
  deadline_strict: boolean
  departure_window: TimeWindow | null
  budget_limit: number | null
  budget_strict: boolean
  budget_priority: BudgetPriority | null
  class_preference: TravelClass | null
  class_strict: boolean
  passenger_needs: PassengerNeed[]
  assistance_mandatory: boolean
  transfer_preference: TransferPreference | null
  transfer_strict: boolean
  field_sources: Record<string, 'explicit' | 'inferred' | 'edited'>
}

/** Shared provenance attached to data-bearing responses; mirrors backend `DataProvenance` (domain/options.py). */
export interface Provenance {
  mode: DataMode
  source: string
  /** ISO-8601 timestamp of when the data was obtained */
  as_of: string
  note: string
}

export type DataProvenance = Provenance

/** Error envelope returned by every backend route (api/errors.py). */
export interface ErrorBody {
  code: string
  message: string
  details: Record<string, unknown>
}

export interface ErrorEnvelope {
  error: ErrorBody
  request_id?: string
}

export interface Leg {
  train_no: string
  train_name: string
  from_code: string
  from_name: string
  to_code: string
  to_name: string
  departure: string
  arrival: string
}

export interface JourneyOption {
  option_id: string
  legs: Leg[]
  departure: string
  arrival: string
  duration_minutes: number
  transfers: number
  min_transfer_minutes: number | null
  fares: Partial<Record<TravelClass, number>>
  classes: TravelClass[]
  station_codes: string[]
  provenance: DataProvenance
  simulated_change: string | null
}

export interface ConstraintCheck {
  name: string
  status: CheckStatus
  detail: string
}

export interface NeedStatus {
  need: PassengerNeed
  status: Verification
  detail: string
}

export interface Recommendation {
  option: JourneyOption
  labels: Category[]
  rank: number
  score: number
  score_breakdown: Record<string, number>
  selected_class: TravelClass | null
  fare_per_passenger: number | null
  total_fare: number | null
  fully_compliant: boolean
  hard_constraints: ConstraintCheck[]
  need_statuses: NeedStatus[]
  preference_matches: string[]
  tradeoffs: string[]
  unverified: string[]
  explanation: string
}

export interface ExcludedOption {
  option_id: string
  summary: string
  reasons: string[]
}

export interface RelaxSuggestion {
  constraint: string
  excluded_count: number
  message: string
}

export interface RecommendationSet {
  constraints_hash: string
  computed_at: string
  considered_count: number
  eligible_count: number
  recommendations: Recommendation[]
  excluded: ExcludedOption[]
  relax_suggestions: RelaxSuggestion[]
  notes: string[]
  limitations: string[]
  provenance: DataProvenance
}

export interface ValidationIssue {
  field: string
  code: string
  message: string
  candidates: string[]
}

export interface Reassessment {
  event_id: string
  event_label: string
  simulated: boolean
  summary: string
  affected_option_ids: string[]
  selected_option_affected: boolean
  original_still_valid: boolean | null
  changes: string[]
  previous_selection: Recommendation | null
  requires_confirmation: boolean
}

export interface ConfirmationRecord {
  confirmation_id: string
  confirmed_at: string
  selected_option_id: string
  constraints_hash: string
  handoff: Record<string, unknown>
  superseded: boolean
}

export interface SessionState {
  session_id: string
  status: WorkflowStatus
  language: Language
  journey: JourneyDetails
  missing_fields: string[]
  validation_errors: ValidationIssue[]
  pending_question: string | null
  awaiting_confirmation: boolean
  selected_option_id: string | null
  recommendations: RecommendationSet | null
  reassessment: Reassessment | null
  confirmation: ConfirmationRecord | null
  data_mode: DataMode
  extraction_source: string | null
  version: number
}

export interface PlannerResponse {
  session_id: string
  session_token?: string | null
  assistant_message: string
  status: WorkflowStatus
  state: SessionState
  missing_fields: string[]
  validation_errors: ValidationIssue[]
  recommendations_ready: boolean
  confirmation_required: boolean
  data_mode: DataMode
  data_notice: string
  extraction: { source: string | null; fallback_reason: string | null } | null
  handoff: Record<string, unknown> | null
}

export interface HealthResponse {
  status: string
  api_version: string
  data_mode: DataMode
  data_provider: { requested: string; active: string; reason: string | null }
  ai: Record<string, unknown>
}

export interface DisruptionEvent {
  id: string
  type: 'delay' | 'cancellation'
  train_no: string
  delay_minutes: number
  label: string
  simulated: boolean
}

export interface ReferenceData {
  places: Place[]
  classes: TravelClass[]
  passenger_needs: PassengerNeed[]
  budget_priorities: BudgetPriority[]
  transfer_preferences: TransferPreference[]
  disruption_events: DisruptionEvent[]
  data_notice: string
}

export type JourneyPatch = Partial<{
  origin: string | null
  destination: string | null
  journey_date: string | null
  date_anchor: 'departure' | 'arrival'
  passenger_count: number | null
  arrival_deadline: string | null
  deadline_strict: boolean
  departure_window: TimeWindow | null
  budget_limit: number | null
  budget_strict: boolean
  budget_priority: BudgetPriority | null
  class_preference: TravelClass | null
  class_strict: boolean
  passenger_needs: PassengerNeed[]
  assistance_mandatory: boolean
  transfer_preference: TransferPreference | null
  transfer_strict: boolean
}>

// ---- Goal planner (/api/journey/*), mirrors backend/app/journey/models.py ----

export type GoalPlanStatus = 'answered' | 'clarification_required' | 'no_feasible_journey' | 'provider_unavailable'

export interface GoalPlanRequest {
  prompt?: string
  origin?: string
  destination_venue?: string
  destination_station?: string
  /** YYYY-MM-DD */
  meeting_date?: string
  /** HH:MM, 24-hour */
  meeting_time?: string
  required_arrival_buffer_minutes?: number
  preferred_class?: TravelClass
  preferred_train_name_or_number?: string
  budget_max?: number
}

/** Changes to a stored plan; only the fields sent are applied (null clears class, train and budget). */
export interface GoalRefineRequest {
  plan_id: string
  meeting_date?: string
  meeting_time?: string
  required_arrival_buffer_minutes?: number
  preferred_class?: TravelClass | null
  preferred_train_name_or_number?: string | null
  budget_max?: number | null
}

export interface TripRequirements {
  origin: string
  destination_venue: string | null
  destination_station: string | null
  meeting_date: string
  meeting_time: string
  required_arrival_buffer_minutes: number
  preferred_train_name_or_number: string | null
  preferred_class: TravelClass | null
  budget_max: number | null
  assumptions: string[]
}

export interface TrainLeg {
  train_number: string
  train_name: string
  from_code: string
  from_name: string
  to_code: string
  to_name: string
  departure: string
  arrival: string
}

export interface TrainCandidate {
  option_id: string
  legs: TrainLeg[]
  departure: string
  arrival: string
  duration_minutes: number
  transfers: number
  classes: string[]
  fares: Record<string, number>
  provenance: Provenance
  train_number: string
  train_name: string
  origin_code: string
  destination_code: string
}

export interface BookingHandoff {
  official_provider: string
  booking_url: string
  journey_date: string
  recommended_class: string | null
  estimated_fare_inr: number | null
  disclaimer: string
}

export interface GoalEvaluation {
  candidate_id: string
  candidate: TrainCandidate
  journey_date: string
  meeting_datetime: string
  last_mile_duration_minutes: number | null
  last_mile_distance_km: number | null
  last_mile_mode: string | null
  latest_acceptable_station_arrival: string
  actual_arrival_buffer_minutes: number
  is_feasible: boolean
  hard_constraint_violations: string[]
  soft_preference_matches: string[]
  soft_preference_penalties: string[]
  rank: number
  match_category: 'best_match' | 'feasible_alternative' | 'infeasible'
  explanation: string
  recommended_class: string | null
  recommended_fare: number | null
  booking_handoff: BookingHandoff | null
}

export interface GoalPlanResponse {
  status: GoalPlanStatus
  summary: string
  /** Server-issued, bound to this session; null for clarification responses. */
  plan_id: string | null
  provenance: Provenance
  trip_requirements: TripRequirements | null
  best_match: GoalEvaluation | null
  feasible_alternatives: GoalEvaluation[]
  infeasible_options: GoalEvaluation[]
  clarification_question: string | null
  missing_fields: string[]
  place_candidates: string[]
  tradeoff_explanation: string | null
  sources: Record<string, unknown>[]
  trace_id: string
}

/** POST /api/chat (backend api/ticketing.py). `provenance` is the shared DataProvenance object (controller.py `_provenance`). */
export interface TicketingRequest {
  message: string
  conversation_id?: string
}

export interface TicketingSource {
  source_id: string
  title: string
  url: string
  publisher: string
  last_verified_at: string
  as_of: string
}

export interface TicketingLink {
  title: string
  url: string
}

export interface TicketingResponse {
  conversation_id: string
  session_token: string
  status: 'answered' | 'execution_limit_reached' | 'unavailable' | string
  answer: string
  sources: TicketingSource[]
  provenance: Provenance
  evidence_sufficient: boolean
  trace_id: string
  /** Only when status is "unavailable". */
  message?: string
  links?: TicketingLink[]
}

/** GET /api/live/stations/{code}/departures (backend providers/live_source.py `DepartureBoard`). */
export interface StationRef {
  code: string
  name: string
}

export interface LiveDeparture {
  train_no: string
  train_name: string
  /** ISO-8601, at the board's station */
  scheduled_departure: string
  /** Nearby catalogue stations this train reaches directly (not necessarily its terminus). */
  towards: StationRef[]
  /** null: running status not known */
  delay_minutes: number | null
  cancelled: boolean | null
  status_as_of: string | null
}

export interface DepartureBoard {
  station: StationRef
  window_start: string
  window_end: string
  neighbours_checked: StationRef[]
  /** false when some neighbour queries failed (trains may be missing) */
  complete: boolean
  departures: LiveDeparture[]
  provenance: Provenance
  /** Only when provenance.mode is "unavailable". */
  reason: string | null
}

/** GET /api/predict/delay (backend delay/model.py `DelayPrediction`). */
export type DelayRisk = 'LOW' | 'MODERATE' | 'HIGH'
export type DelayBasis = 'trained_model' | 'history_only' | 'none'

export interface DelayPrediction {
  train_number: string
  station_code: string
  train_class: string
  /** Echoed; no mode uses it as an input. */
  live_input_delay_minutes: number
  historical_mean_delay_minutes: number | null
  historical_scope: 'pair' | 'station' | 'none'
  /** null: no data for this train and station */
  predicted_delay_minutes: number | null
  /** 0..1, P(delay <= on_time_threshold_minutes); trained_model only */
  on_time_probability: number | null
  on_time_threshold_minutes: number
  risk_level: DelayRisk | null
  model_version: string
  /** Measured on held-out trains; null when there is no trained model */
  mae_minutes: number | null
  baseline_mae_minutes: number | null
  basis: DelayBasis
  provenance: Provenance
  insights: string[]
}
