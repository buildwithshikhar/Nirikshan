import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { type Seeded, ensureDemo } from './seed'
import { ORIGIN_DISCLOSURE, ORIGIN_HEADLINE, ORIGIN_LABEL, TIER_LIMIT } from '../src/dataOrigin'

// WCAG 2.1 A/AA automated checks on every page, with reference-test-data seeded data (the demo case).
// The test FAILS on serious and critical violations; minor/moderate ones are logged and tracked
// in docs/accessibility.md. Automated checks cover only part of WCAG (see that document).
test.describe.configure({ mode: 'serial' })

let s: Seeded
test.beforeAll(async ({ playwright }) => {
  const request = await playwright.request.newContext({
    baseURL: `http://localhost:${process.env.WEB_PORT ?? 5183}`,
  })
  s = await ensureDemo(request)
  // an analytics run so the analytics page has results to scan
  await request.post(`/api/clips/${s.clipId}/analytics`, {
    headers: { 'X-Examiner': 'Insp. A11y' },
    data: { kind: 'motion' },
  })
  await request.dispose()
})

const pages: [string, () => string, string][] = [
  ['dashboard', () => '/', 'Dashboard'],
  ['cases', () => '/cases', 'Cases'],
  ['case detail', () => `/cases/${s.caseId}`, 'DEMO-REFERENCE-001'],
  ['analysis (Hikvision parser, clips)', () => `/evidence/${s.caseId}/${s.hikEvidenceId}`, 'Parser:'],
  ['analysis (Dahua parser, clips)', () => `/evidence/${s.caseId}/${s.dahuaEvidenceId}`, 'Parser:'],
  ['analysis (raw, no parser)', () => `/evidence/${s.caseId}/${s.rawEvidenceId}`, 'Vendor identification'],
  ['custody log', () => `/cases/${s.caseId}/custody`, 'Custody log'],
  ['timeline', () => `/cases/${s.caseId}/timeline`, 'Cross-camera timeline'],
  ['analytics', () => `/clips/${s.clipId}/analytics?case=${s.caseId}`, 'Motion run'],
]

for (const [name, url, ready] of pages) {
  test(`axe: ${name}`, async ({ page }) => {
    await page.goto(url())
    await expect(page.getByText(ready, { exact: false }).first()).toBeVisible({ timeout: 20_000 })
    await page.waitForLoadState('networkidle')
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze()
    const blocking = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    const other = results.violations.filter((v) => !blocking.includes(v))
    for (const v of other) console.log(`[a11y ${name}] ${v.impact} ${v.id}: ${v.help} (${v.nodes.length} nodes)`)
    expect(
      blocking.map((v) => `${v.impact} ${v.id}: ${v.help} -> ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`),
    ).toEqual([])
  })
}

test('banners: data origin and unknown timezone are persistent on case pages', async ({ page }) => {
  for (const url of [`/cases/${s.caseId}`, `/evidence/${s.caseId}/${s.rawEvidenceId}`, `/cases/${s.caseId}/custody`]) {
    await page.goto(url)
    await expect(page.getByTestId('status-reference-data')).toContainText(ORIGIN_LABEL)
    await expect(page.getByTestId('status-tz-unknown')).toContainText(`#${s.rawEvidenceId}`)
  }
  await page.goto('/cases')
  await expect(page.getByTestId('status-reference-data')).toContainText('This workspace contains')
})

// Every demo screen states what the data is and the Tier B limit (not just the pages axe scans).
for (const [name, url, ready] of pages) {
  test(`origin and tier limit are stated on: ${name}`, async ({ page }) => {
    await page.goto(url())
    await expect(page.getByText(ready, { exact: false }).first()).toBeVisible({ timeout: 20_000 })
    const origin = page.getByTestId('status-reference-data')
    await expect(origin).toContainText(ORIGIN_HEADLINE)
    await expect(origin).toContainText(ORIGIN_DISCLOSURE)
    await expect(page.getByTestId('tier-limit')).toHaveText(TIER_LIMIT)
  })
}

test('keyboard: skip link is the first tab stop and moves focus to main', async ({ page }) => {
  await page.goto('/cases')
  await page.keyboard.press('Tab')
  const skip = page.getByRole('link', { name: 'Skip to main content' })
  await expect(skip).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/#main$/)
  await expect(page.getByRole('main')).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Primary' })).toBeVisible()
})

test('the gate can fail: axe flags a known contrast and label violation', async ({ page }) => {
  await page.setContent(
    '<main><h1>t</h1><p style="color:#64748b;background:#0f2040">low contrast</p><input></main>',
  )
  const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()
  const ids = r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => v.id)
  expect(ids).toEqual(expect.arrayContaining(['color-contrast', 'label']))
})
