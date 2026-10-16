import { useApp } from '../PlannerContext'
import { VOICE_ART } from '../voiceAssets'
import { micStatus, Picture, SpeechSelector, StatusLine, VoiceWave, type MicProps } from './VoiceHero'

/**
 * Compact version of the hero shown once the conversation has started: the robot and waves stay
 * on the station photo, the mic moves into the composer at the bottom of the chat.
 */
export function VoiceStrip({ micState, errorCode, permission, transcriptReady, speech, onSpeechChange }: Omit<MicProps, 'onMicToggle'>) {
  const { m } = useApp()
  const listening = micState === 'listening'
  const [tone, status] = micStatus(m.plan, micState, errorCode, permission, transcriptReady)
  return (
    <section data-testid="voice-strip" aria-labelledby="voice-title" className="relative overflow-hidden bg-brand-100">
      <Picture art={VOICE_ART.background} alt="" className="absolute inset-0 h-full w-full object-cover object-[center_70%]" />
      <div aria-hidden className="absolute inset-0 bg-gradient-to-b from-white/70 via-white/30 to-white" />
      <h1 id="voice-title" className="relative pt-2 text-center text-base font-extrabold text-brand-900">{m.plan.title}</h1>
      <div className="relative flex items-center justify-center gap-1 px-4 pt-1">
        <VoiceWave listening={listening} mirrored size="sm" />
        <Picture art={VOICE_ART.robot} alt=""
          className={`h-20 w-auto shrink-0 object-contain drop-shadow-lg transition-transform duration-500 ${listening ? 'scale-105' : ''}`} />
        <VoiceWave listening={listening} size="sm" />
      </div>
      <div className="relative flex flex-col items-center gap-2 px-4 pb-3 pt-1">
        <StatusLine tone={tone} text={status} compact />
        <SpeechSelector speech={speech} onSpeechChange={onSpeechChange} disabled={listening} compact />
      </div>
    </section>
  )
}
