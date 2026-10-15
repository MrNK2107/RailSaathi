// The security headers are plain nginx config, so nothing else exercises them in CI. These checks pin the properties
// the app depends on: Street View (Google Maps JS) and the AR camera keep working, nothing weakens script execution,
// and the file stays valid (one header per directive, no newline inside the CSP value).
import conf from '../../nginx/security-headers.conf?raw'

const directives = conf.split('\n').filter((l) => l.startsWith('add_header '))

function header(name: string): string {
  const line = directives.find((l) => l.startsWith(`add_header ${name} `))
  if (!line) throw new Error(`no ${name} header`)
  const m = /^add_header \S+ "(.*)" always;$/.exec(line)
  if (!m) throw new Error(`${name} header is not a single quoted value ending in "always;"`)
  return m[1]
}

function csp(): Record<string, string[]> {
  const out: Record<string, string[]> = {}
  for (const part of header('Content-Security-Policy').split(';')) {
    const [name, ...values] = part.trim().split(/\s+/)
    if (name) out[name] = values
  }
  return out
}

describe('nginx security headers', () => {
  it('sends every header on error responses too, once each', () => {
    for (const name of ['Content-Security-Policy', 'X-Content-Type-Options', 'X-Frame-Options', 'Referrer-Policy', 'Permissions-Policy', 'Strict-Transport-Security']) {
      expect(directives.filter((l) => l.startsWith(`add_header ${name} `)), name).toHaveLength(1)
      header(name)
    }
  })

  it('does not allow eval or inline script, and never a wildcard script source', () => {
    const script = csp()['script-src']
    expect(script).toContain("'self'")
    expect(script).not.toContain("'unsafe-eval'")
    expect(script).not.toContain("'unsafe-inline'")
    expect(script).not.toContain('*')
    expect(script).not.toContain('https:')
    expect(script).not.toContain('data:')
  })

  it('lets Google Maps JS (Street View) load scripts, tiles, imagery and data', () => {
    const c = csp()
    expect(c['script-src']).toEqual(expect.arrayContaining(['https://maps.googleapis.com', 'https://*.googleapis.com', 'https://*.gstatic.com']))
    expect(c['img-src']).toEqual(expect.arrayContaining(['https://*.googleapis.com', 'https://*.gstatic.com', 'https://*.google.com']))
    expect(c['connect-src']).toEqual(expect.arrayContaining(['https://*.googleapis.com', 'https://*.gstatic.com']))
    expect(c['frame-src']).toContain('https://*.google.com')
    expect(c['worker-src']).toContain('blob:')
  })

  it('keeps the station map, canvas textures and camera preview working', () => {
    const c = csp()
    expect(c['default-src']).toEqual(["'self'"]) // /api/stations/{id}/map is same-origin
    expect(c['img-src']).toEqual(expect.arrayContaining(["'self'", 'data:', 'blob:']))
    expect(c['connect-src']).toEqual(expect.arrayContaining(["'self'", 'data:', 'blob:']))
    expect(c['media-src']).toContain('blob:')
    expect(c['style-src']).toContain('https://fonts.googleapis.com')
    expect(c['font-src']).toContain('https://fonts.gstatic.com')
  })

  it('forbids embedding, plugins and base-tag injection', () => {
    const c = csp()
    expect(c['frame-ancestors']).toEqual(["'none'"])
    expect(c['object-src']).toEqual(["'none'"])
    expect(c['base-uri']).toEqual(["'self'"])
    expect(c['form-action']).toEqual(["'self'"])
    expect(header('X-Frame-Options')).toBe('DENY')
  })

  it('allows camera and motion sensors for the app itself and for nobody else', () => {
    const policy = Object.fromEntries(header('Permissions-Policy').split(',').map((p) => p.trim().split('=')))
    for (const feature of ['camera', 'microphone', 'geolocation', 'gyroscope', 'accelerometer', 'xr-spatial-tracking']) {
      expect(policy[feature], feature).toBe('(self)')
    }
  })

  it('sets HSTS for a year including subdomains', () => {
    expect(header('Strict-Transport-Security')).toMatch(/^max-age=31536000; includeSubDomains$/)
  })

  it('has no newline inside any quoted header value', () => {
    for (const line of directives) expect(line.endsWith(';'), line.slice(0, 40)).toBe(true)
  })
})
