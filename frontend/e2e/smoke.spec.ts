import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'

test('dashboard loads and the API reports online', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
  await expect(page.getByText('API online')).toBeVisible()
  await expect(page.getByTestId('ffmpeg-status')).toBeVisible()
})

test('create case -> acquire -> verify evidence -> verify custody chain', async ({ page }) => {
  const dir = mkdtempSync(join(tmpdir(), 'nirikshan-e2e-'))
  const src = join(dir, 'synthetic.dd') // synthetic bytes, not a real DVR image
  writeFileSync(src, Buffer.alloc(300_000, 7))
  const number = `E2E-${Date.now()}`

  await page.goto('/cases')
  await page.getByLabel('Examiner name').fill('Insp. E2E')
  await page.getByPlaceholder('Case number').fill(number)
  await page.getByPlaceholder('Title', { exact: true }).fill('E2E case')
  await page.getByRole('button', { name: 'Create case' }).click()
  await page.getByRole('link', { name: number }).click()

  await page.getByPlaceholder('Source image path (server-side)').fill(src)
  await page.getByPlaceholder('Label').fill('Synthetic HDD')
  await page.getByLabel('Write blocker used').selectOption('yes')
  await page.getByRole('button', { name: 'Acquire (read-only)' }).click()
  const row = page.getByRole('row').filter({ hasText: 'Synthetic HDD' })
  await expect(row).toContainText('acquired')
  await expect(row).toContainText(/SHA-256 [0-9a-f]{64}/)
  await expect(page.getByTestId('head-hash')).toContainText(/[0-9a-f]{64}/)
  await row.getByRole('button', { name: 'Verify' }).click()
  await expect(row).toContainText('verified')

  await page.getByRole('link', { name: 'Custody log →' }).click()
  await expect(page.getByRole('cell', { name: 'evidence_acquired' })).toBeVisible()
  await expect(page.getByTestId('head-hash')).toContainText(/[0-9a-f]{64}/)
  await page.getByRole('button', { name: 'Verify chain and signatures' }).click()
  await expect(page.getByTestId('chain-result')).toContainText('CHAIN VALID')
})
