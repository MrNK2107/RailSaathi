import { registerServiceWorker } from '../pwa'
import { installStaleChunkReload, RETRY_WINDOW_MS } from '../staleChunks'

function fakeWindow({ secure = true, withWorker = true, readyState = 'loading' } = {}) {
  const register = vi.fn().mockResolvedValue({})
  const target = new EventTarget()
  const win = {
    isSecureContext: secure,
    navigator: withWorker ? { serviceWorker: { register } } : {},
    document: { readyState },
    addEventListener: target.addEventListener.bind(target),
    dispatchLoad: () => target.dispatchEvent(new Event('load')),
  }
  return { win, register }
}

describe('registerServiceWorker', () => {
  it('registers /sw.js after the load event in a production build', () => {
    const { win, register } = fakeWindow()
    registerServiceWorker({ production: true, win: win as unknown as Window })
    expect(register).not.toHaveBeenCalled()
    win.dispatchLoad()
    expect(register).toHaveBeenCalledWith('/sw.js')
  })

  it('registers at once when the page has already loaded', () => {
    const { win, register } = fakeWindow({ readyState: 'complete' })
    registerServiceWorker({ production: true, win: win as unknown as Window })
    expect(register).toHaveBeenCalledTimes(1)
  })

  it('does nothing in dev, on an insecure origin, or without service worker support', () => {
    for (const [production, opts] of [[false, {}], [true, { secure: false }], [true, { withWorker: false }]] as const) {
      const { win, register } = fakeWindow({ ...opts, readyState: 'complete' })
      expect(() => registerServiceWorker({ production, win: win as unknown as Window })).not.toThrow()
      expect(register).not.toHaveBeenCalled()
    }
  })

  it('swallows a failed registration', async () => {
    const { win, register } = fakeWindow({ readyState: 'complete' })
    register.mockRejectedValue(new Error('blocked'))
    registerServiceWorker({ production: true, win: win as unknown as Window })
    await expect(register.mock.results[0].value).rejects.toThrow('blocked')
  })
})

describe('installStaleChunkReload', () => {
  const preloadError = () => window.dispatchEvent(new Event('vite:preloadError'))

  it('reloads once when a lazy chunk fails, and not again within the retry window', () => {
    let t = 1_000_000
    const reload = vi.fn()
    const uninstall = installStaleChunkReload({ now: () => t, reload })
    preloadError()
    expect(reload).toHaveBeenCalledTimes(1)
    t += RETRY_WINDOW_MS - 1
    preloadError() // still failing right after the reload: leave it to ScreenBoundary
    expect(reload).toHaveBeenCalledTimes(1)
    t += 2
    preloadError() // a later deploy in the same tab
    expect(reload).toHaveBeenCalledTimes(2)
    uninstall()
    t += RETRY_WINDOW_MS
    preloadError()
    expect(reload).toHaveBeenCalledTimes(2)
  })

  it('does not reload when sessionStorage is unavailable (no loop guard)', () => {
    const reload = vi.fn()
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied') })
    const uninstall = installStaleChunkReload({ reload })
    preloadError()
    expect(reload).not.toHaveBeenCalled()
    uninstall()
    getItem.mockRestore()
  })
})
