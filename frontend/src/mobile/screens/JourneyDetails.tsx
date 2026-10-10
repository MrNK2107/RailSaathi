import { STRINGS } from '../../i18n/strings'
import { formatDay, formatDuration, formatRupees, formatTime } from '../../utils/format'
import {
  AlertIcon, ArrowRight, CheckIcon, ClockIcon, InfoIcon, RupeeIcon, SeatIcon, TrainIcon, UsersIcon,
} from '../icons'
import { useApp } from '../PlannerContext'
import {
  AppHeader, CategoryBadge, ErrorBanner, ModeBadge, PrimaryButton, Screen, SourceLine, selectedRecommendation,
} from '../ui'

export default function JourneyDetails() {
  const { planner, go, m } = useApp()
  const state = planner.state
  const rec = selectedRecommendation(state)
  const t = STRINGS[planner.language]

  if (!state || !rec) {
    return (
      <Screen>
        <AppHeader />
        <div className="p-4">
          <p className="rounded-2xl bg-brand-50 p-4 text-sm text-brand-900">{m.details.missing}</p>
          <div className="mt-3"><PrimaryButton onClick={() => go('options')}>{m.options.title}</PrimaryButton></div>
        </div>
      </Screen>
    )
  }

  const j = state.journey
  const o = rec.option
  const first = o.legs[0]
  const last = o.legs[o.legs.length - 1]
  const classes = o.classes.length ? o.classes : (Object.keys(o.fares) as typeof o.classes)
  const confirmed = state.status === 'confirmed' && state.confirmation?.selected_option_id === o.option_id

  const prefs: { Icon: typeof ClockIcon; text: string }[] = []
  if (j.arrival_deadline) prefs.push({ Icon: ClockIcon, text: `${m.details.arrivalBefore} ${j.arrival_deadline} (${j.deadline_strict ? m.fields.strict : m.fields.preferred})` })
  if (j.budget_limit !== null) prefs.push({ Icon: RupeeIcon, text: `${m.details.budgetUnder} ${formatRupees(j.budget_limit)} (${j.budget_strict ? m.fields.strict : m.fields.preferred})` })
  if (j.budget_priority) prefs.push({ Icon: RupeeIcon, text: t.priorities[j.budget_priority] })
  prefs.push({ Icon: SeatIcon, text: j.class_preference ? `${j.class_preference} (${j.class_strict ? m.fields.strict : m.fields.preferred})` : m.details.anyClass })
  if (j.transfer_preference === 'direct_only') prefs.push({ Icon: TrainIcon, text: j.transfer_strict ? m.details.directOnly : m.details.directPreferred })
  for (const need of j.passenger_needs) prefs.push({ Icon: UsersIcon, text: t.needs[need] })

  const confirm = async () => {
    if (confirmed || await planner.confirm(o.option_id)) go('confirmation')
  }

  return (
    <Screen footer={(
      <PrimaryButton onClick={confirm} disabled={planner.loading || state.status !== 'awaiting_confirmation' && !confirmed}>
        {m.details.confirm} <ArrowRight size={20} />
      </PrimaryButton>
    )}>
      <AppHeader />
      <div className="space-y-4 p-4">
        <h1 className="text-2xl font-extrabold text-brand-900">{m.details.title}</h1>
        <ErrorBanner />

        <section className="rounded-2xl bg-white p-4 shadow-card ring-1 ring-ink-100">
          <div className="flex flex-wrap items-center gap-1.5">
            {rec.labels.map((l) => <CategoryBadge key={l} category={l} />)}
            <span className="ml-auto"><ModeBadge mode={o.provenance.mode} /></span>
          </div>
          <div className="mt-3 flex items-center gap-3">
            <span className="grid h-11 w-11 place-items-center rounded-xl bg-brand-50 text-brand-600"><TrainIcon size={24} /></span>
            <div>
              <p className="text-lg font-bold text-brand-900">{o.legs.map((l) => l.train_no).join(' + ')}</p>
              <p className="text-sm text-ink-700">{o.legs.map((l) => l.train_name).join(' → ')}</p>
            </div>
          </div>
          <p className="mt-3 text-sm font-semibold text-ink-900">{first.from_name} ({first.from_code}) → {last.to_name} ({last.to_code})</p>
          <p className="text-xs text-ink-500">{formatDuration(o.duration_minutes)} · {o.transfers ? `${o.transfers} ${m.options.changes}` : m.options.direct}</p>
          <div className="mt-3 flex items-center gap-3">
            <div><p className="text-2xl font-extrabold text-ink-900">{formatTime(o.departure)}</p><p className="text-xs text-ink-500">{first.from_code} · {formatDay(o.departure)}</p></div>
            <div className="flex flex-1 items-center gap-1" aria-hidden><span className="h-2 w-2 rounded-full bg-brand-600" /><span className="h-0.5 flex-1 border-t-2 border-dotted border-brand-500" /><span className="h-2 w-2 rounded-full bg-brand-600" /></div>
            <div className="text-right"><p className="text-2xl font-extrabold text-ink-900">{formatTime(o.arrival)}</p><p className="text-xs text-ink-500">{last.to_code} · {formatDay(o.arrival)}</p></div>
          </div>
          {o.legs.length > 1 && (
            <ul className="mt-2 space-y-0.5 text-xs text-ink-700">
              {o.legs.map((l) => <li key={l.train_no}>{l.train_no}: {l.from_code} {formatTime(l.departure)} → {l.to_code} {formatTime(l.arrival)}</li>)}
            </ul>
          )}
        </section>

        <section className="grid grid-cols-2 gap-3">
          <div className="rounded-2xl bg-white p-3 shadow-card ring-1 ring-ink-100">
            <p className="text-xs text-ink-500">{m.details.fareFrom}</p>
            {rec.fare_per_passenger !== null ? (
              <p className="text-xl font-extrabold text-brand-900">{formatRupees(rec.fare_per_passenger)} <span className="text-[11px] font-normal text-ink-500">{m.options.perPassenger}</span></p>
            ) : <p className="text-sm font-semibold text-amber-700">{m.options.fareUnknown}</p>}
          </div>
          <div className="rounded-2xl bg-white p-3 shadow-card ring-1 ring-ink-100">
            <p className="text-xs text-ink-500">{m.details.classes}</p>
            <p className="mt-1 flex flex-wrap gap-1">
              {classes.length ? classes.map((c) => <span key={c} className="rounded-md bg-brand-50 px-1.5 py-0.5 text-xs font-semibold text-brand-700">{c}</span>)
                : <span className="text-sm font-semibold text-amber-700">{m.options.classesUnknown}</span>}
            </p>
          </div>
        </section>

        <section className="rounded-2xl bg-white p-4 shadow-card ring-1 ring-ink-100">
          <h2 className="text-sm font-bold text-brand-900">{m.details.requirements}</h2>
          <ul className="mt-2 space-y-1 text-sm">
            {rec.hard_constraints.map((c) => (
              <li key={c.name} className={`flex items-start gap-2 ${c.status === 'met' ? 'text-match-600' : c.status === 'unverified' ? 'text-amber-700' : 'text-red-700'}`}>
                {c.status === 'met' ? <CheckIcon size={16} className="mt-0.5" /> : <AlertIcon size={16} className="mt-0.5" />} {c.detail}
              </li>
            ))}
          </ul>
          {rec.unverified.map((u) => <p key={u} className="mt-2 rounded-lg bg-amber-50 px-2 py-1 text-xs text-amber-900">{u}</p>)}
        </section>

        <section className="rounded-2xl bg-white p-4 shadow-card ring-1 ring-ink-100">
          <h2 className="text-sm font-bold text-brand-900">{m.details.facilities}</h2>
          <p className="mt-1 flex items-start gap-2 text-xs text-ink-500"><InfoIcon size={16} className="shrink-0" /> {m.details.facilitiesUnknown}</p>
        </section>

        <section className="rounded-2xl bg-white p-4 shadow-card ring-1 ring-ink-100">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold text-brand-900">{m.details.passengerDetails}</h2>
            <button type="button" onClick={() => go('plan')} className="rounded-full bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-700">{m.fields.edit}</button>
          </div>
          <p className="mt-2 flex items-center gap-2 text-sm text-ink-900"><UsersIcon size={18} className="text-brand-600" /> {j.passenger_count ?? '?'} {j.passenger_count === 1 ? m.options.passenger : m.options.passengers}</p>
          <h3 className="mt-4 text-sm font-bold text-brand-900">{m.details.preferences}</h3>
          <ul className="mt-2 space-y-1.5">
            {prefs.map(({ Icon, text }) => <li key={text} className="flex items-center gap-2 text-sm text-ink-700"><Icon size={16} className="text-brand-600" /> {text}</li>)}
          </ul>
        </section>
        <SourceLine provenance={o.provenance} />
      </div>
    </Screen>
  )
}
