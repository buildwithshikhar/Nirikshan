import { mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'
import { loginAs } from '../e2e/fixtures'
import { type Seeded, ensureDemo } from '../e2e/seed'

const OUT = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'docs', 'img')

let s: Seeded
test.beforeAll(async ({ playwright }) => {
  mkdirSync(OUT, { recursive: true })
  const request = await playwright.request.newContext({ baseURL: `http://localhost:${process.env.WEB_PORT ?? 5183}` })
  s = await ensureDemo(request)
  await request.dispose()
})

// One screenshot per module (reference test data; the data-origin chip is part of every case shot).
const shots: [string, () => string, string, string][] = [
  ['dashboard', () => '/', 'Dashboard', 'admin'],
  ['cases', () => `/cases/${s.caseId}`, 'DEMO-REFERENCE-001', 'examiner'],
  ['evidence', () => `/cases/${s.caseId}/evidence/${s.hikEvidenceId}`, 'Evidence', 'examiner'],
  ['device', () => `/cases/${s.caseId}/identification?evidence=${s.hikEvidenceId}`, 'Device Intelligence', 'examiner'],
  ['explorer', () => `/cases/${s.caseId}/explorer?evidence=${s.hikEvidenceId}`, 'Storage Explorer', 'examiner'],
  ['recovery', () => `/cases/${s.caseId}/recovery/clips/${s.clipId}`, 'Recovery', 'examiner'],
  ['timeline', () => `/cases/${s.caseId}/timeline`, 'Timeline', 'examiner'],
  ['triage', () => `/cases/${s.caseId}/triage?clip=${s.clipId}`, 'AI Triage', 'examiner'],
  ['correlation', () => `/cases/${s.caseId}/correlation`, 'Correlation', 'examiner'],
  ['integrity', () => `/cases/${s.caseId}/integrity`, 'Integrity Center', 'examiner'],
  ['reports', () => `/cases/${s.caseId}/reports`, 'Report Studio', 'examiner'],
  ['validation', () => '/validation', 'Validation', 'examiner'],
  ['jobs', () => `/cases/${s.caseId}/jobs?tab=history`, 'Jobs', 'examiner'],
  ['admin', () => '/admin', 'Admin', 'admin'],
  ['help', () => '/help', 'Help', 'examiner'],
]

for (const [name, url, ready, role] of shots) {
  test(`screenshot ${name}`, async ({ page }) => {
    await loginAs(page, role as 'admin' | 'examiner', url())
    await expect(page.getByRole('heading', { level: 1 }).filter({ hasText: ready }).first()).toBeVisible({ timeout: 20_000 })
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(400)
    await page.screenshot({ path: join(OUT, `ui-${name}.png`), animations: 'disabled' })
  })
}
