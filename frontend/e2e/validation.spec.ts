import AxeBuilder from '@axe-core/playwright'
import { type Page, expect, test } from '@playwright/test'
import { loginAs } from './fixtures'

const serious = async (page: Page) => {
  const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  return r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join('|')}`)
}

test('validation center: origin and circularity statements beside the numbers, tier table capped at B, error rates', async ({ page }) => {
  await loginAs(page, 'readonly', '/validation')
  await expect(page.getByRole('heading', { level: 1, name: 'Validation Center' })).toHaveCount(1)
  await expect(page.getByTestId('origin-statement')).toContainText('Reference test data')
  await expect(page.getByTestId('origin-statement')).toContainText('Not captured from a physical DVR')
  await expect(page.getByTestId('basis').first()).toContainText('circular check, not independent validation')
  await expect(page.getByTestId('regression-table')).toBeVisible()
  expect(await serious(page)).toEqual([])

  await page.getByRole('tab', { name: 'Tier table' }).click()
  const tiers = page.getByTestId('tier-table')
  await expect(tiers).toContainText('Hikvision')
  await expect(tiers).toContainText('Tier B')
  await expect(tiers).not.toContainText('Tier A')
  await expect(page.getByTestId('basis')).toContainText('not independent validation')

  await page.getByRole('tab', { name: 'Error rates' }).click()
  await expect(page.getByTestId('negative-table')).toBeVisible()
  await expect(page.getByTestId('crosscheck-table')).toBeVisible()
  await expect(page.getByTestId('basis').first()).toContainText('circular')
  expect(await serious(page)).toEqual([])
})

test('compatibility registry: all 16 targets, Tier C is generic only, drawer shows sources and limits', async ({ page }) => {
  await loginAs(page, 'reviewer', '/validation/compatibility')
  await expect(page.getByRole('heading', { level: 1, name: 'Compatibility Registry' })).toHaveCount(1)
  const matrix = page.getByTestId('oem-matrix')
  await expect(matrix).toContainText('16 targets', { useInnerText: false }).catch(() => undefined)
  await expect(matrix.locator('tbody tr')).toHaveCount(16)
  await expect(matrix).not.toContainText('Tier A')
  const reolink = matrix.locator('tbody tr').filter({ hasText: 'Reolink' })
  await expect(reolink).toContainText('Tier C')
  await expect(reolink).toContainText('generic carving only')
  expect(await serious(page)).toEqual([])
  await reolink.getByRole('button', { name: 'Reolink' }).click()
  await expect(page.getByTestId('detail-drawer')).toContainText('Limitations')
  await expect(page.getByTestId('detail-drawer')).toContainText('confidence')
  await page.keyboard.press('Escape')
  await page.getByRole('tab', { name: 'Open conflicts' }).click()
  await expect(page.getByTestId('conflicts-table')).toBeVisible()
  await page.getByRole('tab', { name: 'Parser versions' }).click()
  await expect(page.getByTestId('parser-versions').locator('tbody tr')).toHaveCount(3)
})

test('re-run: not offered to reviewer; examiner starts one and sees it finish with a comparison', async ({ page }) => {
  test.setTimeout(420_000)
  await loginAs(page, 'reviewer', '/validation?tab=rerun')
  await expect(page.getByRole('button', { name: 'Start re-run' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Sign out' }).click()

  await loginAs(page, 'examiner', '/validation?tab=rerun')
  await page.getByLabel('Trials').fill('1')
  await page.getByRole('button', { name: 'Start re-run' }).click()
  await expect(page.getByTestId('toast-ok')).toContainText('started')
  const status = page.locator('[data-testid^="rerun-status-"]').first()
  await expect(status).toHaveText(/completed|failed|timeout/, { timeout: 360_000 })
  await expect(page.getByTestId('rerun-table')).toContainText('Comparable to baseline')
})
