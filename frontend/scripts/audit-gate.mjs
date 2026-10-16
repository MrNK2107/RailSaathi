// Dependency audit gate for the whole npm tree (dependencies and devDependencies).
//
// Runs `npm audit --json` and fails (exit 1) on any high or critical advisory that is not listed in
// audit-allowlist.json. Every allowlist entry names one advisory (GHSA id), the packages it was accepted for, why it
// does not reach users, and a review-by date; an entry past its date fails the gate too, so exceptions cannot linger
// unreviewed. Entries that npm no longer reports are printed so they can be removed.
//
// The shipped bundle is gated separately and strictly in CI with `npm audit --omit=dev --audit-level=high` (no
// exceptions). Usage: node scripts/audit-gate.mjs [--json-file audit.json]   (the file option is for tests)
import { execSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const BLOCKING = new Set(['high', 'critical'])

function readAudit(argv) {
  const at = argv.indexOf('--json-file')
  if (at >= 0) return JSON.parse(readFileSync(argv[at + 1], 'utf8'))
  try {
    // A fixed command string (no interpolated input), so running it through the shell is safe on every platform.
    return JSON.parse(execSync('npm audit --json', { cwd: ROOT, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] }))
  } catch (err) {
    // npm audit exits non-zero when it finds anything; its JSON is still on stdout.
    if (err.stdout) return JSON.parse(err.stdout)
    throw err
  }
}

/** Every advisory npm reports, once per (advisory, package): {id, pkg, severity, title, url}. */
export function advisories(audit) {
  const out = new Map()
  for (const [pkg, vuln] of Object.entries(audit.vulnerabilities ?? {})) {
    for (const via of vuln.via ?? []) {
      if (typeof via !== 'object' || !via) continue // a string names the dependency it inherits from
      const id = String(via.url ?? '').split('/').pop() || String(via.source)
      out.set(`${id}:${pkg}`, { id, pkg, severity: via.severity, title: via.title, url: via.url })
    }
  }
  return [...out.values()]
}

/** npm prints an error object instead of a report when the audit itself fails (registry down, no lockfile, ...). */
function auditFailure(audit) {
  if (!audit || typeof audit !== 'object') return 'npm audit returned no JSON report'
  if (audit.error) return `npm audit failed: ${audit.error.summary ?? audit.error.code ?? 'unknown error'}`
  if (!audit.vulnerabilities || typeof audit.vulnerabilities !== 'object') return 'npm audit report has no vulnerabilities section'
  return null
}

export function evaluate(audit, allowlist, today = new Date().toISOString().slice(0, 10)) {
  // Fail closed: a report that could not be produced is never read as "no advisories".
  const failure = auditFailure(audit)
  if (failure) {
    return { blocking: [{ id: 'npm-audit', pkg: '(all)', severity: 'critical', title: failure, reason: 'audit did not run' }],
      accepted: [], stale: [] }
  }
  const entries = new Map(allowlist.map((e) => [e.id, e]))
  const blocking = []
  const accepted = []
  const seen = new Set()
  for (const adv of advisories(audit)) {
    if (!BLOCKING.has(adv.severity)) continue
    const entry = entries.get(adv.id)
    if (entry && entry.packages.includes(adv.pkg) && entry.review_by >= today) {
      accepted.push(adv)
      seen.add(adv.id)
    } else {
      blocking.push({ ...adv, reason: !entry ? 'not allowlisted' : entry.review_by < today ? `allowlist entry expired ${entry.review_by}` : `not allowlisted for ${adv.pkg}` })
    }
  }
  const stale = allowlist.filter((e) => !seen.has(e.id)).map((e) => e.id)
  return { blocking, accepted, stale }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const allowlist = JSON.parse(readFileSync(join(ROOT, 'audit-allowlist.json'), 'utf8')).advisories
  const { blocking, accepted, stale } = evaluate(readAudit(process.argv), allowlist)
  for (const a of accepted) console.log(`accepted ${a.severity} ${a.id} in ${a.pkg}: ${a.title}`)
  for (const id of stale) console.log(`allowlist entry ${id} is no longer reported by npm audit; remove it`)
  if (blocking.length) {
    for (const a of blocking) console.error(`BLOCKING ${a.severity} ${a.id} in ${a.pkg} (${a.reason}): ${a.title} ${a.url ?? ''}`)
    process.exit(1)
  }
  console.log(`npm audit gate: no unaccepted high or critical advisories (${accepted.length} accepted).`)
}
