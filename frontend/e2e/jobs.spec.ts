import { expect, test } from '@playwright/test'
import { ensureDemo } from './seed'

const job = (over: Record<string, unknown>) => ({
  id: 901, kind: 'analyze', case_id: 1, evidence_id: 1, params: {}, status: 'running', active: true,
  cancel_requested: false, progress: 0.4, stage: 'Generic carving and exporting clips', run_id: null,
  clips_recorded: 0, error: '', examiner: 'x', created_at: '', started_at: '', finished_at: '',
  ...over,
})

// The progress / cancel UI against a mocked job API (the real cancel path is covered by the
// backend tests; the real job end to end by the other specs, which analyze through the UI).
test('progress bar, stage text and Cancel; cancelled state explains the partial run', async ({ page, playwright }) => {
  const request = await playwright.request.newContext({ baseURL: `http://localhost:${process.env.WEB_PORT ?? 5183}` })
  const s = await ensureDemo(request)
  await request.dispose()
  let cancelled = false
  await page.route('**/api/evidence/*/jobs/analyze', (r) => r.fulfill({ status: 202, json: job({ existing: false }) }))
  await page.route('**/api/jobs/901/cancel', (r) => {
    cancelled = true
    return r.fulfill({ status: 202, json: job({ status: 'cancelling', cancel_requested: true }) })
  })
  await page.route('**/api/jobs/901', (r) =>
    r.fulfill({
      json: cancelled
        ? job({ status: 'cancelled', active: false, progress: 0.5, run_id: 7, clips_recorded: 2, stage: 'Cancelled' })
        : job({}),
    }),
  )
  await page.goto(`/evidence/${s.caseId}/${s.hikEvidenceId}`)
  await page.getByLabel('Examiner name').fill('Insp. E2E')
  await page.getByRole('button', { name: 'Identify + carve' }).click()
  const box = page.getByTestId('job-progress')
  await expect(box.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '40')
  await expect(box.getByTestId('job-stage')).toContainText('Generic carving')
  await expect(page.getByRole('button', { name: 'Analyzing…' })).toBeDisabled()
  await box.getByTestId('job-cancel').click()
  await expect(page.getByTestId('analysis-note')).toContainText('Analysis cancelled', { timeout: 10_000 })
  await expect(page.getByTestId('analysis-note')).toContainText('2 clip(s) were fully recorded')
  await expect(page.getByTestId('job-progress')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Identify + carve' })).toBeEnabled()
})

test('a failed job is shown as an alert', async ({ page, playwright }) => {
  const request = await playwright.request.newContext({ baseURL: `http://localhost:${process.env.WEB_PORT ?? 5183}` })
  const s = await ensureDemo(request)
  await request.dispose()
  await page.route('**/api/evidence/*/jobs/analyze', (r) => r.fulfill({ status: 202, json: job({ id: 902 }) }))
  await page.route('**/api/jobs/902', (r) =>
    r.fulfill({ json: job({ id: 902, status: 'failed', active: false, error: 'RuntimeError: simulated' }) }),
  )
  await page.goto(`/evidence/${s.caseId}/${s.dahuaEvidenceId}`)
  await page.getByLabel('Examiner name').fill('Insp. E2E')
  await page.getByRole('button', { name: 'Identify + carve' }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'simulated' })).toBeVisible({ timeout: 10_000 })
})
