import { render, screen } from '@testing-library/react'
import { ProvenanceBadge } from '../components/ProvenanceBadge'
import type { Provenance } from '../api/types'

const base: Provenance = {
  mode: 'live', source: 'RailRadar live API (third-party)', as_of: '2026-10-10T15:21:00+05:30', note: 'Live third-party data.',
}

describe('ProvenanceBadge', () => {
  it.each([
    ['live', 'LIVE'], ['cached', 'CACHED'], ['stale', 'STALE'], ['fallback', 'FALLBACK'], ['unknown', 'UNVERIFIED'],
  ] as const)('labels %s data', (mode, label) => {
    render(<ProvenanceBadge provenance={{ ...base, mode }} />)
    const badge = screen.getByTestId('provenance-badge')
    expect(badge).toHaveTextContent(label)
    expect(badge).toHaveAttribute('data-mode', mode)
    expect(badge).toHaveAttribute('title', expect.stringContaining('RailRadar live API'))
  })

  it('chip can name its source next to the label', () => {
    render(<ProvenanceBadge provenance={{ ...base, source: 'NTES (unofficial client)' }} showSource />)
    expect(screen.getByTestId('provenance-badge')).toHaveTextContent('LIVE')
    expect(screen.getByTestId('provenance-source')).toHaveTextContent('NTES (unofficial client)')
  })

  it('chip hides the source unless asked', () => {
    render(<ProvenanceBadge provenance={base} />)
    expect(screen.queryByTestId('provenance-source')).not.toBeInTheDocument()
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

  it('renders nothing for demo data (local/dev only, unlabelled in the UI), in every variant', () => {
    const { container, rerender } = render(<ProvenanceBadge provenance={{ ...base, mode: 'demo' }} />)
    expect(container).toBeEmptyDOMElement()
    rerender(<ProvenanceBadge provenance={{ ...base, mode: 'demo' }} variant="full" />)
    expect(container).toBeEmptyDOMElement()
    rerender(<ProvenanceBadge provenance={null} mode="demo" />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders a mode-only chip (health, saved trips) and treats an unrecognised mode as unverified', () => {
    const { rerender } = render(<ProvenanceBadge provenance={null} mode="cached" />)
    expect(screen.getByTestId('provenance-badge')).toHaveAttribute('data-mode', 'cached')
    expect(screen.getByText('CACHED')).toBeInTheDocument()
    rerender(<ProvenanceBadge provenance={null} mode="something-old" />)
    expect(screen.getByTestId('provenance-badge')).toHaveAttribute('data-mode', 'unknown')
  })
})

describe('noteText and sourceName', () => {
  it('render coded notes with params, and fall back to the English note', async () => {
    const { noteText, sourceName } = await import('../components/ProvenanceBadge')
    const { MOBILE_STRINGS } = await import('../mobile/strings')
    const ta = MOBILE_STRINGS.ta
    const p = { note: 'PARTIAL: ... MS to SBC', note_codes: ['ntes_partial', 'ntes'], note_params: { missed: 'MS→SBC' } }
    expect(noteText(p, ta)).toContain('பகுதி:')
    expect(noteText(p, ta)).toContain('MS→SBC')
    expect(noteText(p, ta)).not.toContain('unofficial')
    expect(noteText(p)).toBe(p.note)  // outside the app: English
    expect(noteText({ note: 'x', note_codes: [] }, ta)).toBe('x')
    expect(sourceName('NTES (unofficial client)', ta)).toBe('NTES (அதிகாரப்பூர்வமற்ற கிளையன்ட்)')
    expect(sourceName('NTES (unofficial client)', MOBILE_STRINGS.en)).toBe('NTES (unofficial client)')
    expect(sourceName('Other feed', ta)).toBe('Other feed')
  })
})
