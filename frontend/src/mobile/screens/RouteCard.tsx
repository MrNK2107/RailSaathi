import { ArrowRight, TrainIcon } from '../icons'
import { ROUTE_IMAGES, type RouteImageId } from '../routeImages'

interface Props {
  title: string
  /** Primary station pair, e.g. "MAS → SBC" (from backend station catalogue; nothing is fetched). */
  codes: string
  station: string
  /** Team-supplied photo, or null: then a neutral illustration is shown instead of an unrelated photo. */
  image: RouteImageId | null
  cta: string
  disabled?: boolean
  onClick: () => void
}

/** Popular-route card: photo, route name, station codes and a "plan" affordance. No fares/timings: those come from the planner. */
export function RouteCard({ title, codes, station, image, cta, disabled, onClick }: Props) {
  const img = image ? ROUTE_IMAGES[image] : null
  return (
    <button type="button" disabled={disabled} onClick={onClick}
      className="group flex min-h-11 w-full min-w-0 flex-col overflow-hidden rounded-2xl bg-white text-left shadow-card ring-1 ring-ink-100 hover:ring-brand-200 disabled:opacity-60">
      <span className="relative block aspect-[4/3] w-full overflow-hidden bg-gradient-to-br from-brand-100 to-brand-50">
        {img ? (
          <picture>
            <source srcSet={img.webp} type="image/webp" />
            <img src={img.jpg} alt="" loading="lazy" decoding="async" width={img.width} height={img.height}
              className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105 motion-reduce:transition-none motion-reduce:group-hover:scale-100" />
          </picture>
        ) : (
          <span aria-hidden className="grid h-full w-full place-items-center text-brand-300"><TrainIcon size={44} /></span>
        )}
        <span className="absolute left-2 top-2 rounded-full bg-white/90 px-2 py-0.5 text-[10px] font-bold tracking-wide text-brand-900 shadow-sm">
          {codes}
        </span>
      </span>
      <span className="flex flex-1 flex-col gap-1 p-3">
        <span className="break-words text-sm font-bold leading-snug text-brand-900">{title}</span>
        <span className="truncate text-xs text-ink-500">{station}</span>
        <span className="mt-1 flex items-center justify-between gap-1 text-xs font-semibold text-brand-600">
          <span>{cta}</span>
          <ArrowRight size={14} className="shrink-0" />
        </span>
      </span>
    </button>
  )
}
