import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'

// Expects the lead to route /cases/:id/timeline to src/pages/Timeline.tsx.
test('timeline: unknown timezone is prominent, assumption + reference + fit, exports offered', async ({
  page,
}) => {
  const dir = mkdtempSync(join(tmpdir(), 'nirikshan-e2e-tl-'))
  const src = join(dir, 'synthetic.dd') // synthetic bytes, not a real DVR image
  writeFileSync(src, Buffer.alloc(300_000, 7))
  const number = `E2E-TL-${Date.now()}`

  await page.goto('/cases')
  await page.getByLabel('Examiner name').fill('Insp. E2E')
  await page.getByPlaceholder('Case number').fill(number)
  await page.getByPlaceholder('Title', { exact: true }).fill('Timeline case')
  await page.getByRole('button', { name: 'Create case' }).click()
  await page.getByRole('link', { name: number }).click()
  await page.getByPlaceholder('Source image path (server-side)').fill(src)
  await page.getByPlaceholder('Label').fill('Synthetic HDD')
  await page.getByLabel('Write blocker used').selectOption('yes')
  await page.getByRole('button', { name: 'Acquire (read-only)' }).click()
  await expect(page.getByText('Synthetic HDD').first()).toBeVisible()

  const caseId = page.url().split('/cases/')[1].split(/[/?#]/)[0]
  await page.goto(`/cases/${caseId}/timeline`)

  // unknown timezone is shown, not hidden
  await expect(page.getByTestId('tz-unknown-banner')).toBeVisible()
  await expect(page.getByTestId('tz-unknown-summary')).toContainText('NOT placed')

  // saving an assumption requires the evidence for it
  await page.getByLabel('Device timezone').selectOption('UTC')
  await page.getByRole('button', { name: 'Save time assumption' }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'notes are required' })).toBeVisible()
  await page.getByLabel('Timezone notes').fill('DVR menu photo IMG_0042 shows UTC+00:00')
  await page.getByRole('button', { name: 'Save time assumption' }).click()
  await expect(page.getByTestId('tz-assumed-banner')).toContainText('ASSUMED')

  // reference observation + fit (single observation: drift assumed zero, stated)
  await page.getByLabel('Device clock reading').fill('2025-06-01 10:00:00')
  await page.getByLabel('True time UTC').fill('2025-06-01T10:01:00Z')
  await page.getByLabel('Reference notes').fill('photo of DVR clock next to NTP-synced phone')
  await page.getByRole('button', { name: 'Add reference observation' }).click()
  await expect(page.getByTestId('refs-table')).toContainText('2025-06-01 10:00:00')
  await page.getByRole('button', { name: 'Fit offset / drift model' }).click()
  await expect(page.getByTestId('fit-offset')).toContainText('60.000 s')
  await expect(page.getByTestId('fit-drift')).toContainText('assumed bound')
  await expect(page.getByTestId('fit-result')).toContainText('drift ASSUMED zero')

  // exports and empty-axis message (no clips analysed in this case)
  await expect(page.getByTestId('export-csv')).toHaveAttribute('href', /timeline\/export\?format=csv/)
  await expect(page.getByTestId('export-json')).toHaveAttribute('href', /timeline\/export\?format=json/)
  await expect(page.getByTestId('chart-empty')).toBeVisible()
})
