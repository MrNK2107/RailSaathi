import { useCallback, useRef, useState } from 'react'
import { useMicPermission } from '../../hooks/useMicPermission'
import { useSpeechRecognition } from '../../hooks/useSpeech'
import { STRINGS } from '../../i18n/strings'
import { RefreshIcon } from '../icons'
import { useApp } from '../PlannerContext'
import { SPEECH_OPTIONS, type SpeechOptionId } from '../strings'
import { AppHeader, ErrorBanner, PrimaryButton, Screen } from '../ui'
import { ChatThread } from './ChatThread'
import { Composer } from './Composer'
import { ExtractedDetails } from './ExtractedDetails'
import { ProgressSteps } from './ProgressSteps'
import { VoiceHero } from './VoiceHero'
import { VoiceStrip } from './VoiceStrip'

const speechCode = (id: SpeechOptionId) => SPEECH_OPTIONS.find((o) => o.id === id)?.code ?? 'en-IN'
const RESULT_STATUSES = ['presenting_recommendations', 'awaiting_confirmation', 'no_feasible_options', 'confirmed']

export default function VoiceAgent() {
  const { planner, go, m } = useApp()
  const lang = planner.language
  const state = planner.state
  const [draft, setDraft] = useState('')
  const [fromVoice, setFromVoice] = useState(false)
  // The recognition language follows the UI language; a manual choice applies only until the UI language changes.
  const [picked, setPicked] = useState<{ ui: string; id: SpeechOptionId } | null>(null)
  const speech: SpeechOptionId = picked && picked.ui === lang ? picked.id : lang === 'ta' ? 'ta' : 'en'
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const onTranscript = useCallback((text: string) => {
    setDraft(text)
    setFromVoice(true)
  }, [])
  const mic = useSpeechRecognition(speechCode(speech), onTranscript)
  const permission = useMicPermission()
  const listening = mic.state === 'listening'
  const transcriptReady = fromVoice && mic.state === 'idle' && draft.trim().length > 0
  const toggleMic = () => (listening ? mic.stop() : mic.start(draft))

  const submit = async () => {
    const text = draft.trim()
    if (!text || planner.loading || listening) return
    setDraft('')
    setFromVoice(false)
    if (inputRef.current) inputRef.current.style.height = 'auto'
    await planner.send(text)
  }

  const started = planner.messages.some((msg) => msg.role === 'user')
  // The journey card appears only once the backend reports every mandatory field and has moved past collecting.
  const detailsComplete = Boolean(state && state.missing_fields.length === 0 && state.status !== 'collecting_details')
  const resultsReady = Boolean(state && RESULT_STATUSES.includes(state.status))
  const source = planner.response?.extraction?.source
  const micProps = {
    micState: mic.state, errorCode: mic.errorCode, permission, transcriptReady, speech,
    onSpeechChange: (id: SpeechOptionId) => setPicked({ ui: lang, id }),
  }

  return (
    <Screen footer={(
      <div className="space-y-2">
        {resultsReady && <PrimaryButton onClick={() => go('options')}>{m.plan.viewOptions}</PrimaryButton>}
        {fromVoice && !listening && <p className="text-xs font-medium text-amber-800">{m.plan.reviewTranscript}</p>}
        <Composer draft={draft} onDraft={(t) => { setDraft(t); setFromVoice(false) }} onSubmit={() => void submit()}
          sending={planner.loading} inputRef={inputRef} listening={listening}
          mic={started ? { state: mic.state, onToggle: toggleMic } : undefined} />
      </div>
    )}>
      <AppHeader right={(
        <button type="button" onClick={() => planner.restart()} disabled={planner.loading}
          className="inline-flex min-h-11 items-center gap-1 rounded-full border border-ink-300 px-3 py-1 text-xs font-semibold text-brand-700">
          <RefreshIcon size={14} /> {m.plan.newPlan}
        </button>
      )} />

      {started ? <VoiceStrip {...micProps} /> : <VoiceHero {...micProps} onMicToggle={toggleMic} />}

      <ErrorBanner />

      <ChatThread messages={planner.messages} loading={planner.loading}>
        {source && (
          <p className="mt-2 text-[11px] text-ink-500">{source === 'rules' ? m.plan.understoodBy.rules : m.plan.understoodBy.ai}</p>
        )}
      </ChatThread>

      {state && started && !detailsComplete && <ProgressSteps state={state} />}
      {state && detailsComplete && (
        <>
          <ExtractedDetails state={state} t={STRINGS[lang]} disabled={planner.loading} onPatch={planner.patch} />
          <ProgressSteps state={state} />
        </>
      )}
      <div className="h-4" />
    </Screen>
  )
}
