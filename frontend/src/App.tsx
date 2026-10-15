import { lazy, Suspense, useEffect, type ComponentType } from 'react'
import type { ApiClient } from './api/client'
import { ClassicView } from './ClassicApp'
import { usePlanner } from './hooks/usePlanner'
import { ScreenBoundary } from './components/ScreenBoundary'
import { AppProvider } from './mobile/PlannerContext'
import { useRoute, type Route } from './mobile/router'
import { MOBILE_STRINGS } from './mobile/strings'
import Confirmation from './mobile/screens/Confirmation'
import Dashboard from './mobile/screens/Dashboard'
import GoalPlanner from './mobile/screens/GoalPlanner'
import TicketingGuidance from './mobile/screens/TicketingGuidance'
import HelpAssistance from './mobile/screens/HelpAssistance'
import JourneyDetails from './mobile/screens/JourneyDetails'
import JourneyOptions from './mobile/screens/JourneyOptions'
import StationNavigation from './mobile/screens/StationNavigation'
import { Alerts, MyTrips, Profile } from './mobile/screens/TabPages'
import VoiceAgent from './mobile/screens/VoiceAgent'

// The virtual tour (three.js, Maps) is a separate chunk, kept out of the initial bundle.
const StationTour = lazy(() => import('./mobile/screens/StationTour'))

const SCREENS: Record<Exclude<Route, 'classic'>, ComponentType> = {
  home: Dashboard,
  plan: VoiceAgent,
  options: JourneyOptions,
  navigation: StationNavigation,
  details: JourneyDetails,
  help: HelpAssistance,
  confirmation: Confirmation,
  trips: MyTrips,
  alerts: Alerts,
  profile: Profile,
  goal: GoalPlanner,
  ticketing: TicketingGuidance,
  tour: StationTour,
}

/** Mobile-first RailSaathi app. One planner session is shared by every screen. */
export default function App({ client }: { client?: ApiClient }) {
  const planner = usePlanner(client)
  const [route, go, back] = useRoute()

  useEffect(() => {
    document.documentElement.lang = planner.language
  }, [planner.language])

  if (route === 'classic') return <ClassicView planner={planner} />
  const ScreenComponent = SCREENS[route]
  const errors = MOBILE_STRINGS[planner.language].errors
  return (
    <AppProvider value={{ planner, route, go, back }}>
      {/* Keyed by route so leaving a failed screen recovers. */}
      <ScreenBoundary key={route} message={errors.screenFailed} reloadLabel={errors.reload}>
        <Suspense fallback={<p role="status" className="p-6 text-center text-sm text-ink-500">{errors.loadingScreen}</p>}>
          <ScreenComponent />
        </Suspense>
      </ScreenBoundary>
    </AppProvider>
  )
}
