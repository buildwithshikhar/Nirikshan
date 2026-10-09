import AxeBuilder from '@axe-core/playwright'
import { type Page, expect, test } from '@playwright/test'
import { loginAs } from './fixtures'
import { ensureDemo } from './seed'

const serious = async (page: Page) => {
  const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  return r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join('|')}`)
}
// a 1x1 PNG: a stand-in image, not a real floor plan
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64')

test.describe.configure({ mode: 'serial' })

test('camera map: define cameras and adjacency, upload a floor plan, accessible map with table alternative', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await loginAs(page, 'examiner', `/cases/${s.caseId}/correlation?tab=map`)
  await expect(page.getByRole('heading', { level: 1, name: 'Link suggestions' })).toHaveCount(1)
  await expect(page.getByText('suggestion: time/topology/class rule match, triage, not identification').first()).toBeVisible()
  for (const [id, x, y] of [['cam1', '20', '30'], ['cam2', '70', '60']]) {
    await page.getByLabel('Camera id').fill(id)
    await page.getByLabel('Camera label').fill(`Camera ${id}`)
    await page.getByLabel('Camera channel').fill(id === 'cam1' ? '1' : '2')
    await page.getByLabel('Camera x').fill(x)
    await page.getByLabel('Camera y').fill(y)
    await page.getByRole('button', { name: 'Add camera' }).click()
  }
  await page.getByLabel('Adjacent A').selectOption('cam1')
  await page.getByLabel('Adjacent B').selectOption('cam2')
  await page.getByRole('button', { name: 'Add adjacency' }).click()
  await page.getByRole('button', { name: 'Save camera layout' }).click()
  await expect(page.getByTestId('toast-ok')).toContainText('Camera layout saved')
  await page.getByLabel('Floor plan image').setInputFiles({ name: 'plan.png', mimeType: 'image/png', buffer: PNG })
  await expect(page.getByText('Floor plan stored')).toBeVisible()
  await expect(page.getByAltText('Uploaded floor plan')).toBeVisible()
  const map = page.getByTestId('camera-map')
  await expect(map).toHaveAttribute('role', 'img')
  await expect(map).toHaveAttribute('aria-label', /2 camera nodes, 1 adjacency/)
  await expect(page.getByTestId('nodes-table')).toContainText('cam2')
  await expect(page.getByTestId('edges-table')).toContainText('cam1')
  expect(await serious(page)).toEqual([])
})

test('external log: timezone is required, import keeps the authorisation, suggestions generate with the no-appearance statement', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await loginAs(page, 'examiner', `/cases/${s.caseId}/correlation?tab=logs`)
  await page.getByLabel('Log file').setInputFiles({ name: 'door.csv', mimeType: 'text/csv', buffer: Buffer.from('timestamp,event,door\n2025-06-01 10:00:05,badge,Lobby\nnot a time,badge,Lobby\n') })
  await page.getByLabel('Authorisation note').fill('Consent ref. E2E-1')
  await page.getByLabel('Time column').selectOption('timestamp')
  await page.getByLabel('Event column').selectOption('event')
  await page.getByLabel('Location column').selectOption('door')
  await page.getByLabel('Location mapping').fill('Lobby=cam2')
  await expect(page.getByRole('button', { name: 'Import log' })).toBeDisabled() // no timezone chosen: nothing defaulted
  await page.getByLabel('Log timezone').selectOption('UTC')
  await page.getByRole('button', { name: 'Import log' }).click()
  await expect(page.getByTestId('toast-ok')).toContainText('Imported 2 rows (1 without a usable time)')
  await expect(page.getByTestId('logs-table')).toContainText('door.csv')
  expect(await serious(page)).toEqual([])

  await page.goto(`/cases/${s.caseId}/correlation`)
  await expect(page.getByTestId('no-appearance')).toContainText('No appearance, face or re-identification matching')
  await page.getByRole('button', { name: 'Generate suggestions' }).click()
  await expect(page.getByTestId('toast-ok')).toContainText('candidate link')
  const first = page.getByTestId('links-table').locator('tbody tr').first().getByRole('button').first()
  if (await first.count()) {
    await first.click()
    await page.getByLabel('Decision note').fill('checked against the timeline')
    await page.getByRole('button', { name: 'Accept link' }).click()
    await expect(page.getByTestId('toast-ok')).toContainText('accepted')
  }
  expect(await serious(page)).toEqual([])
})

test('readonly sees the layout and links but no editing, import or generate controls', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await loginAs(page, 'readonly', `/cases/${s.caseId}/correlation?tab=map`)
  await expect(page.getByTestId('nodes-table')).toContainText('cam1')
  await expect(page.getByRole('button', { name: 'Add camera' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Save camera layout' })).toHaveCount(0)
  await page.goto(`/cases/${s.caseId}/correlation?tab=logs`)
  await expect(page.getByRole('button', { name: 'Import log' })).toHaveCount(0)
  await page.goto(`/cases/${s.caseId}/correlation`)
  await expect(page.getByRole('button', { name: 'Generate suggestions' })).toHaveCount(0)
})
