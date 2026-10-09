import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { mkdtempSync, realpathSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { loginAs } from './fixtures'
import { ensureDemo } from './seed'

async function axe(page: Page) {
  const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join('|')}`)).toEqual([])
}

test('create case -> wizard acquire -> verify -> custody entries -> chain valid', async ({ page }) => {
  const dir = mkdtempSync(join(realpathSync(tmpdir()), 'nirikshan-e2e-'))
  const src = join(dir, 'synthetic.dd') // synthetic bytes, not a real DVR image
  writeFileSync(src, Buffer.alloc(300_000, 7))
  const number = `E2E-ACQ-${Date.now()}`
  await loginAs(page, 'examiner', '/cases')
  await page.getByLabel('Case number').fill(number)
  await page.getByLabel('Title', { exact: true }).fill('E2E acquisition case')
  await page.getByRole('button', { name: 'Create case' }).click()
  await expect(page.getByRole('heading', { level: 1 })).toContainText(number)
  const caseUrl = page.url()
  await page.goto(`${caseUrl}/evidence/new`)
  await expect(page.getByRole('heading', { level: 1, name: 'New acquisition' })).toBeVisible()
  await expect(page.getByTestId('unavailable')).toContainText('E01/EWF')
  await axe(page)
  await page.getByLabel('Source path').fill(src)
  await page.getByRole('button', { name: 'Next' }).click()
  await expect(page.getByRole('button', { name: 'Next' })).toBeDisabled() // attestation required
  await page.getByLabel('yes').check()
  await page.getByRole('button', { name: 'Next' }).click()
  await page.getByLabel('Evidence label').fill('Synthetic HDD')
  await page.getByRole('button', { name: 'Next' }).click()
  await expect(page.getByText('Write blocker (attested)')).toBeVisible()
  await page.getByRole('button', { name: 'Next' }).click()
  await page.getByRole('button', { name: 'Acquire', exact: true }).click()
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Synthetic HDD')
  await page.getByRole('tab', { name: 'Hash and verify' }).click()
  await expect(page.getByText(/[0-9a-f]{12}…/).first()).toBeVisible()
  await page.getByRole('button', { name: 'Verify hashes' }).click()
  await expect(page.getByTestId('toast-ok').filter({ hasText: 'Hashes match' })).toBeVisible()
  await expect(page.getByText(/verified 20/)).toBeVisible()
  await axe(page)
  await page.getByRole('tab', { name: 'Custody entries' }).click()
  await expect(page.getByRole('cell', { name: 'evidence_acquired' })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'evidence_verified' }).first()).toBeVisible()
  await page.getByRole('tab', { name: 'Source and attestation' }).click()
  await expect(page.getByRole('img', { name: /Bad-sector map: no unreadable ranges/ })).toBeVisible()
})

test('evidence list and detail of the demo case; readonly cannot acquire or verify', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await loginAs(page, 'readonly', `/cases/${s.caseId}/evidence`)
  await expect(page.getByRole('heading', { level: 1, name: 'Evidence' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'New acquisition' })).toHaveCount(0)
  await axe(page)
  await page.goto(`/cases/${s.caseId}/evidence/${s.hikEvidenceId}?tab=hash`)
  await expect(page.getByRole('button', { name: 'Verify hashes' })).toBeDisabled()
  await page.goto(`/cases/${s.caseId}/evidence/new`)
  await expect(page.getByRole('note')).toContainText('read-only')
})
