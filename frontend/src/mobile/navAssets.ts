// Artwork for the Station Navigation page, cut from the team's "Railway Station Navigation UI Kit"
// sheet (stationn_navigation/). Each asset was cropped to its own file so the sheet is never shown
// whole. Pixel sizes are the cropped originals; the banner is downsized to phone width (≤880 px).
import bannerJpg from '../assets/navigation/banner-chennai-central.jpg'
import bannerWebp from '../assets/navigation/banner-chennai-central.webp'
import compass from '../assets/navigation/control-compass.png'
import locate from '../assets/navigation/control-locate.png'
import zoomIn from '../assets/navigation/control-zoom-in.png'
import zoomOut from '../assets/navigation/control-zoom-out.png'
import avoidStairs from '../assets/navigation/icon-avoid-stairs.png'
import navigate from '../assets/navigation/icon-navigate.png'
import routeIcon from '../assets/navigation/icon-route.png'
import verified from '../assets/navigation/icon-verified.png'
import walkTime from '../assets/navigation/icon-walk-time.png'
import walk from '../assets/navigation/icon-walk.png'
import wheelchair from '../assets/navigation/icon-wheelchair.png'
import pinDestination from '../assets/navigation/pin-destination.png'
import pinPlace from '../assets/navigation/pin-place.png'
import pinStart from '../assets/navigation/pin-start.png'

export interface Sprite { src: string; width: number; height: number }

/** Photo banner: Chennai Central's red-brick facade and clock tower. */
export const NAV_BANNER = { jpg: bannerJpg, webp: bannerWebp, width: 880, height: 284 } as const

/** Map markers. Pins are drawn with their tip (bottom centre) on the node position. */
export const NAV_PINS = {
  start: { src: pinStart, width: 86, height: 117 },
  destination: { src: pinDestination, width: 85, height: 117 },
  place: { src: pinPlace, width: 77, height: 116 },
  navigate: { src: navigate, width: 115, height: 120 },
} as const satisfies Record<string, Sprite>

/** Accessibility preference icons, in the order the chips appear. */
export const NAV_PREF_ICONS = {
  avoid_stairs: { src: avoidStairs, width: 136, height: 129 },
  wheelchair: { src: wheelchair, width: 136, height: 129 },
  require_verified_accessibility: { src: verified, width: 137, height: 129 },
} as const satisfies Record<string, Sprite>

/** Map control buttons. */
export const NAV_CONTROLS = {
  zoomIn: { src: zoomIn, width: 102, height: 118 },
  zoomOut: { src: zoomOut, width: 101, height: 118 },
  locate: { src: locate, width: 103, height: 118 },
  compass: { src: compass, width: 107, height: 101 },
} as const satisfies Record<string, Sprite>

/** Route summary icons. */
export const NAV_SUMMARY_ICONS = {
  walk: { src: walk, width: 129, height: 128 },
  walkTime: { src: walkTime, width: 150, height: 135 },
  route: { src: routeIcon, width: 144, height: 135 },
} as const satisfies Record<string, Sprite>
