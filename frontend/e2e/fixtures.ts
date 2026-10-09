import { type Page, expect } from '@playwright/test'
import { DEMO_PASSWORD, type DemoRole } from './seed'

/** Signs in through the real login screen as one of the demo accounts (created by `make demo` and
 * the e2e global setup). Lands on `next` (default: the dashboard). */
export async function loginAs(page: Page, role: DemoRole = 'examiner', next = '/') {
  await page.goto(`/login?next=${encodeURIComponent(next)}`)
  await page.getByLabel('Username').fill(`demo-${role}`)
  await page.getByLabel('Password').fill(DEMO_PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByTestId('whoami')).toBeVisible()
}

export { DEMO_PASSWORD }
