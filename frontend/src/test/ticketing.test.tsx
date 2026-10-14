import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import { ApiError, createApiClient, type ApiClient } from '../api/client'
import type { TicketingResponse } from '../api/types'
import { officialUrl } from '../utils/officialLinks'
import { response } from './fixtures'

const base: TicketingResponse = {
  conversation_id: 'conv_abcdef123456', session_token: 'tok', status: 'answered',
  answer: 'RAC passengers get a seat.\nWL tickets may stay unconfirmed.', provenance: { mode: 'live', source: 'gemini-2.5-flash grounded on the RailSaathi knowledge base', as_of: '2026-10-10T10:00:00+05:30', note: 'AI guidance, not official. Verify current rules on the cited official pages before acting.' }, evidence_sufficient: true, trace_id: 't',
  sources: [{ source_id: 's1', title: 'Refund rules', url: 'https://www.indianrail.gov.in/refund', publisher: 'IR',
    last_verified_at: '2026-10-01T00:00:00Z', as_of: '2026-10-01T00:00:00Z' }],
}

function client(ticketing: ApiClient['ticketing']): ApiClient {
  return {
    baseUrl: 'http://test',
    health: vi.fn().mockResolvedValue({ status: 'ok', api_version: '1', data_mode: 'demo', data_provider: { requested: 'demo', active: 'demo', reason: null }, ai: {} }),
    reference: vi.fn().mockResolvedValue({ places: [], classes: [], passenger_needs: [], budget_priorities: [], transfer_preferences: [], disruption_events: [], data_notice: '' }),
    createSession: vi.fn().mockResolvedValue(response({}, 'Hello')),
    ticketing,
  } as unknown as ApiClient
}

async function open(ticketing: ApiClient['ticketing']) {
  window.location.hash = '/home'
  const user = userEvent.setup()
  const c = client(ticketing)
  render(<App client={c} />)
  await waitFor(() => expect(c.createSession).toHaveBeenCalled())
  await user.click(await screen.findByRole('button', { name: 'Ticketing Guidance' }))
  await screen.findByText('Ticketing guidance')
  return { user, c }
}

async function ask(user: ReturnType<typeof userEvent.setup>, q = 'What is RAC?') {
  await user.type(screen.getByLabelText('Your ticketing question'), q)
  await user.click(screen.getByRole('button', { name: 'Ask' }))
}

// Copied from a real backend response (POST /api/chat via the backend test client, rule-based agent).
const realFallback = {
  status: 'answered',
  provenance: { mode: 'fallback', source: 'RailSaathi rule-based guidance over the curated knowledge base', as_of: '2026-10-10T10:00:00+05:30', note: 'Rule-based guidance (the AI model is not configured). AI guidance, not official. Verify current rules on the cited official pages before acting.' },
  sources: [{ source_id: 'src-ir-pnr-enquiry', title: 'Indian Railways Passenger Reservation Enquiry: PNR status', url: 'https://www.indianrail.gov.in/enquiry/PNR/PnrEnquiry.html?locale=en', publisher: 'Indian Railways (CRIS)', last_verified_at: '2026-10-14', as_of: '2026-10-14' }],
}

