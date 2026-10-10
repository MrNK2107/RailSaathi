import { useEffect, useState } from 'react'
import type { ApiClient } from './api/client'
import { RELAX_PATCHES } from './api/relax'
import { ChatPanel } from './components/ChatPanel'
import { ConfirmationView, ConfirmedView } from './components/ConfirmationView'
import { DisruptionPanel } from './components/DisruptionPanel'
import { DemoBanner, Header } from './components/Header'
import { JourneySummary } from './components/JourneySummary'
import { RecommendationPanel } from './components/RecommendationPanel'
import { usePlanner, type Planner } from './hooks/usePlanner'
import { STRINGS } from './i18n/strings'

/** Classic desktop planner view (the original UI). Shares the planner state passed in. */
export function ClassicView({ planner }: { planner: Planner }) {
  const t = STRINGS[planner.language]
  const state = planner.state
  const [reviewing, setReviewing] = useState(true)

  useEffect(() => {
    if (state?.status === 'awaiting_confirmation') setReviewing(true)
  }, [state?.status, state?.selected_option_id])

  useEffect(() => {
    document.documentElement.lang = planner.language
  }, [planner.language])

  const isLive = (state?.data_mode ?? planner.health?.data_mode) === 'live'
  const busy = planner.loading
  const showDisruption = state && ['presenting_recommendations', 'awaiting_confirmation', 'confirmed'].includes(state.status)

  return (
    <div className="min-h-screen">
      <a href="#chat-input" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:bg-white focus:p-2">
        Skip to chat input
      </a>
      <Header t={t} language={planner.language} onLanguage={planner.setLanguage} health={planner.health} />
      <a href="#/home" className="block bg-rail-700 px-4 py-1 text-center text-xs text-white underline">Open the mobile app view</a>
      {isLive && <DemoBanner text={t.liveBanner} live />}
      <main className="mx-auto grid max-w-7xl gap-4 p-4 lg:grid-cols-12">
        <div className="lg:col-span-5 lg:h-[calc(100vh-150px)] lg:sticky lg:top-4">
          <ChatPanel
            t={t}
            language={planner.language}
            messages={planner.messages}
            loading={busy}
            error={planner.error}
            canRetry={planner.canRetry}
            onSend={planner.send}
            onRetry={() => planner.retry()}
            onRestart={planner.restart}
            onCancel={planner.cancel}
          />
        </div>
        <div className="space-y-4 lg:col-span-7">
          {state && (
            <>
              {state.status === 'confirmed' && <ConfirmedView t={t} state={state} />}
              {state.status === 'cancelled' && (
                <p role="status" className="rounded-lg border border-slate-300 bg-white p-4 text-slate-700">
                  {STRINGS[planner.language].cancelPlan} ✓ — {t.newPlan}?
                </p>
              )}
              {state.status === 'awaiting_confirmation' && reviewing && (
                <ConfirmationView t={t} state={state} disabled={busy}
                  onConfirm={() => planner.confirm(state.selected_option_id)} onBack={() => setReviewing(false)} />
              )}
              <JourneySummary t={t} state={state} reference={planner.reference} disabled={busy || state.status === 'cancelled'}
                onPatch={planner.patch} />
              <RecommendationPanel t={t} state={state} disabled={busy} onSelect={planner.select}
                onRelax={(c) => planner.patch(RELAX_PATCHES[c] ?? {})} />
              {showDisruption && (
                <DisruptionPanel t={t} state={state} live={isLive} events={isLive ? [] : planner.reference?.disruption_events ?? []}
                  disabled={busy} onReassess={planner.reassess} />
              )}
            </>
          )}
        </div>
      </main>
    </div>
  )
}


/** Standalone classic app (own planner session). Used by the classic-view tests. */
export default function ClassicApp({ client }: { client?: ApiClient }) {
  const planner = usePlanner(client)
  return <ClassicView planner={planner} />
}
