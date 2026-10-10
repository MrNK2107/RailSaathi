import type { MicState } from '../hooks/useSpeech'
import type { Strings } from '../i18n/strings'

interface Props {
  t: Strings
  state: MicState
  onStart: () => void
  onStop: () => void
}

const STYLES: Record<MicState, string> = {
  idle: 'border-slate-300 text-slate-700 hover:bg-slate-50',
  listening: 'border-red-600 bg-red-600 text-white hover:bg-red-700',
  processing: 'border-amber-300 bg-amber-50 text-amber-800',
  error: 'border-red-300 text-red-700',
  unsupported: 'border-slate-200 text-slate-300 cursor-not-allowed',
}

export function MicButton({ t, state, onStart, onStop }: Props) {
  const label = state === 'unsupported' ? t.mic.unsupported : state === 'error' ? t.mic.error : t.mic[state]
  return (
    <button
      type="button"
      onClick={state === 'listening' ? onStop : onStart}
      disabled={state === 'unsupported' || state === 'processing'}
      aria-label={label}
      title={label}
      aria-pressed={state === 'listening'}
      data-state={state}
      className={`flex items-center gap-1.5 rounded border px-3 py-2 ${STYLES[state]}`}
    >
      {state === 'listening' ? (
        <>
          <span aria-hidden className="h-3 w-3 animate-pulse rounded-sm bg-white" />
          <span className="text-sm font-semibold">{t.mic.stopLabel}</span>
        </>
      ) : (
        <svg aria-hidden width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="9" y="2" width="6" height="12" rx="3" />
          <path d="M5 10v1a7 7 0 0 0 14 0v-1M12 18v4" />
        </svg>
      )}
    </button>
  )
}
