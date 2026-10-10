// Configurable, non-planner content for the mobile screens.
// Edit these lists instead of the components. Nothing here is fetched or verified at runtime.

/** Popular routes on the dashboard. Tapping one starts a real planner request. */
export const POPULAR_ROUTES = [
  { from: 'Chennai', to: 'Bengaluru', ta: 'சென்னை → பெங்களூரு' },
  { from: 'Chennai', to: 'Coimbatore', ta: 'சென்னை → கோயம்புத்தூர்' },
  { from: 'Chennai', to: 'Madurai', ta: 'சென்னை → மதுரை' },
  { from: 'Chennai', to: 'Tiruchirappalli', ta: 'சென்னை → திருச்சி' },
  { from: 'Coimbatore', to: 'Chennai', ta: 'கோயம்புத்தூர் → சென்னை' },
  { from: 'Madurai', to: 'Chennai', ta: 'மதுரை → சென்னை' },
  { from: 'Bengaluru', to: 'Chennai', ta: 'பெங்களூரு → சென்னை' },
] as const

/**
 * Public Indian Railways helplines shown on Help & Assistance.
 * 139 = Rail Madad integrated helpline (enquiry, medical, complaints, assistance requests);
 * 182 = Railway Protection Force security helpline. Verify before production use.
 * Calling a number does NOT book or guarantee any assistance.
 */
export const HELPLINES = [
  { id: 'police', number: '182', tone: 'blue' },
  { id: 'medical', number: '139', tone: 'red' },
  { id: 'enquiry', number: '139', tone: 'navy' },
  { id: 'lostFound', number: '139', tone: 'amber' },
  { id: 'divyangjan', number: '139', tone: 'blue' },
] as const
export const EMERGENCY_NUMBER = '139'
export const RAIL_MADAD_URL = 'https://railmadad.indianrailways.gov.in/'

/** Placeholder facility tiles (no station facility data is connected yet). */
export const FACILITY_TILES = ['toilets', 'water', 'food', 'lounge', 'charging', 'atm'] as const
