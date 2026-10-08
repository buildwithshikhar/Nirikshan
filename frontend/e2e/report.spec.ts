import { createHash } from 'node:crypto'
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'

// Expects the lead to mount <ReportPanel caseId evidence /> on the case page and register the
// report router. Written, not run, by the report stream.
test('report: generate, list with hash, download matches, draft certificate and JSON-LD offered', async ({
  page,
}) => {
  const dir = mkdtempSync(join(tmpdir(), 'nirikshan-e2e-rep-'))
  const src = join(dir, 'synthetic.dd') // synthetic bytes, not a real DVR image
  writeFileSync(src, Buffer.alloc(300_000, 5))
  const number = `E2E-REP-${Date.now()}`

  await page.goto('/cases')
  await page.getByLabel('Examiner name').fill('Insp. E2E')
  await page.getByPlaceholder('Case number').fill(number)
  await page.getByPlaceholder('Title', { exact: true }).fill('Report case')
  await page.getByRole('button', { name: 'Create case' }).click()
  await page.getByRole('link', { name: number }).click()
  await page.getByPlaceholder('Source image path (server-side)').fill(src)
  await page.getByPlaceholder('Label').fill('Synthetic HDD')
  await page.getByLabel('Write blocker used').selectOption('yes')
  await page.getByRole('button', { name: 'Acquire (read-only)' }).click()
  await expect(page.getByText('Synthetic HDD').first()).toBeVisible()

  const panel = page.getByTestId('report-panel')
  await expect(panel.getByTestId('draft-note')).toContainText('not legal advice')
  await expect(panel.getByText('No report generated yet.')).toBeVisible()
  await panel.getByRole('button', { name: 'Generate report' }).click()
  const row = panel.getByTestId('report-table').locator('tbody tr').first()
  await expect(row).toContainText('VALID')
  const shown = (await row.locator('td').nth(3).innerText()).trim()
  expect(shown).toMatch(/^[0-9a-f]{64}$/)

  const [dl] = await Promise.all([
    page.waitForEvent('download'),
    row.getByRole('link', { name: 'Download PDF' }).click(),
  ])
  const path = await dl.path()
  const bytes = readFileSync(path)
  expect(bytes.subarray(0, 4).toString()).toBe('%PDF')
  expect(createHash('sha256').update(bytes).digest('hex')).toBe(shown)

  const [cert] = await Promise.all([
    page.waitForEvent('download'),
    panel.getByRole('link', { name: /Draft §63\(4\) certificate/ }).first().click(),
  ])
  expect(cert.suggestedFilename()).toContain('DRAFT')
  await expect(panel.getByRole('link', { name: 'Export case JSON-LD' })).toBeVisible()
})
