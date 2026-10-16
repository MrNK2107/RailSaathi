// Configurable, non-planner content for the mobile screens.
// Edit these lists instead of the components. Nothing here is fetched or verified at runtime.

import type { RouteImageId } from './routeImages'

/**
 * Popular routes on the dashboard. Tapping one starts a real planner request.
 * `codes` is the primary station pair from backend/app/providers/data/station_catalogue.json
 * (Chennai = MAS, Bengaluru = SBC, Coimbatore = CBE, Madurai = MDU, Tiruchirappalli = TPJ); the planner
 * itself still searches every station of the city. `image` picks a team-supplied photo from routeImages.ts
 * (the photo shows the destination); `null` means no photo is available and the card shows a neutral
 * illustration instead. No Bengaluru photo was supplied, so Chennai → Bengaluru has none.
 */
export const POPULAR_ROUTES: readonly {
  from: string; to: string; ta: string; codes: string; station: string; stationTa: string; image: RouteImageId | null
}[] = [
  { from: 'Chennai', to: 'Bengaluru', ta: 'சென்னை → பெங்களூரு', codes: 'MAS → SBC', station: 'KSR Bengaluru', stationTa: 'KSR பெங்களூரு', image: null },
  { from: 'Chennai', to: 'Coimbatore', ta: 'சென்னை → கோயம்புத்தூர்', codes: 'MAS → CBE', station: 'Coimbatore Junction', stationTa: 'கோயம்புத்தூர் சந்திப்பு', image: 'coimbatore' },
  { from: 'Chennai', to: 'Madurai', ta: 'சென்னை → மதுரை', codes: 'MAS → MDU', station: 'Madurai Junction', stationTa: 'மதுரை சந்திப்பு', image: 'madurai' },
  { from: 'Chennai', to: 'Tiruchirappalli', ta: 'சென்னை → திருச்சி', codes: 'MAS → TPJ', station: 'Tiruchchirappalli Junction', stationTa: 'திருச்சிராப்பள்ளி சந்திப்பு', image: 'tiruchirappalli' },
  { from: 'Coimbatore', to: 'Chennai', ta: 'கோயம்புத்தூர் → சென்னை', codes: 'CBE → MAS', station: 'Chennai Central', stationTa: 'சென்னை சென்ட்ரல்', image: 'chennai-central' },
  { from: 'Madurai', to: 'Chennai', ta: 'மதுரை → சென்னை', codes: 'MDU → MAS', station: 'Chennai Central', stationTa: 'சென்னை சென்ட்ரல்', image: 'chennai-central' },
  { from: 'Bengaluru', to: 'Chennai', ta: 'பெங்களூரு → சென்னை', codes: 'SBC → MAS', station: 'Chennai Central', stationTa: 'சென்னை சென்ட்ரல்', image: 'chennai-central' },
] as const

/**
 * Public Indian Railways helplines shown on Help & Assistance.
 * 139 = Rail Madad integrated helpline (enquiry, medical, complaints, assistance requests);
 * 182 (RPF) was merged into 139 and withdrawn on 1 April 2021, so security also goes to 139.
 * Calling a number does NOT book or guarantee any assistance.
 */
export const HELPLINES = [
  { id: 'police', number: '139', tone: 'blue' },
  { id: 'medical', number: '139', tone: 'red' },
  { id: 'enquiry', number: '139', tone: 'navy' },
  { id: 'lostFound', number: '139', tone: 'amber' },
  { id: 'divyangjan', number: '139', tone: 'blue' },
] as const
export const EMERGENCY_NUMBER = '139'
export const RAIL_MADAD_URL = 'https://railmadad.indianrailways.gov.in/'
