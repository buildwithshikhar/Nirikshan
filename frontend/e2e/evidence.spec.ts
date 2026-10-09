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

test('wizard step 1: pick a file from the server folder browser (inside the evidence roots only)', async ({ page, request }) => {
  const s = await ensureDemo(request)
  const dir = mkdtempSync(join(realpathSync(tmpdir()), 'nirikshan-e2e-pick-'))
  writeFileSync(join(dir, 'picked-image.dd'), Buffer.alloc(5000, 3))
  await loginAs(page, 'examiner', `/cases/${s.caseId}/evidence/new`)
  await page.getByRole('button', { name: 'Browse evidence folders' }).click()
  await page.getByLabel('Open folder path').fill(dir)
  await page.getByRole('button', { name: 'Open', exact: true }).click()
  await page.getByRole('button', { name: 'Select picked-image.dd' }).click()
  await expect(page.getByLabel('Source path')).toHaveValue(join(dir, 'picked-image.dd'))
  await page.getByLabel('Open folder path').fill('/etc')
  await page.getByRole('button', { name: 'Open', exact: true }).click()
  await expect(page.getByTestId('error-state')).toContainText('outside the configured evidence roots')
  await axe(page)
})

test('wizard step 1: upload from the browser fills the path and records a custody entry', async ({ page, request }) => {
  const s = await ensureDemo(request)
  const dir = mkdtempSync(join(realpathSync(tmpdir()), 'nirikshan-e2e-up-'))
  const f = join(dir, 'my upload.dd')
  writeFileSync(f, Buffer.alloc(40_000, 9))
  await loginAs(page, 'examiner', `/cases/${s.caseId}/evidence/new`)
  await page.getByLabel('Upload a file from this computer').setInputFiles(f)
  await page.getByRole('button', { name: 'Upload to the incoming folder' }).click()
  await expect(page.getByTestId('upload-result')).toContainText('my upload.dd')
  await expect(page.getByLabel('Source path')).toHaveValue(/incoming\/upload-.*\.bin$/)
  const entries = await page.evaluate(async (id) => {
    const r = await fetch(`/api/cases/${id}/custody`, { headers: { Authorization: `Bearer ${sessionStorage.getItem('nirikshan.token')}` } })
    return (await r.json()) as { action: string; examiner: string; details_json: string }[]
  }, s.caseId)
  const e = entries.filter((x) => x.action === 'file_uploaded_via_browser').pop()!
  expect(e.examiner).toContain('demo-examiner')
  expect(e.details_json).toContain('my upload.dd')
})

test('read-only role has no acquisition wizard controls and the server refuses its upload', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await loginAs(page, 'readonly', `/cases/${s.caseId}/evidence/new`)
  await expect(page.getByRole('button', { name: 'Browse evidence folders' })).toHaveCount(0)
  const status = await page.evaluate(async (id) => {
    const r = await fetch(`/api/cases/${id}/uploads?filename=a.dd`, { method: 'POST', headers: { Authorization: `Bearer ${sessionStorage.getItem('nirikshan.token')}` }, body: 'x' })
    return r.status
  }, s.caseId)
  expect(status).toBe(403)
})
