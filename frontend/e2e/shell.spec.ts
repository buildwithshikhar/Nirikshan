import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { loginAs } from './fixtures'
import { ensureDemo } from './seed'

test('anonymous visitors are sent to the login screen and back to where they were headed', async ({ page }) => {
  await page.goto('/cases')
  await expect(page).toHaveURL(/\/login\?next=%2Fcases/)
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await page.getByLabel('Username').fill('demo-examiner')
  await page.getByLabel('Password').fill('demo-account-not-for-casework')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/cases$/)
  await expect(page.getByTestId('whoami')).toContainText('Examiner')
})

test('a wrong password shows an error and does not sign in', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Username').fill('demo-reviewer')
  await page.getByLabel('Password').fill('not the password')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByTestId('login-error')).toContainText('Sign-in failed')
  await expect(page.getByTestId('whoami')).toHaveCount(0)
})

test('sign out ends the session; the token no longer works', async ({ page }) => {
  await loginAs(page, 'readonly')
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page).toHaveURL(/\/login/)
  await expect(page.getByTestId('login-notice')).toContainText('signed out')
  await page.goto('/cases')
  await expect(page).toHaveURL(/\/login/)
})

test('shell: 6 nav groups, pinned case, chips, custody head with copy, role-aware nav', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await loginAs(page, 'examiner', `/cases/${s.caseId}`)
  const nav = page.getByRole('navigation', { name: 'Primary' })
  for (const g of ['Overview', 'Acquire', 'Recover', 'Analyse', 'Assure', 'System']) await expect(nav.getByText(g, { exact: true })).toBeVisible()
  await expect(page.getByTestId('pinned-case')).toContainText('DEMO-REFERENCE-001')
  await expect(page.getByTestId('chip-origin')).toContainText('Reference test data')
  await expect(page.getByTestId('chip-tz-unknown')).toBeVisible()
  await expect(page.getByTestId('chip-head')).toContainText(/[0-9a-f]{10}/)
  await expect(page.getByRole('button', { name: 'Copy custody head hash' })).toBeVisible()
  await expect(nav.getByRole('link', { name: 'Admin' })).toHaveCount(0) // examiner is not an admin
  await page.getByRole('button', { name: 'Collapse sidebar' }).click()
  await expect(page.getByRole('button', { name: 'Expand sidebar' })).toBeVisible()
  await page.getByRole('button', { name: 'Expand sidebar' }).click()
  await page.getByRole('button', { name: 'Jobs', exact: true }).click()
  await expect(page.getByTestId('jobs-drawer')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByTestId('jobs-drawer')).toHaveCount(0)
})

test('admin sees Admin; non-admin is stopped by the route guard', async ({ page }) => {
  await loginAs(page, 'admin')
  await expect(page.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: 'Admin' })).toBeVisible()
  await page.getByRole('button', { name: 'Sign out' }).click()
  await loginAs(page, 'reviewer', '/admin')
  await expect(page.getByTestId('forbidden')).toBeVisible()
})

test('axe: login screen and shell have no serious or critical violations', async ({ page, request }) => {
  await page.goto('/login')
  let r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => v.id)).toEqual([])
  const s = await ensureDemo(request)
  await loginAs(page, 'admin', `/cases/${s.caseId}`)
  await expect(page.getByTestId('chip-head')).toBeVisible()
  r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join('|')}`)).toEqual([])
})
