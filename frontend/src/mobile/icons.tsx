// Inline SVG icon set for the mobile app (stroke icons, 24px grid, currentColor).
import type { SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement> & { size?: number }

function make(paths: string[], filled = false) {
  return function Icon({ size = 20, ...rest }: IconProps) {
    return (
      <svg aria-hidden width={size} height={size} viewBox="0 0 24 24" fill={filled ? 'currentColor' : 'none'}
        stroke={filled ? 'none' : 'currentColor'} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" {...rest}>
        {paths.map((d) => <path key={d} d={d} />)}
      </svg>
    )
  }
}

export const TrainIcon = make([
  'M7 3h10a3 3 0 0 1 3 3v8a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3V6a3 3 0 0 1 3-3z', 'M4 10h16', 'M8 14h.01', 'M16 14h.01',
  'M7 21l2-4', 'M17 21l-2-4',
])
export const MicIcon = make(['M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3z', 'M5 11a7 7 0 0 0 14 0', 'M12 18v3'])
export const StopIcon = make(['M7 7h10v10H7z'], true)
export const HomeIcon = make(['M3 11l9-7 9 7', 'M5 10v10h5v-6h4v6h5V10'])
export const TripsIcon = make(['M8 6V4h8v2', 'M4 6h16v14H4z', 'M4 12h16'])
export const BellIcon = make(['M6 16V11a6 6 0 0 1 12 0v5l2 2H4z', 'M10 20a2 2 0 0 0 4 0'])
export const HelpIcon = make(['M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z', 'M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14', 'M12 17h.01'])
export const UserIcon = make(['M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z', 'M4 21a8 8 0 0 1 16 0'])
export const UsersIcon = make(['M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z', 'M2 21a7 7 0 0 1 14 0', 'M16 3.5a4 4 0 0 1 0 7', 'M22 21a7 7 0 0 0-4-6.3'])
export const ArrowLeft = make(['M19 12H5', 'M12 19l-7-7 7-7'])
export const ArrowRight = make(['M5 12h14', 'M12 5l7 7-7 7'])
export const ChevronRight = make(['M9 6l6 6-6 6'])
export const ChevronDown = make(['M6 9l6 6 6-6'])
export const EditIcon = make(['M4 20h4L19 9l-4-4L4 16z', 'M14 6l4 4'])
export const CheckIcon = make(['M5 12l5 5 9-10'])
export const CheckCircle = make(['M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z', 'M8 12l3 3 5-6'])
export const InfoIcon = make(['M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z', 'M12 11v6', 'M12 7h.01'])
export const AlertIcon = make(['M12 3l10 18H2z', 'M12 10v4', 'M12 17h.01'])
export const PhoneIcon = make(['M5 4h4l2 5-3 2a11 11 0 0 0 5 5l2-3 5 2v4a2 2 0 0 1-2 2A17 17 0 0 1 3 6a2 2 0 0 1 2-2z'])
export const ShieldIcon = make(['M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z', 'M9 12l2 2 4-4'])
export const MedicalIcon = make(['M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z', 'M12 8v8', 'M8 12h8'])
export const BagIcon = make(['M6 8h12l-1 12H7z', 'M9 8V6a3 3 0 0 1 6 0v2'])
export const AccessibleIcon = make(['M12 4h.01', 'M10 8h4l-1 5h4l2 5', 'M10 8l-1 5', 'M8 13a5 5 0 1 0 6 6'])
export const DocIcon = make(['M6 3h8l4 4v14H6z', 'M14 3v4h4', 'M9 12h6', 'M9 16h6'])
export const MapIcon = make(['M9 4L3 6v14l6-2 6 2 6-2V4l-6 2z', 'M9 4v14', 'M15 6v14'])
export const StepsIcon = make(['M4 6h16', 'M4 12h10', 'M4 18h6'])
export const PinIcon = make(['M12 22s7-6.5 7-12a7 7 0 0 0-14 0c0 5.5 7 12 7 12z', 'M12 12a2 2 0 1 0 0-4 2 2 0 0 0 0 4z'])
export const SearchIcon = make(['M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14z', 'M21 21l-4.3-4.3'])
export const ClockIcon = make(['M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z', 'M12 7v5l3 2'])
export const RupeeIcon = make(['M7 4h10', 'M7 8h10', 'M7 4c5 0 6 8 0 8h-1l8 8'])
export const SeatIcon = make(['M6 4v9a2 2 0 0 0 2 2h8', 'M6 19h12', 'M18 15v4', 'M8 19v-4'])
export const BoltIcon = make(['M13 2L4 14h7l-1 8 9-12h-7z'])
export const TrophyIcon = make(['M8 21h8', 'M12 17v4', 'M7 4h10v5a5 5 0 0 1-10 0z', 'M17 6h3a3 3 0 0 1-3 4', 'M7 6H4a3 3 0 0 0 3 4'])
export const TagIcon = make(['M3 12V3h9l9 9-9 9z', 'M7.5 7.5h.01'])
export const SaveIcon = make(['M6 3h12v18l-6-4-6 4z'])
export const LiveIcon = make(['M12 12h.01', 'M8.5 8.5a5 5 0 0 0 0 7', 'M15.5 8.5a5 5 0 0 1 0 7', 'M5.6 5.6a9 9 0 0 0 0 12.8', 'M18.4 5.6a9 9 0 0 1 0 12.8'])
export const ToiletIcon = make(['M7 4h.01', 'M17 4h.01', 'M5 8h4v6H8v6H6v-6H5z', 'M15 8h4l1 6h-2v6h-2v-6h-2z'])
export const WaterIcon = make(['M12 3s6 7 6 11a6 6 0 0 1-12 0c0-4 6-11 6-11z'])
export const FoodIcon = make(['M5 3v8a2 2 0 0 0 4 0V3', 'M7 3v18', 'M17 3c-2 2-2 6 0 8v10'])
export const LoungeIcon = make(['M4 12v-2a2 2 0 0 1 4 0v2h8v-2a2 2 0 0 1 4 0v2', 'M3 12h18v5H3z', 'M5 17v3', 'M19 17v3'])
export const PlugIcon = make(['M9 2v6', 'M15 2v6', 'M6 8h12v3a6 6 0 0 1-12 0z', 'M12 17v5'])
export const AtmIcon = make(['M3 6h18v12H3z', 'M7 10h10', 'M7 14h4'])
export const GlobeIcon = make(['M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z', 'M2 12h20', 'M12 2a15 15 0 0 1 0 20', 'M12 2a15 15 0 0 0 0 20'])
export const RefreshIcon = make(['M20 11a8 8 0 1 0-2.3 5.7', 'M20 4v7h-7'])
export const SpeakerIcon = make(['M4 9h4l5-4v14l-5-4H4z', 'M16 9a4 4 0 0 1 0 6', 'M19 6a8 8 0 0 1 0 12'])
export const CompassIcon = make([
  'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z',
  'M16.2 7.8l-2.1 6.4-6.3 2.1 2.1-6.4 6.3-2.1z',
])
export const WalkIcon = make([
  'M13 4a2 2 0 1 0 0-4 2 2 0 0 0 0 4z',
  'M7 21v-5l4-3 1-4 3 2v6',
])
export const TrendingUp = make(['M23 6l-9.5 9.5-5-5L1 18', 'M17 6h6v6'])
export const TrendingDown = make(['M23 18l-9.5-9.5-5 5L1 6', 'M17 18h6v-6'])
export const CloseIcon = make(['M6 6l12 12', 'M18 6L6 18'])
export const CameraIcon = make(['M4 7h3l2-3h6l2 3h3v13H4z', 'M12 17a4 4 0 1 0 0-8 4 4 0 0 0 0 8z'])
