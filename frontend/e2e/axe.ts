import AxeBuilder from '@axe-core/playwright'
import { expect, type Page } from '@playwright/test'

/**
 * Runs axe-core on the current page with every rule it enables by default (WCAG 2.0/2.1/2.2 A and AA plus best
 * practices) and fails with a readable list of violations: rule, impact, the offending elements and axe's summary.
 * No rule is disabled. Call it once the screen has settled (its heading or main control is visible).
 */
export async function expectNoAxeViolations(page: Page, screen: string): Promise<void> {
  await expect(page.getByText('Loading…', { exact: true })).toHaveCount(0)
  const { violations } = await new AxeBuilder({ page }).analyze()
  const report = violations.flatMap((v) =>
    v.nodes.map((n) => `${v.id} (${v.impact}) ${n.target.join(' ')}: ${n.failureSummary?.replace(/\s+/g, ' ')}`))
  expect(report, `axe violations on ${screen}`).toEqual([])
}
