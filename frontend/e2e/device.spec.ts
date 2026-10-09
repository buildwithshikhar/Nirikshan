import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { loginAs } from './fixtures'
import { ensureDemo } from './seed'

async function axe(page: Page) {
  const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join('|')}`)).toEqual([])
}

test('identification of the Hikvision reference image: signatures, tier B, model and firmware stay unknown', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await loginAs(page, 'readonly', `/cases/${s.caseId}/identification?evidence=${s.hikEvidenceId}`)
  await expect(page.getByRole('heading', { level: 1, name: 'Identification result' })).toBeVisible()
  await expect(page.getByTestId('manufacturer')).toHaveText('Hikvision')
  await expect(page.getByRole('tab', { name: 'Signature matches' })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Tier B' }).first()).toBeVisible()
  await axe(page)
  await page.getByRole('button', { name: 'Show signatures for Hikvision' }).click()
  await expect(page.getByTestId('detail-drawer')).toContainText('hik_master_any')
  await page.keyboard.press('Escape')
  await page.getByRole('tab', { name: 'Unknown-device view' }).click()
  await expect(page.getByTestId('idfield-unknown').first()).toContainText('unknown')
  await expect(page.getByText('no model field is documented')).toBeVisible()
  await axe(page)
})

test('parser selection tab shows routing and the OEM registry with no vendor above Tier B', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await loginAs(page, 'examiner', `/cases/${s.caseId}/identification?evidence=${s.hikEvidenceId}&tab=selection`)
  await expect(page.getByTestId('routing-engine')).toContainText('Hikvision parser')
  await expect(page.getByRole('table', { name: 'OEM registry support levels' })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Tier A', exact: true })).toHaveCount(0)
  await axe(page)
})

test('an unidentifiable image reports unknown manufacturer and refresh works', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await loginAs(page, 'examiner', `/cases/${s.caseId}/identification?evidence=${s.rawEvidenceId}`)
  await expect(page.getByTestId('manufacturer')).toHaveText('unknown')
  await page.getByRole('button', { name: 'Refresh identification' }).click()
  await expect(page.getByTestId('toast-ok').filter({ hasText: 'refreshed' })).toBeVisible()
  await page.getByRole('tab', { name: 'Unknown-device view' }).click()
  await expect(page.getByText('manufacturer unknown').first()).toBeVisible()
})
