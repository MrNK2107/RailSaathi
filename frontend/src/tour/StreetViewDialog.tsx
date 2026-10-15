// "See it": a node's panorama in Google's StreetViewPanorama (Maps JavaScript API), with steps along the route's
// panorama stops. Without a browser key, or when Maps fails or rejects the key, it explains why and links out to
// Google Maps instead. The imagery stays inside Google's viewer; nothing here copies it anywhere else.
import { useEffect, useRef, useState } from 'react'
import type { StationTour, TourPanorama } from '../api/types'
import { Modal } from '../components/Modal'
import { CloseIcon } from '../mobile/icons'
import type { MobileStrings } from '../mobile/strings'
import { panoramaLink, placeLink } from './mapsLinks'
import { loadStreetView, onMapsAuthFailure } from './streetView'

export type StreetViewStatus = 'no_key' | 'loading' | 'ready' | 'failed'

export interface StreetViewDialogProps {
  open: boolean
  onClose: () => void
  tour: StationTour
  apiKey: string | null
  /** The panoramas to step through (the route's stops, or just the chosen one), and the one showing. */
  stops: TourPanorama[]
  index: number
  onIndex: (i: number) => void
  m: MobileStrings['tour']
}

const TITLE_ID = 'street-view-title'

export default function StreetViewDialog({ open, onClose, tour, apiKey, stops, index, onIndex, m }: StreetViewDialogProps) {
  const holder = useRef<HTMLDivElement>(null)
  const panorama = useRef<google.maps.StreetViewPanorama | null>(null)
  const [status, setStatus] = useState<StreetViewStatus>(apiKey ? 'loading' : 'no_key')
  const stop = stops[index] ?? null
  const nodeName = (id: string) => tour.nodes.find((n) => n.id === id)?.name ?? id

  // Load the library and create the panorama once per opening.
  useEffect(() => {
    if (!open) return undefined
    if (!apiKey) {
      setStatus('no_key')
      return undefined
    }
    let alive = true
    setStatus('loading')
    const offAuth = onMapsAuthFailure(() => { if (alive) setStatus('failed') })
    loadStreetView(apiKey).then((lib) => {
      if (!alive || !holder.current || !stop) return
      const pano = new lib.StreetViewPanorama(holder.current, {
        pano: stop.pano_id, pov: { heading: stop.heading, pitch: stop.pitch }, motionTracking: false,
        addressControl: false, fullscreenControl: false,
      })
      pano.addListener('status_changed', () => {
        if (alive) setStatus(pano.getStatus() === 'OK' ? 'ready' : 'failed')
      })
      panorama.current = pano
      setStatus('ready')
    }, () => { if (alive) setStatus('failed') })
    return () => {
      alive = false
      offAuth()
      panorama.current = null
    }
    // The panorama is created for the stop showing when the dialog opens; later stops move it (effect below).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, apiKey])

  // Step to another stop on the same panorama.
  useEffect(() => {
    if (!stop || !panorama.current) return
    panorama.current.setPano(stop.pano_id)
    panorama.current.setPov({ heading: stop.heading, pitch: stop.pitch })
  }, [stop])

  if (!stop) return null
  const name = nodeName(stop.node_id)
  const fallback = status === 'no_key' || status === 'failed'
  const node = tour.nodes.find((n) => n.id === stop.node_id)
  const place = placeLink(tour, node?.position)
  return (
    <Modal open={open} onClose={onClose} titleId={TITLE_ID} className="h-[92vh]">
      <header className="flex items-start justify-between gap-2 border-b border-ink-100 p-4">
        <h2 id={TITLE_ID} className="text-base font-bold text-brand-900">{m.streetViewTitle.replace('{place}', name)}</h2>
        <button type="button" onClick={onClose} aria-label={m.close} className="rounded-full p-1.5 text-ink-700 hover:bg-ink-100">
          <CloseIcon size={20} />
        </button>
      </header>
      <div className="flex flex-1 flex-col gap-3 overflow-y-auto p-4">
        {status === 'loading' && <p role="status" className="text-sm text-ink-500">{m.svLoading}</p>}
        {fallback && (
          <div role="alert" data-status={status} className="space-y-2 rounded-xl bg-amber-50 p-3 text-xs text-amber-900">
            <p>{status === 'no_key' ? m.noKey : m.outage}</p>
            <p className="flex flex-wrap gap-3">
              <a href={panoramaLink(stop)} target="_blank" rel="noopener noreferrer" className="font-bold underline">{m.openPanoInMaps}</a>
              <a href={place.url} target="_blank" rel="noopener noreferrer" className="font-bold underline">{m.openInMaps}</a>
            </p>
            <p>{place.approximate_m !== null ? m.coordsApprox.replace('{m}', String(place.approximate_m)) : m.noCoords}</p>
          </div>
        )}
        <div ref={holder} data-testid="street-view-holder" aria-label={m.streetViewTitle.replace('{place}', name)} role="region"
          className={`${fallback ? 'hidden' : 'min-h-[320px] flex-1'} rounded-xl bg-ink-100`} />
        {stops.length > 1 && (
          <nav aria-label={m.routeStops} className="flex items-center justify-between gap-2">
            <button type="button" onClick={() => onIndex(index - 1)} disabled={index === 0}
              className="rounded-xl bg-white px-3 py-2 text-xs font-semibold text-ink-700 ring-1 ring-ink-300 disabled:opacity-50">{m.prevPano}</button>
            <p aria-live="polite" className="text-center text-xs text-ink-700">
              {m.panoOf.replace('{i}', String(index + 1)).replace('{n}', String(stops.length)).replace('{place}', name)}
            </p>
            <button type="button" onClick={() => onIndex(index + 1)} disabled={index >= stops.length - 1}
              className="rounded-xl bg-white px-3 py-2 text-xs font-semibold text-ink-700 ring-1 ring-ink-300 disabled:opacity-50">{m.nextPano}</button>
          </nav>
        )}
        <p className="text-[11px] text-ink-500">{m.streetViewNote}</p>
      </div>
    </Modal>
  )
}
