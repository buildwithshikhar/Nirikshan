import { mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'
import { type Seeded, ensureDemo } from '../e2e/seed'

const OUT = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'docs', 'img')

let s: Seeded
test.beforeAll(async ({ playwright }) => {
  mkdirSync(OUT, { recursive: true })
  const request = await playwright.request.newContext({
    baseURL: `http://localhost:${process.env.WEB_PORT ?? 5183}`,
  })
  s = await ensureDemo(request)
  await request.post(`/api/clips/${s.clipId}/analytics`, {
    headers: { 'X-Examiner': 'Demo Examiner (reference data)' },
    data: { kind: 'motion' },
  })
  await request.dispose()
})

// Every shot must show the reference-data banner; the run fails otherwise.
const shots: [string, () => string, string, string?][] = [
  ['dashboard', () => '/', 'System'],
  ['case', () => `/cases/${s.caseId}`, 'Evidence'],
  ['analysis', () => `/evidence/${s.caseId}/${s.dahuaEvidenceId}`, 'Parser:', 'Parser:'],
  ['timeline', () => `/cases/${s.caseId}/timeline`, 'Cross-camera timeline', 'Cross-camera timeline'],
  ['analytics', () => `/clips/${s.clipId}/analytics?case=${s.caseId}`, 'Motion run'],
  ['custody', () => `/cases/${s.caseId}/custody`, 'Custody log'],
]

for (const [name, url, ready, scrollTo] of shots) {
  test(`screenshot ${name}`, async ({ page }) => {
    await page.goto(url())
    await expect(page.getByText(ready).first()).toBeVisible({ timeout: 20_000 })
    await expect(page.getByTestId('status-reference-data')).toContainText('Reference test data')
    await page.waitForLoadState('networkidle')
    if (scrollTo) await page.getByText(scrollTo).first().evaluate((el) => { el.scrollIntoView({ block: 'start' }); window.scrollBy(0, -150) })
    await page.waitForTimeout(500)
    await page.screenshot({ path: join(OUT, `${name}.png`), animations: 'disabled' })
  })
}
