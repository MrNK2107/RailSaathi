import type { HealthResponse, Language } from '../api/types'
import type { Strings } from '../i18n/strings'

interface Props {
  t: Strings
  language: Language
  onLanguage: (lang: Language) => void
  health: HealthResponse | null
}

export function Header({ t, language, onLanguage, health }: Props) {
  const aiActive = Boolean(health?.ai?.active)
  return (
    <header className="bg-rail-800 text-white">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{t.appName}</h1>
          <p className="text-sm text-rail-100">{t.appSubtitle}</p>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          {health?.data_mode === 'live' && (
            <span className="rounded bg-emerald-400 px-2 py-0.5 font-semibold text-slate-900">{t.liveBadge}</span>
          )}
          <span className="flex items-center gap-1.5" role="status">
            <span aria-hidden className={`h-2.5 w-2.5 rounded-full ${health ? 'bg-emerald-400' : 'bg-red-400'}`} />
            {health ? t.online : t.offline}
          </span>
          <span className="hidden text-rail-100 sm:inline">{aiActive ? t.aiOn : t.aiOff}</span>
          <label className="flex items-center gap-2">
            <span>{t.language}</span>
            <select
              value={language}
              onChange={(e) => onLanguage(e.target.value as Language)}
              className="rounded border border-rail-600 bg-rail-700 px-2 py-1 text-white"
            >
              <option value="en">English</option>
              <option value="ta">தமிழ்</option>
            </select>
          </label>
        </div>
      </div>
    </header>
  )
}

export function DemoBanner({ text, live = false }: { text: string; live?: boolean }) {
  const tone = live ? 'border-emerald-300 bg-emerald-50 text-emerald-900' : 'border-amber-300 bg-amber-50 text-amber-900'
  return (
    <div role="note" className={`border-b px-4 py-2 text-center text-sm ${tone}`}>
      {text}
    </div>
  )
}
