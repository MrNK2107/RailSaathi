// The one provenance badge used on every screen that shows railway data (Honesty requirements).
// `unavailable` (or missing provenance) renders an explicit empty state with the reason, never placeholder data.
// `demo` renders nothing: demo data is local/dev only (production refuses it) and is not labelled in the UI.
import type { DataMode, Provenance } from '../api/types'
import { useOptionalApp } from '../mobile/PlannerContext'
import { fill, type MobileStrings } from '../mobile/strings'
import { formatDay, formatTime } from '../utils/format'

type LabelledMode = Exclude<DataMode, 'demo'>

export const DEFAULT_PROVENANCE_LABELS: Record<LabelledMode, string> = {
  live: 'LIVE',
  cached: 'CACHED',
  stale: 'STALE',
  fallback: 'FALLBACK',
  unknown: 'UNVERIFIED',
  unavailable: 'UNAVAILABLE',
}

const STYLE: Record<LabelledMode, string> = {
  live: 'bg-match-50 text-match-700',
  cached: 'bg-sky-50 text-sky-800',
  stale: 'bg-amber-50 text-amber-800',
  fallback: 'bg-amber-50 text-amber-800',
  unknown: 'bg-ink-100 text-ink-700',
  unavailable: 'bg-red-50 text-red-800',
}

// Known backend source names (DataProvenance.source is English) and their key in m.profile.providers.
const SOURCE_KEYS: Record<string, string> = { 'NTES (unofficial client)': 'ntes', 'RailRadar live API (third-party)': 'railradar' }

/** The source name in the UI language; unknown sources are shown as given. */
export function sourceName(source: string, m?: MobileStrings): string {
  const key = SOURCE_KEYS[source]
  return (key && m?.profile.providers[key]) || source
}

/** The note in the UI language from its codes; the English note when there are no codes or one is unknown. */
export function noteText(p: Pick<Provenance, 'note' | 'note_codes' | 'note_params'>, m?: MobileStrings): string {
  const codes = p.note_codes ?? []
  if (!m || codes.length === 0 || codes.some((c) => !(c in m.notes))) return p.note
  return codes.map((c) => fill(m.notes[c], p.note_params ?? {})).join(' ')
}

export interface ProvenanceBadgeProps {
  provenance: Provenance | null | undefined
  /** Mode only, for places that know the data mode but have no provenance object (health, saved trips). */
  mode?: string | null
  /** `chip`: compact label (cards); `full`: label + source, retrieval time and note. */
  variant?: 'chip' | 'full'
  /** Chip only: also print the source name next to the label (e.g. "LIVE · NTES (unofficial client)"). */
  showSource?: boolean
  /** Reason shown when there is no provenance at all. */
  reason?: string
  /** Localised overrides for the mode labels. */
  labels?: Partial<Record<LabelledMode, string>>
  unavailableTitle?: string
  className?: string
}

export function ProvenanceBadge({
  provenance, mode, variant = 'chip', reason, labels: labelProp, unavailableTitle: titleProp, className = '',
  showSource = false,
}: ProvenanceBadgeProps) {
  // Inside the mobile app the labels follow the UI language; explicit props still win.
  const m = useOptionalApp()?.m
  const labels = m ? { live: m.live, ...m.provenance, ...labelProp } : labelProp
  const unavailableTitle = titleProp ?? m?.dataUnavailable ?? 'Data unavailable'
  const defaultReason = m?.noDataReason ?? 'No data could be obtained from the data source.'
  if (provenance?.mode === 'demo' || (!provenance && mode === 'demo')) return null
  if (!provenance && mode && mode !== 'unavailable') {
    const known: LabelledMode = mode in DEFAULT_PROVENANCE_LABELS ? (mode as LabelledMode) : 'unknown'
    return (
      <span data-testid="provenance-badge" data-mode={known} className={className}>
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${STYLE[known]}`}>
          {labels?.[known] ?? DEFAULT_PROVENANCE_LABELS[known]}
        </span>
      </span>
    )
  }
  if (!provenance || provenance.mode === 'unavailable') {
    const why = (provenance && noteText(provenance, m)) || reason || defaultReason
    return (
      <section role="status" data-testid="provenance-badge" data-mode="unavailable"
        className={`rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-900 ${className}`}>
        <p className="font-bold">{unavailableTitle}</p>
        <p className="mt-1 text-xs">{why}</p>
        {provenance?.source && <p className="mt-1 text-[11px] text-red-800">{sourceName(provenance.source, m)}</p>}
      </section>
    )
  }
  const label = labels?.[provenance.mode] ?? DEFAULT_PROVENANCE_LABELS[provenance.mode]
  const when = `${formatDay(provenance.as_of)} ${formatTime(provenance.as_of)} IST`
  const source = sourceName(provenance.source, m)
  const note = noteText(provenance, m)
  const title = `${source} · ${when}${note ? ` · ${note}` : ''}`
  const chip = (
    <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${STYLE[provenance.mode]}`}>{label}</span>
  )
  if (variant === 'chip') {
    return (
      <span data-testid="provenance-badge" data-mode={provenance.mode} title={title}
        className={showSource ? `inline-flex flex-wrap items-center justify-end gap-1 ${className}` : className}>
        {chip}
        {showSource && <span data-testid="provenance-source" className="text-[10px] font-medium text-ink-600">{source}</span>}
      </span>
    )
  }
  return (
    <div data-testid="provenance-badge" data-mode={provenance.mode} title={title}
      className={`flex flex-wrap items-start gap-2 text-[11px] text-ink-500 ${className}`}>
      {chip}
      <span className="flex-1">
        {source} · {when}
        {note && <span className="block">{note}</span>}
      </span>
    </div>
  )
}
