import { execFileSync } from 'node:child_process'
import { existsSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'

// Requires: analytics router registered in the backend and models fetched
// (python scripts/fetch_models.py). Expected route: /clips/:clipId/analytics.

function ffmpegPath() {
  for (const c of ['/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg', '/usr/bin/ffmpeg']) {
    if (existsSync(c)) return c
  }
  return 'ffmpeg'
}

/** SYNTHETIC 2 s H.264 test pattern (testsrc2), not DVR footage. */
function h264Stream(): Buffer {
  return execFileSync(
    ffmpegPath(),
    ['-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=320x240:rate=25:duration=2',
      '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '1', '-g', '25',
      '-x264-params', 'scenecut=0:repeat-headers=1', '-f', 'h264', '-'],
    { maxBuffer: 64 * 1024 * 1024 },
  )
}

test('analytics: triage label, model hash, parameters and error rates beside every result', async ({
  page,
}) => {
  const dir = mkdtempSync(join(tmpdir(), 'nirikshan-e2e-analytics-'))
  const noise = Buffer.alloc(30_000, 0xab)
  const img = Buffer.concat([noise, Buffer.alloc(4096), h264Stream(), Buffer.alloc(4096), noise])
  const path = join(dir, 'synthetic_analytics.dd')
  writeFileSync(path, img)
  const number = `E2E-AN-${Date.now()}`

  await page.goto('/cases')
  await page.getByLabel('Examiner name').fill('Insp. E2E')
  await page.getByPlaceholder('Case number').fill(number)
  await page.getByPlaceholder('Title', { exact: true }).fill('Analytics case')
  await page.getByRole('button', { name: 'Create case' }).click()
  await page.getByRole('link', { name: number }).click()
  await page.getByPlaceholder('Source image path (server-side)').fill(path)
  await page.getByPlaceholder('Label').fill('Analytics image')
  await page.getByRole('button', { name: 'Acquire (read-only)' }).click()
  await expect(page.getByRole('row').filter({ hasText: 'Analytics image' })).toContainText('acquired')
  await page.getByRole('row').filter({ hasText: 'Analytics image' }).getByRole('link', { name: 'Analyze' }).click()
  await page.getByRole('button', { name: 'Identify + carve' }).click()
  const src = await page.getByTestId('clip-clip').getByTestId('clip-video').getAttribute('src')
  const clipId = /\/api\/clips\/(\d+)\/video$/.exec(src ?? '')![1]

  await page.goto(`/clips/${clipId}/analytics`)
  await expect(page.getByTestId('triage-statement')).toContainText('not identifications')

  // motion (frame differencing; a testsrc2 pattern scrolls, so intervals are expected)
  await page.getByRole('button', { name: 'Run motion' }).click()
  const motion = page.getByTestId('run-motion')
  await expect(motion.getByTestId('run-status')).toHaveText('completed')
  await expect(motion.getByTestId('triage-label')).toHaveText('triage, not identification')
  await expect(motion).toContainText('NOMINAL')
  await expect(motion.getByTestId('error-rates')).toContainText('synthetic, not representative of DVR footage')
  await expect(motion).toContainText(/clip bitstream sha256 [0-9a-f]{64}/)

  // objects and faces: model name, licence, short hash, parameters, error rates with dataset labels
  await page.getByRole('button', { name: 'Run objects' }).click()
  const objects = page.getByTestId('run-objects')
  await expect(objects.getByTestId('run-status')).toHaveText('completed')
  await expect(objects.getByTestId('model-info')).toContainText('YOLOX-Nano')
  await expect(objects.getByTestId('model-info')).toContainText('Apache-2.0')
  await expect(objects.getByTestId('model-hash')).toHaveText('c789161ed43c')
  await expect(objects.getByTestId('triage-label')).toHaveText('triage, not identification')
  await expect(objects.getByTestId('error-rates')).toContainText('Penn-Fudan')
  await expect(objects.getByTestId('error-rates')).toContainText('Nothing was validated on real DVR footage')

  await page.getByRole('button', { name: 'Run faces' }).click()
  const faces = page.getByTestId('run-faces')
  await expect(faces.getByTestId('run-status')).toHaveText('completed')
  await expect(faces.getByTestId('model-info')).toContainText('YuNet')
  await expect(faces.getByTestId('model-info')).toContainText('MIT')
  await expect(faces.getByTestId('model-hash')).toHaveText('8f2383e4dd3c')
  await expect(faces.getByTestId('error-rates')).toContainText('BioID')
  await expect(faces).not.toContainText(/identified|match(ed)? to|recogni[sz]ed as/i)

  // results persist per clip: reload shows all three runs again
  await page.reload()
  await expect(page.getByTestId('run-motion')).toBeVisible()
  await expect(page.getByTestId('run-objects')).toBeVisible()
  await expect(page.getByTestId('run-faces')).toBeVisible()
})
