// Accessibility preference toggles. Each is a hard routing constraint on the backend.
import type { RoutePreferencesBody } from '../../../api/types'
import { NAV_PREF_ICONS } from '../../navAssets'
import { useApp } from '../../PlannerContext'

export type PrefKey = keyof RoutePreferencesBody

export function preferenceLabels(n: { avoidStairs: string; wheelchair: string; verifiedOnly: string }) {
  return [
    ['avoid_stairs', n.avoidStairs],
    ['wheelchair', n.wheelchair],
    ['require_verified_accessibility', n.verifiedOnly],
  ] as const satisfies readonly (readonly [PrefKey, string])[]
}

export function PreferenceChips({ prefs, onToggle }: { prefs: RoutePreferencesBody; onToggle: (key: PrefKey) => void }) {
  const { m } = useApp()
  const n = m.navigation
  return (
    <fieldset className="rounded-2xl bg-white p-3 shadow-card ring-1 ring-ink-100">
      <legend className="px-1 text-sm font-bold text-brand-900">{n.prefs}</legend>
      <div className="mt-1 grid grid-cols-3 gap-2">
        {preferenceLabels(n).map(([key, text]) => {
          const on = prefs[key]
          const icon = NAV_PREF_ICONS[key]
          return (
            <button key={key} type="button" aria-pressed={on} onClick={() => onToggle(key)}
              className={`flex min-w-0 flex-col items-center gap-1 rounded-xl p-2 text-center text-[11px] font-semibold leading-tight ring-2 ${on ? 'bg-brand-50 text-brand-900 ring-brand-600' : 'bg-white text-ink-700 ring-ink-100'}`}>
              <img src={icon.src} alt="" width={icon.width} height={icon.height} className="h-11 w-11 rounded-lg" />
              <span className="break-words">{text}</span>
            </button>
          )
        })}
      </div>
    </fieldset>
  )
}
