import { useState } from 'react'
import { formatDate, formatDuration, formatRupees } from '../../utils/format'
import { ArrowLeft, ArrowRight, CheckIcon, ClockIcon, CompassIcon, EditIcon, InfoIcon, LiveIcon, RupeeIcon, SaveIcon, SeatIcon, TrainIcon } from '../icons'
import { useApp } from '../PlannerContext'
import { saveTrip } from '../trips'
import { ErrorBanner, PrimaryButton, Screen, SecondaryButton, SourceLine, selectedRecommendation } from '../ui'

export default function Confirmation() {
  const { planner, go, back, m } = useApp()
  const state = planner.state
  const conf = state?.confirmation ?? null
  const rec = selectedRecommendation(state)
  const [saved, setSaved] = useState(false)

  if (!state || !conf || !rec) {
    return (
      <Screen nav>
        <div className="p-4">
          <p className="rounded-2xl bg-brand-50 p-4 text-sm text-brand-900">{m.confirmation.notConfirmed}</p>
          <div className="mt-3"><PrimaryButton onClick={() => go('plan')}>{m.dashboard.planTitle}</PrimaryButton></div>
        </div>
      </Screen>
    )
  }

  const o = rec.option
  const j = state.journey
  const first = o.legs[0]
  const last = o.legs[o.legs.length - 1]

  const onSave = () => {
    setSaved(saveTrip({
      confirmationId: conf.confirmation_id, savedAt: new Date().toISOString(),
      trainNo: o.legs.map((l) => l.train_no).join(' + '), trainName: o.legs.map((l) => l.train_name).join(' → '),
      fromLabel: `${first.from_name} (${first.from_code})`, toLabel: `${last.to_name} (${last.to_code})`,
      journeyDate: j.journey_date, departure: o.departure, arrival: o.arrival, passengers: j.passenger_count,
      dataMode: o.provenance.mode, handoff: conf.handoff,
    }))
  }

  const checkStatus = async () => {
    const ok = await planner.reassess(null)
    if (ok) go('options') // reassessment returns re-ranked options for the passenger to review
  }

  // A 409 "no_relevant_event" from /reassess means nothing is reported; show it as a status, not an error.
  const noDelays = planner.error && /No (delays|simulated disruption)/i.test(planner.error)

  return (
    <Screen nav>
      <div className="px-4 pt-3">
        <button type="button" onClick={back} aria-label={m.back} className="rounded-full p-1.5 text-brand-900 hover:bg-ink-100"><ArrowLeft size={22} /></button>
      </div>
      <section className="px-6 pt-2 text-center">
        <span className="mx-auto grid h-20 w-20 place-items-center rounded-full bg-match-600 text-white ring-8 ring-match-50"><CheckIcon size={40} /></span>
        <h1 className="mt-4 text-2xl font-extrabold text-brand-900">{m.confirmation.ready}</h1>
        <p className="mt-1 text-sm text-ink-500">{m.confirmation.readyBody}</p>
        <p className="mt-1 text-[11px] text-ink-500">{m.confirmation.ref} {conf.confirmation_id}</p>
      </section>

      <div className="space-y-3 p-4">
        <section className="rounded-2xl bg-white p-4 shadow-card ring-1 ring-ink-100">
          <div className="flex items-start gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand-50 text-brand-600"><TrainIcon size={22} /></span>
            <div>
              <p className="font-bold text-brand-900">{o.legs.map((l) => `${l.train_no} - ${l.train_name}`).join(' → ')}</p>
              <p className="text-xs text-ink-500">{first.from_name} ({first.from_code}) → {last.to_name} ({last.to_code})</p>
              <p className="text-xs text-ink-500">{j.journey_date ? formatDate(j.journey_date) : ''} · {j.passenger_count} {j.passenger_count === 1 ? m.options.passenger : m.options.passengers}</p>
            </div>
          </div>
          <dl className="mt-3 divide-y divide-ink-100 text-sm">
            <Row Icon={SeatIcon} label={m.confirmation.selectedClass} value={rec.selected_class ?? m.options.classesUnknown} />
            <Row Icon={RupeeIcon} label={m.confirmation.totalFare} value={rec.total_fare !== null ? formatRupees(rec.total_fare) : m.options.fareUnknown} />
            <Row Icon={ClockIcon} label={m.confirmation.journeyTime} value={formatDuration(o.duration_minutes)} />
          </dl>
          <button type="button" onClick={checkStatus} disabled={planner.loading}
            className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-brand-50 px-3 py-1.5 text-xs font-semibold text-brand-700 disabled:opacity-60">
            <LiveIcon size={14} /> {m.confirmation.checkStatus}
          </button>
          {noDelays ? <p role="status" className="mt-2 text-xs font-semibold text-match-600">{m.confirmation.noDelays}</p> : null}
        </section>

        {!noDelays && <ErrorBanner />}

        <p className="flex items-center gap-2 rounded-2xl bg-brand-50 p-3 text-sm font-semibold text-brand-900">
          <InfoIcon size={20} className="shrink-0 text-brand-600" /> {m.confirmation.planOnly}
        </p>

        <PrimaryButton onClick={() => go('navigation')}>{m.confirmation.toStationGuide} <ArrowRight size={20} /></PrimaryButton>
        <SecondaryButton onClick={() => go('tour')}><CompassIcon size={18} /> {m.confirmation.exploreStation}</SecondaryButton>
        <SecondaryButton onClick={onSave} disabled={saved}><SaveIcon size={18} /> {saved ? m.confirmation.saved : m.confirmation.save}</SecondaryButton>
        <SecondaryButton onClick={() => go('plan')}><EditIcon size={18} /> {m.confirmation.modify}</SecondaryButton>

        <details className="rounded-2xl bg-white p-3 text-xs shadow-card ring-1 ring-ink-100">
          <summary className="cursor-pointer font-semibold text-ink-700">{m.confirmation.handoff}</summary>
          <pre className="mt-2 max-h-72 overflow-auto rounded-lg bg-ink-100 p-2 text-[10px] text-ink-900">{JSON.stringify(conf.handoff, null, 2)}</pre>
        </details>
        <SourceLine provenance={o.provenance} />
      </div>
    </Screen>
  )
}

function Row({ Icon, label, value }: { Icon: typeof ClockIcon; label: string; value: string }) {
  return (
    <div className="flex items-center gap-2 py-2">
      <Icon size={16} className="text-brand-600" />
      <dt className="flex-1 text-ink-500">{label}</dt>
      <dd className="font-semibold text-ink-900">{value}</dd>
    </div>
  )
}

