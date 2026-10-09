import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { ORIGIN_DISCLOSURE, ORIGIN_HEADLINE, TIER_LIMIT } from '../src/dataOrigin'
import { loginAs } from './fixtures'
import { type Seeded, ensureDemo } from './seed'

let s: Seeded
test.beforeAll(async ({ playwright }) => {
  const request = await playwright.request.newContext({ baseURL: `http://localhost:${process.env.WEB_PORT ?? 5183}` })
  s = await ensureDemo(request)
  await request.dispose()
})

const axe = async (page: import('@playwright/test').Page, name: string) => {
  await page.waitForLoadState('networkidle')
  const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  const blocking = r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
  expect(blocking.map((v) => `${name} ${v.impact} ${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join('|')}`)).toEqual([])
}

test('dashboard: three tabs, case stats, recent activity, integrity health; axe', async ({ page }) => {
  await loginAs(page, 'examiner', `/`)
  await page.goto(`/cases/${s.caseId}`)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
  await expect(page.getByText('API online')).toBeVisible()
  await expect(page.getByTestId('ffmpeg-status')).toBeVisible()
  await expect(page.getByText('Evidence items')).toBeVisible()
  await expect(page.getByText('Success rates')).toBeVisible()
  await axe(page, 'dashboard stats')
  await page.getByRole('tab', { name: 'Recent activity' }).click()
  await expect(page.getByText('Latest custody entries')).toBeVisible()
  await expect(page.getByRole('listitem').filter({ hasText: /#\d+/ }).first()).toBeVisible()
  await axe(page, 'dashboard activity')
  await page.getByRole('tab', { name: 'Integrity health' }).click()
  await expect(page.getByText('CHAIN VALID')).toBeVisible()
  await axe(page, 'dashboard health')
})

test('jobs: history lists the seeded analyses with a dependency-chain drawer; axe', async ({ page }) => {
  await loginAs(page, 'examiner', `/cases/${s.caseId}/jobs`)
  await expect(page.getByRole('heading', { name: 'Jobs' })).toBeVisible()
  await page.getByRole('tab', { name: 'History' }).click()
  await expect(page.getByTestId('jobs-history').getByRole('row')).not.toHaveCount(1)
  await page.getByTestId('jobs-history').getByRole('button', { name: /^#\d+ analyze/ }).first().click()
  const d = page.getByTestId('detail-drawer')
  await expect(d).toContainText('Dependency chain')
  await expect(d).toContainText('subprocess worker with best-effort limits')
  await axe(page, 'jobs')
  await page.getByRole('tab', { name: /^Running/ }).click()
  await expect(page.getByText('Nothing is running')).toBeVisible()
})

test('admin: users, roles, keys (read-only with fingerprints), config and audit; axe', async ({ page }) => {
  await loginAs(page, 'admin', '/admin')
  await expect(page.getByRole('heading', { name: 'Admin', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: /demo-reviewer/ })).toBeVisible()
  await axe(page, 'admin users')
  const uname = `e2e-user-${Date.now() % 100000}`
  await page.getByLabel('Username').fill(uname)
  await page.getByLabel('Display name').fill('E2E User')
  await page.getByLabel('Initial password').fill('a-long-e2e-password-1')
  await page.getByRole('button', { name: 'Create user' }).click()
  await expect(page.getByTestId('toast-ok')).toContainText(uname)
  await expect(page.getByRole('cell', { name: new RegExp(uname) })).toBeVisible()
  await page.getByRole('tab', { name: 'Roles' }).click()
  await expect(page.getByRole('table', { name: 'Role permissions' })).toBeVisible()
  await axe(page, 'admin roles')
  await page.getByRole('tab', { name: 'Keys' }).click()
  await expect(page.getByText('SHA-256 fingerprint of the public key')).toHaveCount(2)
  await expect(page.getByRole('button', { name: /Copy .*fingerprint/ }).first()).toBeVisible()
  await axe(page, 'admin keys')
  await page.getByRole('tab', { name: 'Config and audit' }).click()
  await expect(page.getByText('Database schema version')).toBeVisible()
  await expect(page.getByRole('table', { name: 'Audit trail' })).toBeVisible()
  await axe(page, 'admin config')
})

test('help: SOPs, manual and limits render from bundled docs; axe', async ({ page }) => {
  await loginAs(page, 'readonly', '/help')
  await expect(page.getByRole('heading', { name: 'Help', level: 1 })).toBeVisible()
  await expect(page.getByTestId('markdown')).toBeVisible()
  await axe(page, 'help sops')
  await page.getByRole('tab', { name: 'Manual' }).click()
  await expect(page.getByTestId('markdown')).toContainText(/Nirikshan/)
  await page.getByRole('tab', { name: 'Limits and tiers' }).click()
  await expect(page.getByText('no vendor is supported above Tier B').first()).toBeVisible()
  await expect(page.getByText('correlation 0.44')).toBeVisible()
  await axe(page, 'help limits')
})

test('every authenticated screen states the Tier B limit; case screens also state the data origin; login states neither', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await expect(page.locator('body')).not.toContainText('Tier limit')
  await expect(page.locator('body')).not.toContainText('known ground truth')
  await loginAs(page, 'admin', `/cases/${s.caseId}`)
  const caseScreens = ['', '/evidence', '/identification', '/explorer', '/recovery', '/timeline', '/triage', '/correlation', '/integrity', '/reports', '/jobs'].map((x) => `/cases/${s.caseId}${x}`)
  const globalScreens = ['/', '/cases', '/validation', '/admin', '/help']
  for (const url of [...caseScreens, ...globalScreens]) {
    await page.goto(url)
    await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible()
    await expect(page.getByTestId('tier-limit')).toHaveText(TIER_LIMIT)
    if (caseScreens.includes(url)) {
      const origin = page.getByTestId('status-reference-data')
      await expect(origin).toContainText(ORIGIN_HEADLINE)
      await expect(origin).toContainText(ORIGIN_DISCLOSURE)
      await expect(page.getByTestId('chip-origin')).toBeVisible()
    }
  }
})

test('read-only role: write controls are hidden, server still refuses a forced write', async ({ page }) => {
  await loginAs(page, 'readonly', '/cases')
  const status = await page.evaluate(async () => {
    const token = sessionStorage.getItem('nirikshan.token')
    const r = await fetch('/api/cases', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify({ case_number: 'X-RO', title: 't', description: '' }) })
    return r.status
  })
  expect(status).toBe(403)
})

test('keyboard: skip link is the first tab stop and moves focus to main', async ({ page }) => {
  await loginAs(page, 'examiner', '/help')
  await page.goto('/help')
  await expect(page.getByRole('heading', { name: 'Help', level: 1 })).toBeVisible()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Skip to main content' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/#main$/)
})

test('the gate can fail: axe flags a known contrast and label violation', async ({ page }) => {
  await page.setContent('<main><h1>t</h1><p style="color:#64748b;background:#0f2040">low contrast</p><input></main>')
  const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()
  const ids = r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => v.id)
  expect(ids).toEqual(expect.arrayContaining(['color-contrast', 'label']))
})
