// Defence in depth: the backend already restricts links to official railway domains; the UI re-checks every one.
const OFFICIAL_DOMAINS = ['irctc.co.in', 'indianrail.gov.in', 'indianrailways.gov.in'] as const

/** Returns the normalised URL when it is https on an official domain (or subdomain) without credentials, else null. */
export function officialUrl(raw: unknown): string | null {
  if (typeof raw !== 'string' || raw.trim() !== raw || raw === '') return null
  let url: URL
  try {
    url = new URL(raw)
  } catch {
    return null
  }
  if (url.protocol !== 'https:' || url.username || url.password) return null
  if (url.port && url.port !== '443') return null
  const host = url.hostname.toLowerCase().replace(/\.$/, '')
  const ok = OFFICIAL_DOMAINS.some((d) => host === d || host.endsWith(`.${d}`))
  return ok ? url.href : null
}
