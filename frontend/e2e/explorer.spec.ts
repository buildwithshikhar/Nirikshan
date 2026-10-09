import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { loginAs } from './fixtures'
import { ensureDemo } from './seed'

async function axe(page: Page) {
  const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join('|')}`)).toEqual([])
}

test('offset map: accessible SVG layout with table alternative, vendor structures, anomalies', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await loginAs(page, 'readonly', `/cases/${s.caseId}/explorer?evidence=${s.hikEvidenceId}`)
  await expect(page.getByRole('heading', { level: 1, name: 'Offset map' })).toBeVisible()
  await expect(page.getByRole('img', { name: /Layout map of/ })).toBeVisible()
  await expect(page.getByRole('table', { name: 'Regions of the image' })).toBeVisible()
  await axe(page)
  await page.getByRole('tab', { name: 'Vendor structures' }).click()
  await expect(page.getByRole('table', { name: /Vendor and partition structures/ })).toBeVisible()
  await expect(page.getByText('hik_master_any').first()).toBeVisible()
  await axe(page)
  await page.getByRole('tab', { name: 'Anomalies' }).click()
  await expect(page.getByText(/\d+ item\(s\)/)).toBeVisible()
  await axe(page)
})

test('hex view is read-only, clamps length to 4096 and rejects an offset past the image', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await loginAs(page, 'readonly', `/cases/${s.caseId}/explorer?evidence=${s.hikEvidenceId}`)
  await page.getByLabel('Offset (decimal or 0x hex)').fill('0x0')
  await page.getByLabel('Length (1 to 4096)').fill('999999')
  await page.getByRole('button', { name: 'Read bytes' }).click()
  const dump = page.getByTestId('hex-dump')
  await expect(dump).toContainText('|NIRIKSHAN SYNTHE|')
  await expect(page.getByLabel('Length (1 to 4096)')).toHaveValue('4096')
  await expect(page.getByText('4096 bytes from 0x0')).toBeVisible()
  await page.getByLabel('Offset (decimal or 0x hex)').fill('999999999')
  await page.getByRole('button', { name: 'Read bytes' }).click()
  await expect(page.getByTestId('toast-error')).toContainText('Offset must be between')
  await axe(page)
})