describe('Ticketing guidance screen', () => {
  it('shows the notice, answer, citation link with as_of, and provenance, and reuses the conversation id', async () => {
    const ticketing = vi.fn().mockResolvedValue(base)
    const { user } = await open(ticketing)
    expect(screen.getByTestId('ticketing-notice')).toHaveTextContent('AI guidance, not official')
    await ask(user)
    expect(await screen.findByTestId('ticketing-answer')).toHaveTextContent('RAC passengers get a seat.')
    const link = screen.getByRole('link', { name: 'Refund rules' })
    expect(link).toHaveAttribute('href', 'https://www.indianrail.gov.in/refund')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    expect(screen.getByText(/as of 2026-10-01/)).toBeInTheDocument()
    expect(screen.getByTestId('provenance-badge')).toHaveAttribute('data-mode', 'live')
    expect(screen.getByTestId('provenance-badge')).toHaveTextContent('LIVE')
    expect(ticketing).toHaveBeenCalledWith({ message: 'What is RAC?' })
    await ask(user, 'And WL?')
    await waitFor(() => expect(ticketing).toHaveBeenCalledTimes(2))
    expect(ticketing).toHaveBeenLastCalledWith({ message: 'And WL?', conversation_id: 'conv_abcdef123456' })
  })

  it('renders a real backend fallback response with a FALLBACK badge', async () => {
    const { user } = await open(vi.fn().mockResolvedValue({ ...base, ...realFallback }))
    await ask(user)
    await screen.findByTestId('ticketing-answer')
    const badge = screen.getByTestId('provenance-badge')
    expect(badge).toHaveAttribute('data-mode', 'fallback')
    expect(badge).toHaveTextContent('FALLBACK')
    expect(badge).toHaveTextContent('Rule-based guidance')
  })

  it('renders the unavailable state with official links only', async () => {
    const ticketing = vi.fn().mockResolvedValue({
      ...base, status: 'unavailable', provenance: { mode: 'unavailable', source: 'RailSaathi ticketing guidance', as_of: '2026-10-10T10:00:00+05:30', note: 'The AI guidance service could not answer; use the official links.' }, answer: 'AI ticketing guidance is unavailable right now.',
      message: 'guidance unavailable', sources: [],
      links: [
        { title: 'IRCTC e-ticketing', url: 'https://www.irctc.co.in/nget/train-search' },
        { title: 'Evil site', url: 'https://irctc.co.in.evil.com/x' },
      ],
    })
    const { user } = await open(ticketing)
    await ask(user)
    const box = await screen.findByTestId('ticketing-unavailable')
    expect(box).toHaveTextContent('Guidance unavailable')
    expect(box).toHaveTextContent('The AI guidance service could not answer; use the official links.')
    expect(screen.getByTestId('provenance-badge')).toHaveAttribute('data-mode', 'unavailable')
    expect(screen.getByRole('link', { name: /IRCTC e-ticketing/ })).toHaveAttribute('href', 'https://www.irctc.co.in/nget/train-search')
    expect(screen.queryByText(/Evil site/)).toBeNull()
  })

  it('shows the error envelope message', async () => {
    const ticketing = vi.fn().mockRejectedValue(new ApiError(429, 'rate_limited', 'Too many requests, slow down.'))
    const { user } = await open(ticketing)
    await ask(user)
    expect(await screen.findByRole('alert')).toHaveTextContent('Too many requests, slow down.')
  })

  it('never renders non-allowlisted links or HTML from the answer as live elements', async () => {
    const ticketing = vi.fn().mockResolvedValue({
      ...base,
      answer: 'See [x](https://evil.example/a) <img src=x onerror="alert(1)"> <a href="https://evil.example">go</a> <script>1</script>',
      sources: [
        base.sources[0],
        { ...base.sources[0], source_id: 'bad', title: 'Bad source', url: 'https://evil.example/p' },
        { ...base.sources[0], source_id: 'js', title: 'JS source', url: 'javascript:alert(1)' },
        { ...base.sources[0], source_id: 'http', title: 'Http source', url: 'http://www.irctc.co.in/x' },
      ],
    })
    const { user } = await open(ticketing)
    await ask(user)
    const answer = await screen.findByTestId('ticketing-answer')
    expect(answer.querySelector('img, a, script')).toBeNull()
    expect(answer).toHaveTextContent('<img src=x onerror="alert(1)">')
    expect(document.querySelector('img[src="x"]')).toBeNull()
    const hrefs = screen.getAllByRole('link').map((a) => a.getAttribute('href'))
    expect(hrefs).toEqual(['https://www.indianrail.gov.in/refund'])
    expect(screen.getByText('Bad source')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Bad source' })).toBeNull()
  })
})

describe('officialUrl', () => {
  it.each([
    ['https://www.irctc.co.in/nget', true],
    ['https://irctc.co.in', true],
    ['https://enquiry.indianrail.gov.in/x', true],
    ['https://indianrailways.gov.in', true],
    ['HTTPS://IRCTC.CO.IN', true],
    ['https://evil.com/?irctc.co.in', false],
    ['https://irctc.co.in@evil.com', false],
    ['https://irctc.co.in.evil.com/', false],
    ['http://irctc.co.in', false],
    ['https://evilirctc.co.in', false],
    ['https://irctc.co.in.evil.com', false],
    ['https://user:pw@irctc.co.in', false],
    ['https://irctc.co.in:8443/', false],
    ['javascript:alert(1)', false],
    ['//irctc.co.in', false],
    [' https://irctc.co.in', false],
    ['', false],
  ])('%s -> %s', (u, ok) => {
    expect(officialUrl(u) !== null).toBe(ok)
  })
  it('rejects non-strings', () => expect(officialUrl(undefined)).toBeNull())
})

describe('ApiClient.ticketing', () => {
  it('POSTs /api/chat with the body', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(JSON.stringify(base), { status: 200 }))
    const c = createApiClient({ baseUrl: 'http://t', fetchImpl })
    expect((await c.ticketing({ message: 'hi' })).conversation_id).toBe(base.conversation_id)
    const [url, init] = fetchImpl.mock.calls[0]
    expect(url).toBe('http://t/api/chat')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ message: 'hi' })
  })
})
