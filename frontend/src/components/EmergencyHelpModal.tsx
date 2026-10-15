// Emergency and station help. Helplines, amenities and notes all come from the station info API
// (national helplines merged with the station's own, each with a source); no number is hard-coded here.
import { useEffect, useState } from 'react'
import { ApiError, type ApiClient } from '../api/client'
import type { StationInfo } from '../api/types'
import { CloseIcon, PhoneIcon, ShieldIcon } from '../mobile/icons'
import type { MobileStrings } from '../mobile/strings'
import { Modal } from './Modal'
import { ProvenanceBadge } from './ProvenanceBadge'
import { isHttps, telHref } from './safeUrl'

export interface EmergencyHelpModalProps {
  isOpen: boolean
  onClose: () => void
  client: ApiClient
  m: MobileStrings
  stationId: string
}

const TITLE_ID = 'sos-title'

export default function EmergencyHelpModal({ isOpen, onClose, client, m, stationId }: EmergencyHelpModalProps) {
  const [info, setInfo] = useState<StationInfo | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const s = m.sos

  useEffect(() => {
    if (!isOpen) return undefined
    const ctl = new AbortController()
    setInfo(null)
    setError(null)
    client.stationInfo(stationId, { signal: ctl.signal }).then(setInfo, (e) => {
      if (!(e instanceof ApiError && e.isAborted)) setError(e instanceof ApiError ? e : new ApiError(0, 'unknown', 'Something went wrong.'))
    })
    return () => ctl.abort()
  }, [client, stationId, isOpen])

  return (
    <Modal open={isOpen} onClose={onClose} titleId={TITLE_ID}>
      <header className="flex items-start justify-between gap-2 border-b border-ink-100 p-4">
        <h2 id={TITLE_ID} className="flex items-center gap-2 text-base font-bold text-red-700">
          <ShieldIcon size={20} /> {s.title}
        </h2>
        <button type="button" onClick={onClose} aria-label={s.close} className="rounded-full p-1.5 text-ink-700 hover:bg-ink-100">
          <CloseIcon size={20} />
        </button>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {error && <p role="alert" className="rounded-xl bg-amber-50 p-3 text-xs text-amber-900">{s.failed}</p>}
        {!info && !error && <p role="status" className="text-sm text-ink-500">{s.loading}</p>}
        {info && (
          <>
            {info.disclaimer && <p className="rounded-xl bg-ink-100/60 p-3 text-xs text-ink-700">{info.disclaimer}</p>}
            <section aria-labelledby="sos-helplines">
              <h3 id="sos-helplines" className="text-sm font-bold text-brand-900">{s.helplines}</h3>
              <ul className="mt-2 space-y-2">
                {info.helplines.map((h) => (
                  <li key={h.id} className="rounded-xl bg-white p-3 shadow-card ring-1 ring-ink-100">
                    <div className="flex items-start justify-between gap-3">
                      <div className="text-sm">
                        <p className="font-semibold text-ink-900">{h.label}</p>
                        {h.number && <p className="font-mono text-lg font-extrabold text-brand-700">{h.number}</p>}
                        <p className="text-xs text-ink-500">{h.purpose}</p>
                      </div>
                      {h.number ? (
                        <a href={telHref(h.number)} aria-label={`${s.call} ${h.number}: ${h.label}`}
                          className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-red-600 text-white hover:bg-red-700">
                          <PhoneIcon size={18} />
                        </a>
                      ) : isHttps(h.url) && (
                        <a href={h.url} target="_blank" rel="noopener noreferrer" aria-label={`${s.openPortal}: ${h.label}`}
                          className="shrink-0 rounded-xl bg-brand-600 px-3 py-2 text-xs font-semibold text-white hover:bg-brand-700">
                          {s.openPortal} ↗
                        </a>
                      )}
                    </div>
                    {h.notes && <p className="mt-1 text-[11px] text-ink-500">{h.notes}</p>}
                    {h.sources.length > 0 && (
                      <p className="mt-1 text-[11px] text-ink-500">
                        {s.sources}:{' '}
                        {h.sources.map((src, i) => (
                          <span key={src.url}>
                            {i > 0 && ', '}
                            {isHttps(src.url)
                              ? <a href={src.url} target="_blank" rel="noopener noreferrer" className="underline">{src.name}</a>
                              : src.name}
                          </span>
                        ))}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
              {info.checked_on && <p className="mt-1 text-[11px] text-ink-500">{s.checkedOn} {info.checked_on}</p>}
            </section>

            <section aria-labelledby="sos-amenities">
              <h3 id="sos-amenities" className="text-sm font-bold text-brand-900">{s.amenities}</h3>
              {info.amenities.length === 0 ? <p className="mt-1 text-xs text-ink-500">{s.noAmenities}</p> : (
                <ul className="mt-2 space-y-2">
                  {info.amenities.map((a) => (
                    <li key={a.name} className="rounded-xl bg-white p-3 text-sm shadow-card ring-1 ring-ink-100">
                      <p className="font-semibold text-ink-900">{a.name}</p>
                      <p className="text-xs text-ink-500">{a.detail}{!a.mapped ? ` (${s.notMapped})` : ''}</p>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {info.layout_note && <p role="note" className="rounded-xl bg-amber-50 p-3 text-xs text-amber-900">{info.layout_note}</p>}
            <ProvenanceBadge provenance={info.provenance} variant="full" />
          </>
        )}
      </div>
    </Modal>
  )
}
