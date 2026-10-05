import { execFileSync } from 'node:child_process'
import { existsSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'

test('dashboard loads and the API reports online', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
  await expect(page.getByText('API online')).toBeVisible()
  await expect(page.getByTestId('ffmpeg-status')).toBeVisible()
})

test('create case -> acquire -> verify evidence -> verify custody chain', async ({ page }) => {
  const dir = mkdtempSync(join(tmpdir(), 'nirikshan-e2e-'))
  const src = join(dir, 'synthetic.dd') // synthetic bytes, not a real DVR image
  writeFileSync(src, Buffer.alloc(300_000, 7))
  const number = `E2E-${Date.now()}`

  await page.goto('/cases')
  await page.getByLabel('Examiner name').fill('Insp. E2E')
  await page.getByPlaceholder('Case number').fill(number)
  await page.getByPlaceholder('Title', { exact: true }).fill('E2E case')
  await page.getByRole('button', { name: 'Create case' }).click()
  await page.getByRole('link', { name: number }).click()

  await page.getByPlaceholder('Source image path (server-side)').fill(src)
  await page.getByPlaceholder('Label').fill('Synthetic HDD')
  await page.getByLabel('Write blocker used').selectOption('yes')
  await page.getByRole('button', { name: 'Acquire (read-only)' }).click()
  const row = page.getByRole('row').filter({ hasText: 'Synthetic HDD' })
  await expect(row).toContainText('acquired')
  await expect(row).toContainText(/SHA-256 [0-9a-f]{64}/)
  await expect(page.getByTestId('head-hash')).toContainText(/[0-9a-f]{64}/)
  await row.getByRole('button', { name: 'Verify' }).click()
  await expect(row).toContainText('verified')

  await page.getByRole('link', { name: 'Custody log →' }).click()
  await expect(page.getByRole('cell', { name: 'evidence_acquired' })).toBeVisible()
  await expect(page.getByTestId('head-hash')).toContainText(/[0-9a-f]{64}/)
  await page.getByRole('button', { name: 'Verify chain and signatures' }).click()
  await expect(page.getByTestId('chain-result')).toContainText('CHAIN VALID')
})

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

test('identify + carve: vendor signature, clip offsets/hashes, preview, damaged clip listed', async ({
  page,
  request,
}) => {
  const dir = mkdtempSync(join(tmpdir(), 'nirikshan-e2e-carve-'))
  const stream = h264Stream()
  const noise = Buffer.alloc(30_000, 0xab) // no zero runs, so no start codes
  const prefix = Buffer.alloc(0x200 + 18 + 4096, 0xcd)
  prefix.write('HIKVISION@HANGZHOU', 0x200, 'ascii') // SYNTHETIC per-paper signature, not a real device
  const good = Buffer.concat([prefix, Buffer.alloc(4096), stream, Buffer.alloc(4096), noise])
  const damaged = Buffer.from(stream)
  Buffer.alloc(600, 0x5a).copy(damaged, 5000)
  const bad = Buffer.concat([noise, Buffer.alloc(4096), damaged, Buffer.alloc(4096)])
  const goodPath = join(dir, 'synthetic_good.dd')
  const badPath = join(dir, 'synthetic_damaged.dd')
  writeFileSync(goodPath, good)
  writeFileSync(badPath, bad)
  const number = `E2E-CARVE-${Date.now()}`

  await page.goto('/cases')
  await page.getByLabel('Examiner name').fill('Insp. E2E')
  await page.getByPlaceholder('Case number').fill(number)
  await page.getByPlaceholder('Title', { exact: true }).fill('Carve case')
  await page.getByRole('button', { name: 'Create case' }).click()
  await page.getByRole('link', { name: number }).click()

  for (const [label, path] of [['Good image', goodPath], ['Damaged image', badPath]]) {
    await page.getByPlaceholder('Source image path (server-side)').fill(path)
    await page.getByPlaceholder('Label').fill(label)
    await page.getByRole('button', { name: 'Acquire (read-only)' }).click()
    await expect(page.getByRole('row').filter({ hasText: label })).toContainText('acquired')
  }

  // good image: vendor evidence + one clean clip with hashes and a served MP4
  await page.getByRole('row').filter({ hasText: 'Good image' }).getByRole('link', { name: 'Analyze' }).click()
  await page.getByRole('button', { name: 'Identify + carve' }).click()
  const vendor = page.getByTestId('vendor-section')
  await expect(vendor).toContainText('Hikvision')
  await expect(vendor).toContainText('Tier B')
  await expect(vendor).toContainText('medium')
  await expect(vendor).toContainText('0x200')
  const clipRow = page.getByTestId('clip-clip')
  await expect(clipRow).toHaveCount(1)
  await expect(clipRow).toContainText(/bitstream [0-9a-f]{64}/)
  await expect(clipRow).toContainText(/mp4 [0-9a-f]{64}/)
  await expect(clipRow.getByTestId('decode-status')).toHaveText('ok')
  await expect(clipRow).toContainText('50 frames')
  const src = await clipRow.getByTestId('clip-video').getAttribute('src')
  expect(src).toMatch(/\/api\/clips\/\d+\/video$/)
  const video = await request.get(src!)
  expect(video.status()).toBe(200)
  expect(video.headers()['content-type']).toBe('video/mp4')
  // Browser playback itself is not asserted: Playwright's Chromium ships without H.264.
  await clipRow.getByRole('button', { name: 'Verify MP4 hash' }).click()
  await expect(page.getByText('matches the carve-time hash')).toBeVisible()

  // damaged image: the failed decode is listed with its errors, not hidden
  await page.getByRole('link', { name: '← Case' }).click()
  await page.getByRole('row').filter({ hasText: 'Damaged image' }).getByRole('link', { name: 'Analyze' }).click()
  await page.getByRole('button', { name: 'Identify + carve' }).click()
  await expect(page.getByTestId('vendor-section')).toContainText('Unknown vendor')
  const badClip = page.getByTestId('clip-clip').first()
  await expect(badClip.getByTestId('decode-status')).toHaveText('decode_errors')
  await expect(badClip).toContainText(/error|invalid|concealed|corrupt|missing|decode/i)
})
