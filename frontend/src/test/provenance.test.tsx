import { render, screen } from '@testing-library/react'
import { ProvenanceBadge } from '../components/ProvenanceBadge'
import type { Provenance } from '../api/types'

const base: Provenance = {
  mode: 'live', source: 'RailRadar live API (third-party)', as_of: '2026-10-10T15:21:00+05:30', note: 'Live third-party data.',
}

describe('ProvenanceBadge', () => {
  it.each([
    ['live', 'LIVE'], ['cached', 'CACHED'], ['stale', 'STALE'], ['demo', 'DEMO'], ['fallback', 'FALLBACK'], ['unknown', 'UNVERIFIED'],
  ] as const)('labels %s data', (mode, label) => {
    render(<ProvenanceBadge provenance={{ ...base, mode }} />)
    const badge = screen.getByTestId('provenance-badge')
    expect(badge).toHaveTextContent(label)
    expect(badge).toHaveAttribute('data-mode', mode)
    expect(badge).toHaveAttribute('title', expect.stringContaining('RailRadar live API'))
  })

  it('full variant shows source, retrieval time and note', () => {
    render(<ProvenanceBadge provenance={{ ...base, mode: 'stale', note: 'Quota exhausted; earlier response.' }} variant="full" />)
    const el = screen.getByTestId('provenance-badge')
    expect(el).toHaveTextContent('STALE')
    expect(el).toHaveTextContent('RailRadar live API (third-party)')
    expect(el).toHaveTextContent('10 Oct')
    expect(el).toHaveTextContent('Quota exhausted; earlier response.')
  })

  it('renders unavailable as an explicit empty state with the reason, never as data', () => {
    render(<ProvenanceBadge provenance={{ ...base, mode: 'unavailable', note: 'The live train data source is rate limited.' }} />)
    const empty = screen.getByRole('status')
    expect(empty).toHaveAttribute('data-mode', 'unavailable')
    expect(empty).toHaveTextContent('Data unavailable')
    expect(empty).toHaveTextContent('The live train data source is rate limited.')
  })

  it('treats missing provenance as unavailable and uses the given reason', () => {
    render(<ProvenanceBadge provenance={null} reason="Live data is not configured." />)
    expect(screen.getByRole('status')).toHaveTextContent('Live data is not configured.')
  })

  it('accepts localised labels', () => {
    render(<ProvenanceBadge provenance={base} labels={{ live: 'LIVE · RailRadar' }} />)
    expect(screen.getByText('LIVE · RailRadar')).toBeInTheDocument()
  })

  it('renders a mode-only chip (health, saved trips) and treats an unrecognised mode as unverified', () => {
    const { rerender } = render(<ProvenanceBadge provenance={null} mode="demo" />)
    expect(screen.getByTestId('provenance-badge')).toHaveAttribute('data-mode', 'demo')
    expect(screen.getByText('DEMO')).toBeInTheDocument()
    rerender(<ProvenanceBadge provenance={null} mode="something-old" />)
    expect(screen.getByTestId('provenance-badge')).toHaveAttribute('data-mode', 'unknown')
  })
})
