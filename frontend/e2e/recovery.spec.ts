import AxeBuilder from '@axe-core/playwright'
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { existsSync, mkdtempSync, realpathSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { loginAs } from './fixtures'
import { apiLogin, ensureDemo } from './seed'

async function axe(page: Page) {
  const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join('|')}`)).toEqual([])
}

test('run console shows the latest run, vendor tier, clips; axe', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await loginAs(page, 'examiner', `/cases/${s.caseId}/recovery?evidence=${s.hikEvidenceId}`)
  await expect(page.getByRole('heading', { level: 1, name: 'Recovery lab' })).toBeVisible()
  const vendor = page.getByTestId('vendor-section')
  await expect(vendor).toContainText('Hikvision')
  await expect(vendor).toContainText('Tier B')
  await expect(page.getByRole('link', { name: `Clip ${s.clipId}` })).toBeVisible()
  await axe(page)
})

test('clip detail: six tabs, parsed/inferred/unknown chips, drawer, player, recovery limits state 0.44', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await loginAs(page, 'examiner', `/cases/${s.caseId}/recovery/clips/${s.clipId}`)
  await expect(page.getByRole('heading', { level: 1 })).toContainText(`Clip ${s.clipId}`)
  for (const t of ['Parser results', 'Generic carving', 'Cross-check', 'Player', 'Bitstream and hash info', 'Recovery limits'])
    await expect(page.getByRole('tab', { name: t })).toBeVisible()
  await expect(page.getByTestId('field-parsed').first()).toBeVisible()
  await expect(page.getByTestId('raw-timestamps')).toContainText('timezone: not assumed')
  await axe(page)
  await page.getByRole('button', { name: 'Tier and confidence' }).click()
  await expect(page.getByTestId('detail-drawer')).toContainText('Tier B')
  await page.keyboard.press('Escape')
  await page.getByRole('tab', { name: 'Cross-check' }).click()
  await expect(page.getByTestId('crosscheck')).toContainText('parser clips')
  await page.getByRole('tab', { name: 'Player' }).click()
  await expect(page.getByTestId('clip-video')).toHaveAttribute('src', new RegExp(`/api/clips/${s.clipId}/video$`))
  await page.getByRole('button', { name: 'Verify clip hash' }).click()
  await expect(page.getByTestId('toast-ok').filter({ hasText: 'matches' })).toBeVisible()
  await expect(page.getByText('triage, not identification')).toBeVisible()
  await page.getByRole('tab', { name: 'Bitstream and hash info' }).click()
  await expect(page.getByText(/[0-9a-f]{64}/).first()).toBeVisible()
  await page.getByRole('tab', { name: 'Recovery limits' }).click()
  await expect(page.getByTestId('recoverability')).toContainText('ROUGH ESTIMATE')
  await expect(page.getByTestId('agreement-note')).toContainText('0.44')
  await axe(page)
})

test('orphans and failed decodes screen; readonly cannot start an analysis', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await loginAs(page, 'readonly', `/cases/${s.caseId}/recovery/orphans?evidence=${s.rawEvidenceId}`)
  await expect(page.getByRole('heading', { level: 1, name: 'Orphans and failed decodes' })).toBeVisible()
  await expect(page.locator('table, [data-testid="empty-state"]').first()).toBeVisible()
  await axe(page)
  await page.goto(`/cases/${s.caseId}/recovery?evidence=${s.hikEvidenceId}`)
  await expect(page.getByRole('button', { name: 'Identify + carve' })).toBeDisabled()
})

const job = (over: Record<string, unknown>) => ({
  id: 901, kind: 'analyze', case_id: 1, evidence_id: 1, params: {}, status: 'running', active: true,
  cancel_requested: false, progress: 0.4, stage: 'Generic carving and exporting clips', run_id: null,
  clips_recorded: 0, error: '', examiner: 'x', created_at: '', started_at: '', finished_at: '',
  ...over,
})

// Progress / cancel UI against a mocked job API (the real job runs end to end in the carve tests below).
test('progress bar, stage text and Cancel; cancelled state explains the partial run', async ({ page, request }) => {
  const s = await ensureDemo(request)
  let cancelled = false
  await page.route('**/api/evidence/*/jobs/analyze', (r) => r.fulfill({ status: 202, json: job({ existing: false }) }))
  await page.route('**/api/jobs/901/cancel', (r) => {
    cancelled = true
    return r.fulfill({ status: 202, json: job({ status: 'cancelling', cancel_requested: true }) })
  })
  await page.route('**/api/jobs/901', (r) =>
    r.fulfill({ json: cancelled ? job({ status: 'cancelled', active: false, progress: 0.5, run_id: 7, clips_recorded: 2, stage: 'Cancelled' }) : job({}) }),
  )
  await loginAs(page, 'examiner', `/cases/${s.caseId}/recovery?evidence=${s.hikEvidenceId}`)
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

test('a failed job is shown as an alert', async ({ page, request }) => {
  const s = await ensureDemo(request)
  await page.route('**/api/evidence/*/jobs/analyze', (r) => r.fulfill({ status: 202, json: job({ id: 902 }) }))
  await page.route('**/api/jobs/902', (r) => r.fulfill({ json: job({ id: 902, status: 'failed', active: false, error: 'RuntimeError: simulated' }) }))
  await loginAs(page, 'examiner', `/cases/${s.caseId}/recovery?evidence=${s.dahuaEvidenceId}`)
  await page.getByRole('button', { name: 'Identify + carve' }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'simulated' })).toBeVisible({ timeout: 10_000 })
})

// ---- ported from the legacy smoke spec: real background job on synthetic images ----
function ffmpegPath() {
  for (const c of ['/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg', '/usr/bin/ffmpeg']) if (existsSync(c)) return c
  return 'ffmpeg'
}
/** SYNTHETIC 2 s H.264 test pattern (testsrc2), not DVR footage. */
function h264Stream(): Buffer {
  return execFileSync(
    ffmpegPath(),
    ['-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=320x240:rate=25:duration=2', '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '1', '-g', '25', '-x264-params', 'scenecut=0:repeat-headers=1', '-f', 'h264', '-'],
    { maxBuffer: 64 * 1024 * 1024 },
  )
}
/** SYNTHETIC per-paper DHAV layout (FFmpeg dhav.c fields), not a real device image. */
function dhavFrames(stream: Buffer, channel: number): Buffer {
  const starts: number[] = []
  for (let i = 0; i + 3 < stream.length; i++) if (stream[i] === 0 && stream[i + 1] === 0 && stream[i + 2] === 1) starts.push(i > 0 && stream[i - 1] === 0 ? i - 1 : i)
  const frames: Buffer[] = []
  let au = starts[0]
  let n = 1000
  for (let k = 0; k < starts.length; k++) {
    const end = k + 1 < starts.length ? starts[k + 1] : stream.length
    const hdr = stream[starts[k] + (stream[starts[k]] === 0 && stream[starts[k] + 1] === 0 && stream[starts[k] + 2] === 0 ? 4 : 3)]
    const type = hdr & 0x1f
    if (type !== 1 && type !== 5) continue
    const payload = stream.subarray(au, end)
    const key = type === 5
    const ext = key ? Buffer.from([0x82, 0, 0, 0, 0x40, 0x01, 0xf0, 0x00, 0x81, 0, 0x08, 25]) : Buffer.alloc(0)
    const length = 24 + ext.length + payload.length + 8
    const h = Buffer.alloc(24)
    h.write('DHAV', 0, 'ascii')
    h[4] = key ? 0xfd : 0xfc
    h[6] = channel
    h.writeUInt32LE(n++, 8)
    h.writeUInt32LE(length, 12)
    h.writeUInt32LE((25 << 26) | (6 << 22) | (1 << 17) | (12 << 12), 16)
    h[22] = ext.length
    const trailer = Buffer.alloc(8)
    trailer.write('dhav', 0, 'ascii')
    trailer.writeUInt32LE(length - 8, 4)
    frames.push(Buffer.concat([h, ext, payload, trailer]))
    au = end
  }
  return Buffer.concat(frames)
}

/** Creates a case and acquires the images over the API (the UI flows are covered in the evidence spec). */
async function caseWith(request: APIRequestContext, name: string, images: [string, Buffer][]) {
  const headers = await apiLogin(request, 'examiner')
  const dir = mkdtempSync(join(realpathSync(tmpdir()), 'nirikshan-e2e-rec-'))
  const kase = (await (await request.post('/api/cases', { headers, data: { case_number: `E2E-${name}-${Date.now()}`, title: name, description: '' } })).json()) as { id: number }
  const ids: number[] = []
  for (const [label, buf] of images) {
    const path = join(dir, `${label.replace(/\W/g, '_')}.dd`)
    writeFileSync(path, buf)
    const ev = (await (await request.post(`/api/cases/${kase.id}/evidence`, { headers, data: { source_path: path, label, write_blocker: 'yes' } })).json()) as { id: number }
    ids.push(ev.id)
  }
  return { caseId: kase.id, ids }
}

test('identify + carve: vendor signature, clip, hashes, damaged clip listed in Orphans and failed decodes', async ({ page, request }) => {
  const stream = h264Stream()
  const noise = Buffer.alloc(30_000, 0xab)
  const prefix = Buffer.alloc(0x200 + 18 + 4096, 0xcd)
  prefix.write('HIKVISION@HANGZHOU', 0x200, 'ascii') // SYNTHETIC per-paper signature, not a real device
  const good = Buffer.concat([prefix, Buffer.alloc(4096), stream, Buffer.alloc(4096), noise])
  const damaged = Buffer.from(stream)
  Buffer.alloc(600, 0x5a).copy(damaged, 5000)
  const bad = Buffer.concat([noise, Buffer.alloc(4096), damaged, Buffer.alloc(4096)])
  const { caseId, ids } = await caseWith(request, 'carve', [['Good image', good], ['Damaged image', bad]])
  await loginAs(page, 'examiner', `/cases/${caseId}/recovery?evidence=${ids[0]}`)
  await page.getByRole('button', { name: 'Identify + carve' }).click()
  const vendor = page.getByTestId('vendor-section')
  await expect(vendor).toContainText('Hikvision', { timeout: 60_000 })
  await expect(vendor).toContainText('Tier B')
  await expect(vendor).toContainText('medium')
  await expect(page.getByTestId('decode-status')).toHaveText('ok')
  await page.getByRole('link', { name: /^Clip \d+/ }).click()
  await page.getByRole('tab', { name: 'Bitstream and hash info' }).click()
  await expect(page.getByText(/[0-9a-f]{64}/).first()).toBeVisible()
  await expect(page.getByText('50 frames')).toBeVisible()
  await page.getByRole('tab', { name: 'Player' }).click()
  const src = await page.getByTestId('clip-video').getAttribute('src')
  expect(src).toMatch(/\/api\/clips\/\d+\/video$/)
  // Browser playback itself is not asserted: Playwright's Chromium ships without H.264.
  await page.getByRole('button', { name: 'Verify clip hash' }).click()
  await expect(page.getByTestId('toast-ok').filter({ hasText: 'matches' })).toBeVisible()

  // damaged image: the failed decode is listed with its errors, not hidden
  await page.goto(`/cases/${caseId}/recovery?evidence=${ids[1]}`)
  await page.getByRole('button', { name: 'Identify + carve' }).click()
  await expect(page.getByTestId('vendor-section')).toContainText('Unknown vendor', { timeout: 60_000 })
  await page.goto(`/cases/${caseId}/recovery/orphans?evidence=${ids[1]}`)
  const row = page.getByRole('row').filter({ hasText: 'decode_errors' }).first()
  await expect(row).toBeVisible()
  await expect(row).toContainText(/error|invalid|concealed|corrupt|missing|decode/i)
})

test('Dahua parser: tier, parsed/inferred/unknown fields, raw timestamps, cross-check, channel', async ({ page, request }) => {
  const img = Buffer.concat([Buffer.alloc(4096, 0xab), dhavFrames(h264Stream(), 3), Buffer.alloc(4096)])
  const { caseId, ids } = await caseWith(request, 'dhav', [['DHAV-like image', img]])
  await loginAs(page, 'examiner', `/cases/${caseId}/recovery?evidence=${ids[0]}`)
  await page.getByLabel('Parser options').fill('{"Dahua": {"frame_gap_tolerance": 5}}')
  await page.getByRole('button', { name: 'Identify + carve' }).click()
  await expect(page.getByTestId('vendor-section')).toContainText('Dahua', { timeout: 60_000 })
  await expect(page.getByTestId('clip-engine')).toHaveText('Dahua')
  await expect(page.getByText('ch 3')).toBeVisible()
  await page.getByRole('link', { name: /^Clip \d+/ }).click()
  await expect(page.getByTestId('parser-status')).toHaveText('parsed')
  await expect(page.getByTestId('field-parsed').first()).toBeVisible()
  await expect(page.getByTestId('raw-timestamps')).toContainText('timezone: not assumed')
  await page.getByRole('tab', { name: 'Cross-check' }).click()
  await expect(page.getByTestId('crosscheck')).toContainText('1 parser clips')
})
