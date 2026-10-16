// Writes dist/sw.js from the sw/sw.js template at build time (see the template's header for what the worker does).
//   VERSION       hash of the template and every emitted file name. Chunk names carry content hashes, so any deploy
//                 that changes the app is a new worker with a new cache, and the old cache is deleted on activate.
//   SHELL_ASSETS  the entry chunk, everything it statically imports and its CSS: what the shell needs to boot offline.
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import type { Plugin } from 'vite'

const VERSION_MARK = "'__BUILD_VERSION__'"
const ASSETS_MARK = '[/* __SHELL_ASSETS__ */]'

export function serviceWorker(templatePath: string): Plugin {
  return {
    name: 'railsaathi-service-worker',
    apply: 'build',
    generateBundle(_options, bundle) {
      const template = readFileSync(templatePath, 'utf8')
      if (!template.includes(VERSION_MARK) || !template.includes(ASSETS_MARK)) {
        this.error(`${templatePath} is missing the ${VERSION_MARK} or ${ASSETS_MARK} placeholder`)
      }
      const entry = Object.values(bundle).find((file) => file.type === 'chunk' && file.isEntry)
      if (!entry) this.error('no entry chunk to build the service worker shell from')

      const shell = new Set<string>()
      const walk = (fileName: string) => {
        const file = bundle[fileName]
        if (shell.has(fileName) || file?.type !== 'chunk') return
        shell.add(fileName)
        file.viteMetadata?.importedCss.forEach((css) => shell.add(css))
        file.imports.forEach(walk)
      }
      walk(entry.fileName)

      const version = createHash('sha256').update(template).update(Object.keys(bundle).sort().join('\n')).digest('hex').slice(0, 12)
      const source = template
        .replace(VERSION_MARK, JSON.stringify(version))
        .replace(ASSETS_MARK, JSON.stringify([...shell].sort().map((f) => `/${f}`)))
      this.emitFile({ type: 'asset', fileName: 'sw.js', source })
    },
  }
}
