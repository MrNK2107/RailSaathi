// Station photo banner with the station name and the page heading. The only photo is of Chennai Central, so other
// stations get the heading without a photo rather than a mislabelled one.
import { NAV_BANNER } from '../../navAssets'
import { useApp } from '../../PlannerContext'

const PHOTO_STATION = 'chennai_central'

export function NavBanner({ stationId, stationName }: { stationId: string; stationName: string | null }) {
  const { m } = useApp()
  const n = m.navigation
  return (
    <section aria-labelledby="nav-title">
      {stationId === PHOTO_STATION && (
        <div className="relative mx-4 mt-3 overflow-hidden rounded-2xl bg-brand-100 shadow-card">
          <picture>
            <source srcSet={NAV_BANNER.webp} type="image/webp" />
            <img src={NAV_BANNER.jpg} alt={n.bannerAlt} width={NAV_BANNER.width} height={NAV_BANNER.height}
              decoding="async" className="block h-auto w-full" />
          </picture>
          {stationName && (
            <span className="absolute bottom-2 left-2 max-w-[calc(100%-1rem)] truncate rounded-full bg-white/95 px-3 py-1 text-xs font-bold text-brand-900 shadow-card">
              {stationName}
            </span>
          )}
        </div>
      )}
      <div className="px-4 pt-3">
        <h1 id="nav-title" className="text-xl font-extrabold tracking-tight text-brand-900">{n.title}</h1>
        <p className="text-xs text-ink-500">
          {n.subtitle}{stationName && stationId !== PHOTO_STATION ? ` · ${stationName}` : ''}
        </p>
      </div>
    </section>
  )
}
