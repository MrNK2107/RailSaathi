import type { JourneyPatch } from './types'

// Maps a backend relax suggestion (RelaxSuggestion.constraint) to the journey fields that loosen it.
export const RELAX_PATCHES: Record<string, JourneyPatch> = {
  arrival_deadline: { arrival_deadline: null },
  budget_limit: { budget_limit: null, budget_strict: false },
  travel_class: { class_strict: false },
  direct_only: { transfer_strict: false },
  mandatory_assistance: { assistance_mandatory: false },
}
