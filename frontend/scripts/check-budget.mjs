// Bundle budget gate, run after `vite build` (it is part of `npm run build`, so CI and the Docker build enforce it).
// Sizes are gzip bytes at level 6 (what Vite prints and what nginx/default.conf.template serves with gzip_comp_level 6)
// of the files in dist/, using dist/.vite/manifest.json to follow the import graph. Budgets (kB = 1000 bytes):
//   initial JS        entry chunk + everything it statically imports (React, the shell, the router)   <= 180
//   home first view   initial JS + the #/home screen chunk and its static imports                      <= 180
//   three.js chunk    the three.js vendor chunk on its own                                             <= 200
//   3D tour           everything #/tour downloads on top of the initial JS (screen, scene, three.js)   <= 270
//   any other chunk   every other lazy JS chunk (a screen or a shared module)                          <= 40
// The tour and three.js ceilings sit about 10 % above today's size: they only load on #/tour, only when WebGL exists.
// The 40 kB ceiling is about 4x the largest screen chunk: a screen that grows past it should be split or reviewed.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { gzipSync } from 'node:zlib'

const DIST = fileURLToPath(new URL('../dist/', import.meta.url))
const KB = 1000
const BUDGET = { initial: 180, home: 180, three: 200, tour: 270, chunk: 40 }

const manifest = JSON.parse(readFileSync(join(DIST, '.vite', 'manifest.json'), 'utf8'))
const gz = (key) => gzipSync(readFileSync(join(DIST, manifest[key].file)), { level: 6 }).length
const kb = (bytes) => `${(bytes / KB).toFixed(1)} kB`
const keyWhere = (test, what) => {
  const key = Object.keys(manifest).find((k) => test(manifest[k]))
  if (!key) throw new Error(`${what} not found in the Vite manifest`)
  return key
}

/** Chunks reachable from `key` (static imports, plus dynamic ones when asked), skipping those in `exclude`. */
function closure(key, { dynamic = false, exclude = new Set() } = {}) {
  const seen = new Set()
  const walk = (k) => {
    if (seen.has(k) || exclude.has(k)) return
    seen.add(k)
    for (const dep of [...(manifest[k].imports ?? []), ...(dynamic ? manifest[k].dynamicImports ?? [] : [])]) walk(dep)
  }
  walk(key)
  return seen
}
const total = (keys) => [...keys].reduce((sum, k) => sum + gz(k), 0)

let failed = false
function check(label, bytes, limitKb) {
  const over = bytes > limitKb * KB
  if (over) failed = true
  console.log(`${over ? 'OVER BUDGET ' : ''}${label}: ${kb(bytes)} gzip (budget ${limitKb} kB)`)
}

const initial = closure(keyWhere((c) => c.isEntry, 'the entry chunk'))
check(`initial JS (entry + static imports, ${initial.size} chunks)`, total(initial), BUDGET.initial)

const home = closure(keyWhere((c) => c.name === 'Dashboard', 'the Dashboard (#/home) chunk'), { exclude: initial })
check(`home first view (initial + ${home.size} screen chunks)`, total(initial) + total(home), BUDGET.home)

const threeKey = keyWhere((c) => c.name === 'three', 'the three.js chunk')
check(`three.js chunk ${manifest[threeKey].file}`, gz(threeKey), BUDGET.three)

const tour = closure(keyWhere((c) => c.name === 'StationTour', 'the StationTour chunk'), { dynamic: true, exclude: initial })
check(`3D tour on top of the initial JS (${tour.size} chunks)`, total(tour), BUDGET.tour)

for (const [key, chunk] of Object.entries(manifest)) {
  if (initial.has(key) || key === threeKey || !chunk.file.endsWith('.js')) continue
  if (chunk.name === 'TourScene') continue // counted in the 3D tour budget above
  check(`  lazy ${chunk.file}`, gz(key), BUDGET.chunk)
}
if (failed) {
  console.error('Bundle budget exceeded (see scripts/check-budget.mjs).')
  process.exit(1)
}
