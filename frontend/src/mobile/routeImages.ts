// Photos for the popular-route cards (supplied by the team, resized to ≤800px, JPG + WebP).
// Keyed by what the photo shows, not by route, so config.ts can map any route to any photo.
import chennaiCentralJpg from '../assets/routes/chennai-central.jpg'
import chennaiCentralWebp from '../assets/routes/chennai-central.webp'
import coimbatoreJpg from '../assets/routes/coimbatore.jpg'
import coimbatoreWebp from '../assets/routes/coimbatore.webp'
import maduraiJpg from '../assets/routes/madurai.jpg'
import maduraiWebp from '../assets/routes/madurai.webp'
import tiruchirappalliJpg from '../assets/routes/tiruchirappalli.jpg'
import tiruchirappalliWebp from '../assets/routes/tiruchirappalli.webp'

// Decorative: the card title already names the route, so the photos carry no (English-only) alt text.
export interface RouteImage { jpg: string; webp: string; width: number; height: number }

export const ROUTE_IMAGES = {
  'chennai-central': { jpg: chennaiCentralJpg, webp: chennaiCentralWebp, width: 800, height: 450 },
  coimbatore: { jpg: coimbatoreJpg, webp: coimbatoreWebp, width: 312, height: 195 },
  madurai: { jpg: maduraiJpg, webp: maduraiWebp, width: 543, height: 351 },
  tiruchirappalli: { jpg: tiruchirappalliJpg, webp: tiruchirappalliWebp, width: 542, height: 341 },
} as const satisfies Record<string, RouteImage>

export type RouteImageId = keyof typeof ROUTE_IMAGES
