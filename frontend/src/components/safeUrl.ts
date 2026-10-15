/** Only https links from station data are rendered as links. */
export function isHttps(url: string | undefined | null): url is string {
  return typeof url === 'string' && url.startsWith('https://')
}

/** Digits (and a leading +) only, safe for a tel: href. */
export function telHref(number: string): string {
  return `tel:${number.replace(/[^0-9+]/g, '')}`
}
