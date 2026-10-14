import { useEffect, type ComponentType } from 'react'
import type { ApiClient } from './api/client'
import { ClassicView } from './ClassicApp'
import { usePlanner } from './hooks/usePlanner'
import { AppProvider } from './mobile/PlannerContext'
import { useRoute, type Route } from './mobile/router'
import Confirmation from './mobile/screens/Confirmation'
import Dashboard from './mobile/screens/Dashboard'
import GoalPlanner from './mobile/screens/GoalPlanner'
import HelpAssistance from './mobile/screens/HelpAssistance'
import JourneyDetails from './mobile/screens/JourneyDetails'
import JourneyOptions from './mobile/screens/JourneyOptions'
import StationNavigation from './mobile/screens/StationNavigation'
import { Alerts, MyTrips, Profile } from './mobile/screens/TabPages'
import VoiceAgent from './mobile/screens/VoiceAgent'

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
  return (
    <AppProvider value={{ planner, route, go, back }}>
      <ScreenComponent />
    </AppProvider>
  )
}
