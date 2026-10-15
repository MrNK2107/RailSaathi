// The one provenance badge used on every screen that shows railway data (Honesty requirements).
// `unavailable` (or missing provenance) renders an explicit empty state with the reason, never placeholder data.
import type { DataMode, Provenance } from '../api/types'
import { formatDay, formatTime } from '../utils/format'

export const DEFAULT_PROVENANCE_LABELS: Record<DataMode, string> = {
  live: 'LIVE',
  cached: 'CACHED',
  stale: 'STALE',
  demo: 'DEMO',
  fallback: 'FALLBACK',
  unknown: 'UNVERIFIED',
  unavailable: 'UNAVAILABLE',
}

const STYLE: Record<DataMode, string> = {
  live: 'bg-match-50 text-match-600',
  cached: 'bg-sky-50 text-sky-800',
  stale: 'bg-amber-50 text-amber-800',
  demo: 'bg-violet-50 text-violet-800',
  fallback: 'bg-amber-50 text-amber-800',
  unknown: 'bg-ink-100 text-ink-700',
  unavailable: 'bg-red-50 text-red-800',
}

export interface ProvenanceBadgeProps {
  provenance: Provenance | null | undefined
  /** Mode only, for places that know the data mode but have no provenance object (health, saved trips). */
  mode?: string | null
  /** `chip`: compact label (cards); `full`: label + source, retrieval time and note. */
  variant?: 'chip' | 'full'
  /** Reason shown when there is no provenance at all. */
  reason?: string
  /** Localised overrides for the mode labels. */
  labels?: Partial<Record<DataMode, string>>
  unavailableTitle?: string
  className?: string
}

export function ProvenanceBadge({
  provenance, mode, variant = 'chip', reason, labels, unavailableTitle = 'Data unavailable', className = '',
}: ProvenanceBadgeProps) {
  if (!provenance && mode && mode !== 'unavailable') {
    const known: DataMode = mode in DEFAULT_PROVENANCE_LABELS ? (mode as DataMode) : 'unknown'
    return (
      <span data-testid="provenance-badge" data-mode={known} className={className}>
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${STYLE[known]}`}>
          {labels?.[known] ?? DEFAULT_PROVENANCE_LABELS[known]}
        </span>
      </span>
    )
  }
  if (!provenance || provenance.mode === 'unavailable') {
    const why = provenance?.note || reason || 'No data could be obtained from the data source.'
    return (
      <section role="status" data-testid="provenance-badge" data-mode="unavailable"
        className={`rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-900 ${className}`}>
        <p className="font-bold">{unavailableTitle}</p>
        <p className="mt-1 text-xs">{why}</p>
        {provenance?.source && <p className="mt-1 text-[11px] text-red-800">{provenance.source}</p>}
      </section>
    )
  }
  const label = labels?.[provenance.mode] ?? DEFAULT_PROVENANCE_LABELS[provenance.mode]
  const when = `${formatDay(provenance.as_of)} ${formatTime(provenance.as_of)} IST`
  const title = `${provenance.source} · ${when}${provenance.note ? ` · ${provenance.note}` : ''}`
  const chip = (
    <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${STYLE[provenance.mode]}`}>{label}</span>
  )
  if (variant === 'chip') {
    return (
      <span data-testid="provenance-badge" data-mode={provenance.mode} title={title} className={className}>{chip}</span>
    )
  }
  return (
    <div data-testid="provenance-badge" data-mode={provenance.mode} title={title}
      className={`flex flex-wrap items-start gap-2 text-[11px] text-ink-500 ${className}`}>
      {chip}
      <span className="flex-1">
        {provenance.source} · {when}
        {provenance.note && <span className="block">{provenance.note}</span>}
      </span>
    </div>
  )
}
