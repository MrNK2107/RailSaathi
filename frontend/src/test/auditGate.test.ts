import { advisories, evaluate } from '../../scripts/audit-gate.mjs'
import allowlistRaw from '../../audit-allowlist.json?raw'
import packageRaw from '../../package.json?raw'

type Entry = { id: string; packages: string[]; review_by: string }

const audit = (vulns: Record<string, { severity: string; via: unknown[] }>) => ({ vulnerabilities: vulns })
const advisory = (id: string, severity: string) => ({ source: 1, url: `https://github.com/advisories/${id}`, severity, title: `t-${id}` })

const AUDIT = audit({
  braces: { severity: 'high', via: [advisory('GHSA-aaaa', 'high')] },
  micromatch: { severity: 'high', via: ['braces'] },
  vitest: { severity: 'critical', via: [advisory('GHSA-bbbb', 'critical')] },
  postcss: { severity: 'moderate', via: [advisory('GHSA-cccc', 'moderate')] },
})
const allow = (id: string, review_by = '2099-01-01', packages = ['braces']): Entry => ({ id, packages, review_by })

describe('npm audit gate', () => {
  it('lists each advisory once per package and ignores inherited (string) entries', () => {
    expect(advisories(AUDIT).map((a: { id: string; pkg: string }) => `${a.id}:${a.pkg}`).sort())
      .toEqual(['GHSA-aaaa:braces', 'GHSA-bbbb:vitest', 'GHSA-cccc:postcss'])
  })

  it('blocks a high or critical advisory that is not allowlisted, never a moderate one', () => {
    const { blocking, accepted } = evaluate(AUDIT, [allow('GHSA-aaaa')], '2026-10-16')
    expect(blocking.map((a: { id: string }) => a.id)).toEqual(['GHSA-bbbb'])
    expect(accepted.map((a: { id: string }) => a.id)).toEqual(['GHSA-aaaa'])
  })

  it('blocks an allowlisted advisory once its review date has passed or in a package it was not accepted for', () => {
    expect(evaluate(AUDIT, [allow('GHSA-aaaa', '2026-10-15'), allow('GHSA-bbbb')], '2026-10-16').blocking
      .map((a: { id: string; reason: string }) => `${a.id} ${a.reason}`))
      .toEqual(['GHSA-aaaa allowlist entry expired 2026-10-15', 'GHSA-bbbb not allowlisted for vitest'])
  })

  it('reports allowlist entries npm no longer finds', () => {
    expect(evaluate(audit({}), [allow('GHSA-gone')], '2026-10-16')).toEqual({ blocking: [], accepted: [], stale: ['GHSA-gone'] })
  })

  it('the committed allowlist never covers a shipped dependency and every entry has a reason and a review date', () => {
    const file = JSON.parse(allowlistRaw)
    const pkg = JSON.parse(packageRaw)
    const shipped = new Set(Object.keys(pkg.dependencies))
    for (const entry of file.advisories) {
      expect(entry.id).toMatch(/^GHSA-/)
      expect(entry.reason.length).toBeGreaterThan(40)
      expect(entry.review_by).toMatch(/^\d{4}-\d{2}-\d{2}$/)
      for (const p of entry.packages) expect(shipped.has(p)).toBe(false)
    }
  })
})
