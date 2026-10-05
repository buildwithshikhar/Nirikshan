import { expect, test } from '@playwright/test'

test('dashboard loads and the API reports online', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
  await expect(page.getByText('Nirikshan').first()).toBeVisible()
  await expect(page.getByText('API online')).toBeVisible()
})
