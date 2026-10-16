// Pins the parts of nginx/default.conf.template that the PWA and the bundle budgets depend on. `nginx -t` on the built
// image checks the syntax; these check the intent, in CI, without Docker.
import conf from '../../nginx/default.conf.template?raw'
import budget from '../../scripts/check-budget.mjs?raw'

/** The body of `location <match> { ... }` (locations in this file do not nest). */
function location(match: string): string {
  const start = conf.indexOf(`location ${match} {`)
  if (start < 0) throw new Error(`no location ${match}`)
  return conf.slice(start, conf.indexOf('\n    }', start))
}

describe('nginx site config', () => {
  it('revalidates the service worker, the manifest and the shell on every load, so a deploy replaces them', () => {
    for (const match of ['= /sw.js', '= /manifest.webmanifest', '= /', '= /index.html']) {
      expect(location(match), match).toContain('add_header Cache-Control "no-cache" always;')
    }
    expect(location('= /manifest.webmanifest')).toContain('default_type application/manifest+json;')
  })

  it('serves hashed assets as immutable and never caches the API', () => {
    expect(location('/assets/')).toContain('max-age=31536000, immutable')
    expect(location('~ ^/api(/|$)')).not.toContain('Cache-Control')
  })

  it('repeats the security headers in every location (add_header is not inherited once a location sets its own)', () => {
    for (const match of ['~ ^/api(/|$)', '/assets/', '= /', '= /index.html', '= /sw.js', '= /manifest.webmanifest', '/']) {
      expect(location(match), match).toContain('include /etc/nginx/snippets/security-headers.conf;')
    }
  })

  it('compresses at the gzip level the bundle budgets are measured at', () => {
    expect(conf).toMatch(/^\s*gzip_comp_level 6;$/m)
    expect(budget).toContain('{ level: 6 }')
  })
})
