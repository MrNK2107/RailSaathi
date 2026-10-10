import { render, screen } from '@testing-library/react'
import { JourneyCard } from '../components/JourneyCard'
import { DemoBanner } from '../components/Header'
import { STRINGS } from '../i18n/strings'
import type { Recommendation } from '../api/types'
import { rec } from './fixtures'

const liveRec: Recommendation = {
  ...rec,
  labels: ['fastest'],
  explanation: 'Recommended because it is the quickest eligible journey (7 h 45 min).',
  preference_matches: [],
  selected_class: null,
  fare_per_passenger: null,
  total_fare: null,
  option: {
    ...rec.option,
    fares: {},
    classes: ['2S', 'CC'],
    provenance: { ...rec.option.provenance, mode: 'live', source: 'RailRadar live API (third-party)' },
  },
}

describe('live RailRadar data', () => {
  it('shows "Fare not available" and the live badge instead of a made-up price', () => {
    render(<JourneyCard t={STRINGS.en} rec={liveRec} passengers={2} selected={false} disabled={false} onSelect={vi.fn()} />)
    expect(screen.getByText('Fare not available')).toBeInTheDocument()
    expect(screen.getByText('LIVE · RailRadar')).toBeInTheDocument()
    expect(screen.getByText('2S · CC')).toBeInTheDocument()
    expect(screen.queryByText(/₹/)).not.toBeInTheDocument()
  })

  it('uses the live banner text', () => {
    render(<DemoBanner text={STRINGS.en.liveBanner} live />)
    expect(screen.getByRole('note')).toHaveTextContent('LIVE DATA from RailRadar')
  })
})

describe('live provenance', () => {
  it('shows source and retrieval time on a live card', () => {
    const asOf = { ...liveRec, option: { ...liveRec.option, provenance: { ...liveRec.option.provenance, as_of: '2026-10-10T10:00:00+05:30' } } }
    render(<JourneyCard t={STRINGS.en} rec={asOf} passengers={1} selected={false} disabled={false} onSelect={vi.fn()} />)
    expect(screen.getByText(/RailRadar live API \(third-party\) · retrieved 10:00 IST/)).toBeInTheDocument()
  })
})
