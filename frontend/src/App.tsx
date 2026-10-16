import { lazy, Suspense, useEffect, type ComponentType } from 'react'
import type { ApiClient } from './api/client'
import { usePlanner } from './hooks/usePlanner'
import { ScreenBoundary } from './components/ScreenBoundary'
import { AppProvider } from './mobile/PlannerContext'
import { useRoute, type Route } from './mobile/router'
import { MOBILE_STRINGS } from './mobile/strings'

// Every screen is its own chunk (the entry bundle holds only the shell and router); the tour and AR code split further.
const Confirmation = lazy(() => import('./mobile/screens/Confirmation'))
const Dashboard = lazy(() => import('./mobile/screens/Dashboard'))
const GoalPlanner = lazy(() => import('./mobile/screens/GoalPlanner'))
const TicketingGuidance = lazy(() => import('./mobile/screens/TicketingGuidance'))
const HelpAssistance = lazy(() => import('./mobile/screens/HelpAssistance'))
const JourneyDetails = lazy(() => import('./mobile/screens/JourneyDetails'))
const JourneyOptions = lazy(() => import('./mobile/screens/JourneyOptions'))
const StationNavigation = lazy(() => import('./mobile/screens/StationNavigation'))
const VoiceAgent = lazy(() => import('./mobile/screens/VoiceAgent'))
const StationTour = lazy(() => import('./mobile/screens/StationTour'))
const Alerts = lazy(() => import('./mobile/screens/TabPages').then((m) => ({ default: m.Alerts })))
const MyTrips = lazy(() => import('./mobile/screens/TabPages').then((m) => ({ default: m.MyTrips })))
const Profile = lazy(() => import('./mobile/screens/TabPages').then((m) => ({ default: m.Profile })))

const SCREENS: Record<Route, ComponentType> = {
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

  const Screen = SCREENS[route]
  const errors = MOBILE_STRINGS[planner.language].errors
  return (
    <AppProvider value={{ planner, route, go, back }}>
      {/* Keyed by route so leaving a failed screen recovers. */}
      <ScreenBoundary key={route} message={errors.screenFailed} reloadLabel={errors.reload}>
        <Suspense fallback={<p role="status" className="p-6 text-center text-sm text-ink-500">{errors.loadingScreen}</p>}>
          <Screen />
        </Suspense>
      </ScreenBoundary>
    </AppProvider>
  )
}
