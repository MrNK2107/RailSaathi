// Helplines are real tap-to-call links from config.ts. Nearby facilities are a labelled placeholder.
import { useState } from 'react'
import { EMERGENCY_NUMBER, FACILITY_TILES, HELPLINES, RAIL_MADAD_URL } from '../config'
import {
  AccessibleIcon, AtmIcon, BagIcon, ChevronRight, DocIcon, FoodIcon, HelpIcon, InfoIcon, LoungeIcon, MedicalIcon,
  PhoneIcon, PlugIcon, ShieldIcon, ToiletIcon, WaterIcon,
} from '../icons'
import { useApp } from '../PlannerContext'
import { AppHeader, Screen } from '../ui'
import EmergencyHelpModal from '../../components/EmergencyHelpModal'

const LINE_ICONS = { police: ShieldIcon, medical: MedicalIcon, enquiry: InfoIcon, lostFound: BagIcon, divyangjan: AccessibleIcon }
const TONES = { blue: 'bg-brand-50 text-brand-600', red: 'bg-red-50 text-red-600', navy: 'bg-ink-100 text-brand-900', amber: 'bg-amber-50 text-amber-600' }
const TILE_ICONS = { toilets: ToiletIcon, water: WaterIcon, food: FoodIcon, lounge: LoungeIcon, charging: PlugIcon, atm: AtmIcon }

export default function HelpAssistance() {
  const { m } = useApp()
  const [sosModalOpen, setSosModalOpen] = useState(false)

  return (
    <Screen>
      <AppHeader />
      <div className="space-y-4 p-4">
        <h1 className="text-2xl font-extrabold text-brand-900">{m.help.title}</h1>

        <section className="flex items-center gap-3 rounded-2xl bg-red-50 p-4 ring-1 ring-red-100">
          <span className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-red-600 text-white"><PhoneIcon size={24} /></span>
          <div className="flex-1">
            <p className="font-bold text-red-700">{m.help.urgent}</p>
            <p className="text-xs text-red-700/80">{m.help.urgentSub}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              <a href={`tel:${EMERGENCY_NUMBER}`} className="inline-block rounded-xl bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700">
                {m.help.call} {EMERGENCY_NUMBER} ({m.help.helpline})
              </a>
              <button
                type="button"
                onClick={() => setSosModalOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-xl border border-red-300 bg-white px-3 py-2 text-xs font-bold text-red-700 shadow-sm hover:bg-red-50"
              >
                <ShieldIcon size={16} /> 24×7 Station SOS & Medical
              </button>
            </div>
          </div>
        </section>

        <ul className="divide-y divide-ink-100 rounded-2xl bg-white shadow-card ring-1 ring-ink-100">
          {HELPLINES.map((line) => {
            const Icon = LINE_ICONS[line.id]
            return (
              <li key={line.id}>
                <a href={`tel:${line.number}`} className="flex items-center gap-3 px-4 py-3 hover:bg-brand-50">
                  <span className={`grid h-10 w-10 place-items-center rounded-xl ${TONES[line.tone]}`}><Icon size={22} /></span>
                  <span className="flex-1">
                    <span className="block text-sm font-semibold text-ink-900">{m.help.lines[line.id]}</span>
                    <span className="block text-xs text-ink-500">{m.help.call} {line.number}</span>
                  </span>
                  <ChevronRight size={18} className="text-ink-500" />
                </a>
              </li>
            )
          })}
          <li>
            <a href={RAIL_MADAD_URL} target="_blank" rel="noopener noreferrer" className="flex items-center gap-3 px-4 py-3 hover:bg-brand-50">
              <span className="grid h-10 w-10 place-items-center rounded-xl bg-fuchsia-50 text-fuchsia-600"><DocIcon size={22} /></span>
              <span className="flex-1">
                <span className="block text-sm font-semibold text-ink-900">{m.help.report}</span>
                <span className="block text-xs text-ink-500">{m.help.reportSub} ↗</span>
              </span>
              <ChevronRight size={18} className="text-ink-500" />
            </a>
          </li>
        </ul>

        <p className="flex items-start gap-2 rounded-xl bg-brand-50 p-3 text-xs text-brand-900">
          <HelpIcon size={16} className="mt-0.5 shrink-0" /> {m.help.disclaimer}
        </p>

        <section aria-labelledby="nearby-title">
          <div className="flex items-center justify-between">
            <h2 id="nearby-title" className="text-base font-bold text-brand-900">{m.help.nearby}</h2>
            <button type="button" disabled className="rounded-full bg-ink-100 px-3 py-1 text-xs text-ink-500">{m.help.viewOnMap}</button>
          </div>
          <p role="note" className="mt-1 text-xs font-medium text-amber-800">{m.help.nearbyPreview}</p>
          <ul className="mt-2 grid grid-cols-3 gap-3">
            {FACILITY_TILES.map((tile) => {
              const Icon = TILE_ICONS[tile]
              return (
                <li key={tile} className="flex flex-col items-center gap-1 rounded-2xl bg-white p-3 text-center text-xs text-ink-500 shadow-card ring-1 ring-ink-100">
                  <Icon size={24} className="text-brand-500 opacity-70" /> {m.help.tiles[tile]}
                </li>
              )
            })}
          </ul>
        </section>
      </div>

      <EmergencyHelpModal
        isOpen={sosModalOpen}
        onClose={() => setSosModalOpen(false)}
        stationCode="MAS"
      />
    </Screen>
  )
}
