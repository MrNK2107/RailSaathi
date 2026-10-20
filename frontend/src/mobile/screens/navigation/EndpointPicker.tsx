// Start / destination selectors with a swap button. Options are the station's named places (the hook hides
// junctions and corridors).
import type { StationNode } from '../../../api/types'
import { useApp } from '../../PlannerContext'

interface Props {
  places: StationNode[]
  from: string
  to: string
  sameEndpoints: boolean
  onFrom: (id: string) => void
  onTo: (id: string) => void
  onSwap: () => void
}

const SELECT = 'mt-0.5 min-h-[44px] w-full min-w-0 rounded-xl border border-ink-300 bg-white px-2.5 py-2 text-sm font-medium text-ink-900 focus:border-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-600/30'

export function EndpointPicker({ places, from, to, sameEndpoints, onFrom, onTo, onSwap }: Props) {
  const { m } = useApp()
  const n = m.navigation
  return (
    <div className="rounded-2xl bg-white p-3 shadow-card ring-1 ring-ink-100">
      <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2">
        <span aria-hidden="true" className="h-3 w-3 rounded-full bg-match-600 ring-2 ring-match-50" />
        <div className="min-w-0">
          <label htmlFor="nav-from" className="block text-xs font-medium text-ink-500">{n.pickFrom}</label>
          <select id="nav-from" value={from} onChange={(e) => onFrom(e.target.value)} className={SELECT}>
            {places.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </div>
        <button type="button" aria-label={n.swap} title={n.swap} disabled={!to} onClick={onSwap}
          className="row-span-2 grid h-11 w-11 place-items-center rounded-full bg-brand-50 text-lg font-bold text-brand-700 ring-1 ring-brand-100 disabled:opacity-40">
          <span aria-hidden="true">⇅</span>
        </button>
        <span aria-hidden="true" className="h-3 w-3 rounded-full bg-red-600 ring-2 ring-red-100" />
        <div className="min-w-0">
          <label htmlFor="nav-to" className="block text-xs font-medium text-ink-500">{n.pickTo}</label>
          <select id="nav-to" value={to} onChange={(e) => onTo(e.target.value)} className={SELECT}>
            <option value="">{n.chooseDestination}</option>
            {places.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </div>
      </div>
      {sameEndpoints && <p role="alert" className="mt-2 rounded-lg bg-amber-50 px-2 py-1 text-xs text-amber-900">{n.sameEndpoints}</p>}
    </div>
  )
}
