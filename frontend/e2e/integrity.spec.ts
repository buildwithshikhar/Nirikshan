import AxeBuilder from '@axe-core/playwright'
import { type Page, expect, test } from '@playwright/test'
import { loginAs } from './fixtures'
import { ensureDemo } from './seed'

const serious = async (page: Page) => {
  const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  return r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join('|')}`)
}

test('custody log: chain view, entry drawer, verify chain, head_hash, audit trail; old /custody URL redirects', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await loginAs(page, 'examiner', `/cases/${s.caseId}/custody`)
  await expect(page).toHaveURL(new RegExp(`/cases/${s.caseId}/integrity`))
  await expect(page.getByRole('heading', { level: 1, name: 'Custody log' })).toHaveCount(1)
  await expect(page.getByTestId('custody-table').locator('tbody tr').first()).toBeVisible()
  expect(await serious(page)).toEqual([])
  await page.getByRole('button', { name: 'Verify chain and signatures' }).click()
  await expect(page.getByTestId('chain-result')).toContainText('CHAIN VALID')
  await page.getByTestId('custody-table').locator('tbody tr').first().getByRole('button').first().click()
  await expect(page.getByTestId('detail-drawer')).toContainText('Entry hash')
  await page.keyboard.press('Escape')
  await page.getByRole('tab', { name: 'head_hash' }).click()
  await expect(page.getByTestId('head-hash')).toContainText(/[0-9a-f]{64}/)
  await expect(page.getByText('Record this value outside the system')).toBeVisible()
  await page.getByRole('tab', { name: 'Audit trail' }).click()
  await expect(page.getByTestId('audit-table')).toBeVisible()
  expect(await serious(page)).toEqual([])
})

test('verification: examiner re-hashes evidence and a clip; readonly sees no re-verify buttons', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await loginAs(page, 'examiner', `/cases/${s.caseId}/integrity/verification?tab=hash`)
  await expect(page.getByRole('heading', { level: 1, name: 'Verification' })).toHaveCount(1)
  await page.getByRole('button', { name: `Re-verify evidence ${s.hikEvidenceId}` }).click()
  await expect(page.getByTestId(`verdict-evidence-${s.hikEvidenceId}`)).toContainText('MATCH')
  await page.getByRole('button', { name: `Re-verify clip ${s.clipId}` }).click()
  await expect(page.getByTestId(`verdict-clip-${s.clipId}`)).toContainText('MATCH')
  expect(await serious(page)).toEqual([])

  await page.getByRole('button', { name: 'Sign out' }).click()
  await loginAs(page, 'readonly', `/cases/${s.caseId}/integrity/verification?tab=hash`)
  await expect(page.getByTestId('reverify-evidence')).toBeVisible()
  await expect(page.getByRole('button', { name: /Re-verify/ })).toHaveCount(0)
  await page.getByRole('tab', { name: 'Chain check' }).click()
  await page.getByRole('button', { name: 'Verify chain and signatures' }).click()
  await expect(page.getByTestId('chain-result')).toContainText('CHAIN VALID')
})
