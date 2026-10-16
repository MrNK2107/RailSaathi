// Demo-only what-if: close one pathway of the shown route and watch the engine reroute. The closure travels with the
// route request (`simulate_closures`, with `previous_edge_ids` so the response can explain it); nothing is stored.
// Rendered only when client-config says the backend accepts simulated closures (`features.simulate_closures`).
import { useState } from 'react'
import type { RouteResult } from '../../../api/types'
import { fill } from '../../strings'
import { useApp } from '../../PlannerContext'

interface Props {
  route: RouteResult | null
  simulated: string[]
  busy: boolean
  nodeName: (id: string) => string
  onClose: (edgeId: string) => void
  onReopenAll: () => void
}

export function ClosureSimulator({ route, simulated, busy, nodeName, onClose, onReopenAll }: Props) {
  const { m } = useApp()
  const n = m.navigation
  const [closeId, setCloseId] = useState('')
  const segments = route?.status === 'ok' ? route.segments.filter((s) => !simulated.includes(s.edge_id)) : []
  return (
    <section className="rounded-2xl border border-dashed border-red-200 bg-white p-4 shadow-card" data-testid="closure-simulator">
      <h2 className="flex items-center gap-2 text-sm font-bold text-brand-900">
        {n.closure}
        <span className="rounded-full bg-red-50 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-red-800">{n.simulatedTag}</span>
      </h2>
      <p className="text-xs text-ink-500">{n.closureHelp}</p>
      {segments.length > 0 && (
        <div className="mt-2 flex gap-2">
          <label htmlFor="nav-closure" className="sr-only">{n.closure}</label>
          <select id="nav-closure" value={closeId} onChange={(e) => setCloseId(e.target.value)}
            className="min-h-[44px] min-w-0 flex-1 rounded-lg border border-ink-300 bg-white px-2 py-1 text-xs">
            <option value="">{n.closurePick}</option>
            {segments.map((s) => <option key={s.edge_id} value={s.edge_id}>{nodeName(s.from_node)} → {nodeName(s.to_node)}</option>)}
          </select>
          <button type="button" disabled={!closeId || busy} onClick={() => { onClose(closeId); setCloseId('') }}
            className="min-h-[44px] shrink-0 rounded-lg bg-red-600 px-3 py-1 text-xs font-semibold text-white disabled:opacity-40">{n.closeBtn}</button>
        </div>
      )}
      {simulated.length > 0 && (
        <p className="mt-2 flex items-center justify-between gap-2 rounded-xl bg-red-50 px-3 py-2 text-xs text-red-800">
          <span>{fill(n.simulatedActive, { count: simulated.length })}</span>
          <button type="button" onClick={onReopenAll} disabled={busy} className="min-h-[44px] font-semibold underline">{n.reopenAll}</button>
        </p>
      )}
    </section>
  )
}
