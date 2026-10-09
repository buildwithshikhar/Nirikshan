import { defineConfig } from '@playwright/test'
import base from './playwright.config'

// `npm run screenshots`: README screenshots of the SYNTHETIC demo case (docs/img/*.png).
// Reuses the e2e servers and the demo-case global setup; a separate config so the normal
// e2e run never rewrites committed images.
export default defineConfig({
  ...base,
  testDir: './scripts',
  testMatch: 'screenshots.ts',
  workers: 1,
  use: { ...base.use, viewport: { width: 1280, height: 800 }, colorScheme: 'dark' },
})
