import AxeBuilder from '@axe-core/playwright'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { type Page, expect, test } from '@playwright/test'
import { loginAs } from './fixtures'
import { ensureDemo } from './seed'

const serious = async (page: Page) => {
  const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  return r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join('|')}`)
}
const signOut = async (page: Page) => {
  await page.getByRole('button', { name: /^Close / }).first().click({ trial: false }).catch(() => undefined)
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page).toHaveURL(/\/login/)
}

test.describe.configure({ mode: 'serial' })

test('builder: generate, hash matches the download, approval workflow across two roles, finalize', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await loginAs(page, 'examiner', `/cases/${s.caseId}/reports`)
  await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1)
  await expect(page.getByTestId('draft-note')).toContainText('not legal advice')
  await page.getByRole('button', { name: 'Generate report' }).click()
  const row = page.getByTestId('report-table').locator('tbody tr').first()
  await expect(row).toContainText('VALID')
  await expect(row.getByTestId('review-status')).toHaveText('draft')
  const sha = await row.locator('code').first().getAttribute('title')
  expect(sha).toMatch(/^[0-9a-f]{64}$/)
  const [dl] = await Promise.all([page.waitForEvent('download'), row.getByRole('button', { name: /Download PDF/ }).click()])
  const bytes = readFileSync((await dl.path())!)
  expect(bytes.subarray(0, 4).toString()).toBe('%PDF')
  expect(createHash('sha256').update(bytes).digest('hex')).toBe(sha)
  expect(await serious(page)).toEqual([])

  // examiner requests approval; cannot approve (no control)
  await row.getByRole('button', { name: /Review report/ }).click()
  const drawer = page.getByTestId('detail-drawer')
  await expect(drawer.getByRole('button', { name: 'Approve' })).toHaveCount(0)
  await drawer.getByRole('button', { name: 'Request approval' }).click()
  await expect(drawer.getByTestId('review-status')).toHaveText('pending approval')
  await signOut(page)

  // reviewer approves
  await loginAs(page, 'reviewer', `/cases/${s.caseId}/reports`)
  await expect(page.getByRole('button', { name: 'Generate report' })).toHaveCount(0)
  await page.getByTestId('report-table').locator('tbody tr').first().getByRole('button', { name: /Review report/ }).click()
  await page.getByTestId('detail-drawer').getByRole('button', { name: 'Approve' }).click()
  await expect(page.getByTestId('detail-drawer').getByTestId('review-status')).toHaveText('approved')
  await signOut(page)

  // examiner finalizes
  await loginAs(page, 'examiner', `/cases/${s.caseId}/reports`)
  await page.getByTestId('report-table').locator('tbody tr').first().getByRole('button', { name: /Review report/ }).click()
  await page.getByTestId('detail-drawer').getByRole('button', { name: 'Finalize' }).click()
  await expect(page.getByTestId('detail-drawer').getByTestId('review-status')).toHaveText('final')
})

test('draft certificate is labelled DRAFT and downloads as DRAFT', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await loginAs(page, 'examiner', `/cases/${s.caseId}/reports?tab=certificate`)
  await expect(page.getByTestId('cert-draft')).toContainText('not a signed certificate')
  const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: /Download DRAFT certificate/ }).click()])
  expect(dl.suggestedFilename()).toContain('DRAFT')
  expect(await serious(page)).toEqual([])
})

test('exports: JSON-LD, package build/download/verify instructions, approval status, readonly cannot build', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await loginAs(page, 'examiner', `/cases/${s.caseId}/reports/exports`)
  await expect(page.getByRole('heading', { level: 1, name: 'Exports' })).toHaveCount(1)
  const [ld] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Export case JSON-LD' }).click()])
  expect(ld.suggestedFilename()).toMatch(/\.jsonld$/)
  await page.getByRole('tab', { name: /Evidence package/ }).click()
  await expect(page.getByTestId('package-reports')).toContainText('final')
  await page.getByRole('button', { name: 'Build package' }).click()
  await expect(page.getByTestId('toast-ok')).toContainText('built')
  await expect(page.getByTestId('verify-instructions')).toContainText('python -m app.cli verify-package')
  await expect(page.getByTestId('verify-instructions')).toContainText('--expect-key-id')
  const [pk] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: /Download package/ }).first().click()])
  expect(pk.suggestedFilename()).toMatch(/\.zip$/)
  // transfer record
  await page.getByLabel('Transfer from').fill('Insp. A')
  await page.getByLabel('Transfer to').fill('Forensic lab')
  await page.getByLabel('Transfer reason').fill('analysis at the lab')
  await page.getByRole('button', { name: 'Record transfer' }).click()
  await expect(page.getByTestId('transfers-table')).toContainText('Forensic lab')
  expect(await serious(page)).toEqual([])

  await page.getByRole('button', { name: 'Sign out' }).click()
  await loginAs(page, 'readonly', `/cases/${s.caseId}/reports/exports?tab=package`)
  await expect(page.getByRole('button', { name: 'Build package' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Record transfer' })).toHaveCount(0)
  await expect(page.getByTestId('package-table')).toBeVisible()
})
