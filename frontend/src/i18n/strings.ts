// Shared field labels and enum names for the journey-details editor (FieldEditor, ExtractedDetails, JourneyDetails)
// and the planner's session message. Screen copy lives in mobile/strings.ts.
import type { Language } from '../api/types'

const en = {
  edit: 'Edit',
  save: 'Save',
  cancel: 'Cancel',
  notSet: 'Not set',
  strict: 'mandatory',
  errors: {
    sessionGone: 'Your planning session expired. A new session has been started.',
  },
  labels: {
    origin: 'From',
    destination: 'To',
    journey_date: 'Date',
    passenger_count: 'Passengers',
    arrival_deadline: 'Arrive by',
    departure_window: 'Departure window',
    budget: 'Budget',
    budget_priority: 'Priority',
    class_preference: 'Class',
    passenger_needs: 'Passenger needs',
    transfer_preference: 'Transfers',
  },
  priorities: { minimize_cost: 'Cheapest', minimize_time: 'Fastest', balanced: 'Balanced' },
  transfers: { direct_only: 'Direct only', allow: 'Changes allowed' },
  needs: {
    assistance_requested: 'Assistance requested',
    wheelchair: 'Wheelchair',
    reduced_walking: 'Reduced walking',
    travelling_with_children: 'With children',
    travelling_with_elderly: 'With elderly passenger',
    daytime_departure: 'Daytime departure',
    longer_transfer_buffer: 'Longer connection time',
  },
  dateMeans: { arrival: 'arrival date', departure: 'departure date' },
}

export type Strings = typeof en

const ta: Strings = {
  edit: 'திருத்து',
  save: 'சேமி',
  cancel: 'ரத்து',
  notSet: 'அமைக்கப்படவில்லை',
  strict: 'கட்டாயம்',
  errors: {
    sessionGone: 'உங்கள் திட்டமிடல் அமர்வு காலாவதியானது. புதிய அமர்வு தொடங்கப்பட்டது.',
  },
  labels: {
    origin: 'புறப்படும் இடம்',
    destination: 'சேருமிடம்',
    journey_date: 'தேதி',
    passenger_count: 'பயணிகள்',
    arrival_deadline: 'சேர வேண்டிய நேரம்',
    departure_window: 'புறப்படும் நேரம்',
    budget: 'பட்ஜெட்',
    budget_priority: 'முன்னுரிமை',
    class_preference: 'வகுப்பு',
    passenger_needs: 'பயணி தேவைகள்',
    transfer_preference: 'மாற்றங்கள்',
  },
  priorities: { minimize_cost: 'மலிவானது', minimize_time: 'விரைவானது', balanced: 'சமநிலை' },
  transfers: { direct_only: 'நேரடி மட்டும்', allow: 'மாற்றங்கள் அனுமதிக்கப்படும்' },
  needs: {
    assistance_requested: 'உதவி கோரப்பட்டது',
    wheelchair: 'சக்கர நாற்காலி',
    reduced_walking: 'குறைந்த நடை',
    travelling_with_children: 'குழந்தைகளுடன்',
    travelling_with_elderly: 'முதியவருடன்',
    daytime_departure: 'பகல் நேரப் புறப்பாடு',
    longer_transfer_buffer: 'நீண்ட இணைப்பு நேரம்',
  },
  dateMeans: { arrival: 'சேரும் தேதி', departure: 'புறப்படும் தேதி' },
}

export const STRINGS: Record<Language, Strings> = { en, ta }
