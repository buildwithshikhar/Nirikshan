import AxeBuilder from '@axe-core/playwright'
import { type Page, expect, test } from '@playwright/test'
import { loginAs } from './fixtures'
import { ensureDemo } from './seed'

const serious = async (page: Page) => {
  const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  return r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join('|')}`)
}

test.describe.configure({ mode: 'serial' })

test('timeline: unknown timezone is prominent, clips are unplaceable with the reason, nothing defaulted', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await loginAs(page, 'examiner', `/cases/${s.caseId}/timeline`)
  await expect(page.getByRole('heading', { level: 1, name: 'Timeline' })).toHaveCount(1)
  await expect(page.getByTestId('tz-unknown-summary')).toContainText('NOT placed')
  await expect(page.getByTestId('timeline-svg')).toHaveAttribute('role', 'img')
  await page.getByRole('tab', { name: 'Unplaceable clips' }).click()
  await expect(page.getByTestId('unplaceable-item').first()).toBeVisible()
  await expect(page.getByTestId('unplaceable-reason').first()).not.toBeEmpty()
  await page.getByRole('tab', { name: 'Gaps and overlaps' }).click()
  await expect(page.getByTestId('gaps')).toBeVisible()
  expect(await serious(page)).toEqual([])
})

test('time settings: assumption needs its evidence, reference + fit, then clips are placed and the chart has a table alternative', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await loginAs(page, 'examiner', `/cases/${s.caseId}/timeline`)
  const unknownId = /#(\d+)/.exec((await page.getByTestId('tz-unknown-summary').textContent()) ?? '')![1]
  await page.goto(`/cases/${s.caseId}/timeline/time-settings?evidence=${unknownId}`)
  await expect(page.getByRole('heading', { level: 1, name: 'Time settings' })).toHaveCount(1)
  await expect(page.getByTestId('tz-unknown-banner')).toBeVisible()
  expect(await serious(page)).toEqual([])
  await page.getByLabel('IANA timezone').selectOption('UTC')
  await page.getByRole('button', { name: 'Save time assumption' }).click()
  await expect(page.getByTestId('toast-error')).toContainText(/notes/i)
  await page.getByLabel('Timezone notes').fill('DVR menu photo IMG_0042 shows UTC+00:00')
  await page.getByRole('button', { name: 'Save time assumption' }).click()
  await expect(page.getByTestId('tz-assumed-banner')).toContainText('ASSUMED')

  await page.getByRole('tab', { name: 'Reference times' }).click()
  await page.getByLabel('Device clock reading').fill('2025-06-01 10:00:00')
  await page.getByLabel('True time UTC').fill('2025-06-01T10:01:00Z')
  await page.getByLabel('Reference notes').fill('photo of DVR clock next to NTP-synced phone')
  await page.getByRole('button', { name: 'Add reference observation' }).click()
  await expect(page.getByTestId('refs-table')).toContainText('2025-06-01 10:00:00')
  await page.getByRole('tab', { name: 'Drift fit' }).click()
  await page.getByRole('button', { name: 'Fit offset / drift model' }).click()
  await expect(page.getByTestId('fit-offset')).toContainText('60.000 s')
  await expect(page.getByTestId('fit-result')).toContainText('drift ASSUMED zero')

  await page.goto(`/cases/${s.caseId}/timeline`)
  await expect(page.getByTestId('tz-unknown-summary')).toHaveCount(0)
  const chart = page.getByTestId('timeline-svg')
  await expect(chart).toHaveAttribute('role', 'img')
  await expect(chart).toHaveAttribute('aria-label', /placed clips/)
  expect(await serious(page)).toEqual([])
  await page.getByTestId('chart-toggle').click()
  await expect(page.getByTestId('chart-table')).toBeVisible()
  await page.getByRole('button', { name: /^Clip \d+/ }).first().click()
  await expect(page.getByTestId('detail-drawer')).toContainText('UTC (uncorrected)')
  await page.keyboard.press('Escape')
})

test('readonly role sees no write controls; exports remain available', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await loginAs(page, 'readonly', `/cases/${s.caseId}/timeline/time-settings?evidence=${s.dahuaEvidenceId}`)
  await expect(page.getByRole('heading', { level: 1, name: 'Time settings' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Save time assumption' })).toHaveCount(0)
  await expect(page.getByText('read-only for this action')).toBeVisible()
  await page.goto(`/cases/${s.caseId}/timeline`)
  await expect(page.getByTestId('export-csv')).toBeVisible()
  const dl = page.waitForEvent('download')
  await page.getByTestId('export-json').click()
  expect((await dl).suggestedFilename()).toMatch(/timeline/)
})
