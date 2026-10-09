import AxeBuilder from '@axe-core/playwright'
import { type Page, expect, test } from '@playwright/test'
import { loginAs } from './fixtures'
import { ensureDemo } from './seed'

const serious = async (page: Page) => {
  const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  return r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join('|')}`)
}

test.describe.configure({ mode: 'serial' })

test('run: background jobs for motion, objects, faces complete; results carry the triage label, model hash and error rates', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await loginAs(page, 'examiner', `/cases/${s.caseId}/triage?clip=${s.clipId}`)
  await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1)
  await expect(page.getByTestId('triage-statement')).toContainText('not identifications')
  await expect(page.getByTestId('triage-statement')).toContainText('no recognition and no matching')
  await expect(page.getByTestId('models-list')).toContainText('YOLOX')
  expect(await serious(page)).toEqual([])

  for (const kind of ['motion', 'objects', 'faces']) {
    await page.getByRole('button', { name: `Run ${kind}` }).click()
    await expect(page.getByTestId(`job-${kind}`)).toContainText('completed', { timeout: 120_000 })
  }

  await page.getByTestId('job-motion').getByRole('link', { name: /View motion results/ }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Triage results' })).toHaveCount(1)
  const motion = page.getByTestId('run-motion')
  await expect(motion.getByTestId('run-status')).toHaveText('completed')
  await expect(motion.getByTestId('triage-label')).toHaveText('triage, not identification')
  await expect(motion).toContainText('NOMINAL')
  await expect(motion.getByTestId('error-rates')).toContainText('Nothing was validated on real DVR footage')
  expect(await serious(page)).toEqual([])

  await page.getByRole('tab', { name: 'Objects' }).click()
  const objects = page.getByTestId('run-objects')
  await expect(objects.getByTestId('model-info')).toContainText('YOLOX-Nano')
  await expect(objects.getByTestId('model-hash')).toHaveText('c789161ed43c')
  await expect(objects.getByTestId('error-rates')).toContainText('Penn-Fudan')

  await page.getByRole('tab', { name: 'Faces' }).click()
  const faces = page.getByTestId('run-faces')
  await expect(faces.getByTestId('model-info')).toContainText('YuNet')
  await expect(faces.getByTestId('model-hash')).toHaveText('8f2383e4dd3c')
  await expect(faces).toContainText('says nothing about who')
  await expect(faces).not.toContainText(/identified|match(ed)? to|recogni[sz]ed as/i)

  await page.getByRole('tab', { name: 'Error rates' }).click()
  await expect(page.getByTestId('error-rates-tab')).toContainText('Face detection')
})

test('event search: grammar help, index status, reindex, search, parse error, unavailable frame offset, summaries', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await loginAs(page, 'examiner', `/cases/${s.caseId}/triage/search`)
  await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1)
  await expect(page.getByTestId('index-status')).toContainText('events indexed')
  await page.getByRole('button', { name: 'Reindex events' }).click()
  await expect(page.getByTestId('toast-ok')).toContainText('rebuilt')
  await page.getByTestId('grammar-help').locator('summary').click()
  await expect(page.getByTestId('grammar-help')).toContainText('camera N')

  await page.getByLabel('Event query').fill('motion')
  await page.getByRole('button', { name: 'Search', exact: true }).click()
  await expect(page.getByTestId('search-results')).toContainText(/\d+ hits?/)
  const first = page.getByTestId('hits-table').locator('tbody tr').first().getByRole('button').first()
  if (await first.count()) {
    await first.click()
    await expect(page.getByTestId('detail-drawer')).toContainText('Per-frame byte offset: not available')
    await expect(page.getByTestId('detail-drawer')).toContainText('triage, not identification')
    await page.keyboard.press('Escape')
  }
  await page.getByLabel('Event query').fill('confidence>abc')
  await page.getByRole('button', { name: 'Search', exact: true }).click()
  await expect(page.getByTestId('query-error')).toBeVisible()
  expect(await serious(page)).toEqual([])

  await page.getByRole('tab', { name: 'Summaries' }).click()
  await expect(page.getByTestId('summaries')).toContainText('automatic summary of triage detections')
  expect(await serious(page)).toEqual([])
})

test('readonly can read results but has no run, reindex controls', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await loginAs(page, 'readonly', `/cases/${s.caseId}/triage?clip=${s.clipId}`)
  await expect(page.getByTestId('triage-statement')).toBeVisible()
  await expect(page.getByRole('button', { name: /^Run (motion|objects|faces)$/ })).toHaveCount(0)
  await page.goto(`/cases/${s.caseId}/triage/search`)
  await expect(page.getByTestId('index-status')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Reindex events' })).toHaveCount(0)
  await page.goto(`/cases/${s.caseId}/triage/results?clip=${s.clipId}`)
  await expect(page.getByTestId('run-motion')).toBeVisible()
})
