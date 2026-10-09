import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { loginAs } from './fixtures'
import { ensureDemo } from './seed'

async function axe(page: Page) {
  const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join('|')}`)).toEqual([])
}

test('case list: sortable table, create case (examiner), axe', async ({ page, request }) => {
  await ensureDemo(request)
  await loginAs(page, 'examiner', '/cases')
  await expect(page.getByRole('heading', { level: 1, name: 'Cases' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'DEMO-REFERENCE-001' })).toBeVisible()
  await page.getByRole('button', { name: 'Number' }).click()
  await expect(page.getByRole('columnheader', { name: /Number/ })).toHaveAttribute('aria-sort', 'ascending')
  await axe(page)
  const number = `E2E-CASE-${Date.now()}`
  await page.getByLabel('Case number').fill(number)
  await page.getByLabel('Title', { exact: true }).fill('E2E created case')
  await page.getByRole('button', { name: 'Create case' }).click()
  await expect(page.getByRole('heading', { level: 1 })).toContainText(number)
  await expect(page.getByRole('tab', { name: 'Overview' })).toHaveAttribute('aria-selected', 'true')
})

test('read-only role sees the case list but no create form', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await loginAs(page, 'readonly', '/cases')
  await expect(page.getByRole('link', { name: 'DEMO-REFERENCE-001' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Create case' })).toHaveCount(0)
  await page.goto(`/cases/${s.caseId}?tab=evidence`)
  await expect(page.getByRole('link', { name: 'New acquisition' })).toHaveCount(0)
})

test('case detail: overview, evidence list and activity tabs, axe', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await loginAs(page, 'examiner', `/cases/${s.caseId}`)
  await expect(page.getByRole('heading', { level: 1 })).toContainText('DEMO-REFERENCE-001')
  await expect(page.getByText('Members (read-only)')).toBeVisible()
  await axe(page)
  await page.getByRole('tab', { name: 'Evidence list' }).click()
  await expect(page.getByRole('link', { name: /Hikvision/ })).toBeVisible()
  await expect(page.getByRole('link', { name: 'New acquisition' })).toBeVisible()
  await page.getByRole('tab', { name: 'Activity' }).click()
  await page.getByLabel('Filter Chain-of-custody entries for this case').fill('evidence_acquired')
  await expect(page.getByRole('cell', { name: 'evidence_acquired' }).first()).toBeVisible()
  await axe(page)
})
