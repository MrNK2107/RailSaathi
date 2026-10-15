// WebXR floor arrow: the composed mesh tilt + holder yaw must put the arrow's tip on the target direction.
import { arrowTipDirection, floorDirection, holderYawRad } from '../ar/xr'

describe('floor arrow orientation', () => {
  it.each([0, 45, 90, 180, 270, 333])('the tip points along the target yaw %i°', (yaw) => {
    const [tx, tz] = arrowTipDirection(yaw)
    const [dx, , dz] = floorDirection(yaw)
    expect(tx).toBeCloseTo(dx)
    expect(tz).toBeCloseTo(dz)
  })

  it('a target to the right (+X) puts the tip at +X, not behind', () => {
    const [tx, tz] = arrowTipDirection(90)
    expect(tx).toBeCloseTo(1)
    expect(tz).toBeCloseTo(0)
    expect(holderYawRad(0)).toBeCloseTo(0)
  })
})

describe('floor mode needs the DOM overlay', () => {
  it('requires dom-overlay and ends the session when it is not shown', async () => {
    const { startFloorArrows, hasDomOverlay } = await import('../ar/xr')
    expect(hasDomOverlay({ domOverlayState: { type: 'screen' } })).toBe(true)
    expect(hasDomOverlay({ domOverlayState: null })).toBe(false)
    expect(hasDomOverlay({})).toBe(false)

    const end = vi.fn(() => Promise.resolve())
    const requestSession = vi.fn(async () => ({ end, domOverlayState: null }))
    Object.defineProperty(navigator, 'xr', { value: { requestSession }, configurable: true })
    try {
      const root = document.createElement('div')
      await expect(startFloorArrows({ arrowAngleDeg: 0, overlayRoot: root, onEnd: vi.fn() })).rejects.toThrow('dom_overlay_unavailable')
      expect(requestSession).toHaveBeenCalledWith('immersive-ar', { requiredFeatures: ['hit-test', 'dom-overlay'], domOverlay: { root } })
      expect(end).toHaveBeenCalled()
    } finally {
      Reflect.deleteProperty(navigator, 'xr')
    }
  })
})
