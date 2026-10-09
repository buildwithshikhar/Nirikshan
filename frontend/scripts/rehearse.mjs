// Rehearses docs/DEMO_RUNBOOK.md against a RUNNING `make demo`, timing every step.
//   node scripts/rehearse.mjs [--web http://localhost:5273] [--evidence /abs/path/to/image.dd]
// Prints a markdown table (step, seconds, result). Exit code 1 if a step failed.
import { chromium } from '@playwright/test'

const arg = (n, d) => { const i = process.argv.indexOf(`--${n}`); return i > 0 ? process.argv[i + 1] : d }
const WEB = arg('web', 'http://localhost:5273')
const EVIDENCE = arg('evidence', '')
const rows = []
let failed = 0

async function step(name, fn) {
  const t0 = performance.now()
  let note = 'ok'
  try {
    const r = await fn()
    if (r) note = `ok: ${r}`
  } catch (e) {
    failed++
    note = `FAILED: ${String(e.message).split('\n')[0].slice(0, 160)}`
  }
  rows.push({ name, s: ((performance.now() - t0) / 1000).toFixed(1), note })
  console.error(`${rows.at(-1).s.padStart(6)} s  ${name}  ${note}`)
}

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 } })
await ctx.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: WEB })
const page = await ctx.newPage()
page.setDefaultTimeout(60_000)
const T = (id) => page.getByTestId(id)

await step('S1 dashboard: version, ffmpeg, key id', async () => {
  await page.goto(`${WEB}/`)
  await T('ffmpeg-status').waitFor()
  return (await T('ffmpeg-status').innerText()).slice(0, 40)
})
await step('S2 origin banner + Tier B footer on the dashboard', async () => {
  await T('status-reference-data').waitFor()
  await T('tier-limit').waitFor()
})
await step('S3 /cases: type examiner name', async () => {
  await page.goto(`${WEB}/cases`)
  await page.getByLabel('Examiner name').fill('Demo Examiner (reference data)')
})
if (EVIDENCE) {
  await step('S4 acquire an image live (case 1)', async () => {
    await page.goto(`${WEB}/cases/1`)
    await page.getByPlaceholder('Source image path (server-side)').fill(EVIDENCE)
    await page.getByPlaceholder('Label').fill('Rehearsal acquisition')
    await page.getByLabel('Write blocker used').selectOption('unknown')
    await page.getByRole('button', { name: 'Acquire (read-only)' }).click()
    await page.getByRole('row').filter({ hasText: 'Rehearsal acquisition' }).getByText('acquired').first().waitFor()
  })
}
await step('S5 case page: head_hash visible, Copy works', async () => {
  await page.goto(`${WEB}/cases/1`)
  await T('head-hash').waitFor()
  await page.getByRole('button', { name: 'Copy' }).click()
  await page.getByRole('button', { name: 'Copied' }).waitFor()
})
await step('S6 custody: Verify chain and signatures', async () => {
  await page.goto(`${WEB}/cases/1/custody`)
  await page.getByRole('button', { name: 'Verify chain and signatures' }).click()
  await T('chain-result').filter({ hasText: 'CHAIN VALID' }).waitFor()
})
await step('S7 analysis page: Identify + carve (new job, wait for it to complete)', async () => {
  await page.goto(`${WEB}/evidence/1/1`)
  const before = await T('clip-clip').count()
  await page.getByRole('button', { name: 'Identify + carve' }).click()
  await T('job-progress').waitFor() // appears while the job is queued/running
  await T('job-progress').waitFor({ state: 'detached' }) // the panel goes away when the job is done
  await T('clip-clip').first().waitFor()
  return `job completed; ${await T('clip-clip').count()} clip rows (${before} before)`
})
await step('S8 parser panel: parsed/inferred/unknown chips, no-timezone, cross-check', async () => {
  await T('parser-panel').waitFor()
  await T('field-parsed').first().waitFor()
  await T('field-inferred').first().waitFor()
  await T('field-unknown').first().waitFor()
  await T('raw-timestamps').waitFor()
  await T('crosscheck').waitFor()
})
await step('S9 a clip has a video element with a served MP4', async () => {
  const src = await T('clip-video').first().getAttribute('src')
  const r = await page.request.get(WEB + src)
  if (r.status() !== 200) throw new Error(`video ${r.status()}`)
  return `${(await r.body()).length} bytes`
})
await step('S10 timeline: placed bars + unplaceable group', async () => {
  await page.goto(`${WEB}/cases/1/timeline`)
  await page.getByText('Cross-camera timeline', { exact: false }).first().waitFor()
  await T('unplaceable-item').first().waitFor()
  return `${await T('unplaceable-item').count()} unplaceable`
})
await step('S11 evidence Verify button (case page)', async () => {
  await page.goto(`${WEB}/cases/1`)
  await page.getByRole('row').filter({ hasText: 'Hikvision' }).getByRole('button', { name: 'Verify' }).click()
  await page.getByRole('row').filter({ hasText: 'Hikvision' }).getByText('verified').first().waitFor()
})
await step('S12 analytics: run objects on a clip (new run)', async () => {
  await page.goto(`${WEB}/evidence/1/1`)
  const href = await page.getByRole('link', { name: /Triage analytics/ }).first().getAttribute('href')
  await page.goto(`${WEB}${href}`)
  const before = await T('run-objects').count()
  await page.getByRole('button', { name: 'Run objects' }).click()
  await page.waitForFunction(
    (n) => document.querySelectorAll('[data-testid="run-objects"]').length > n, before)
  return await T('run-objects').first().getByTestId('run-status').innerText()
})
await step('S12b timeline: set a timezone on the raw evidence (#3) and reopen', async () => {
  await page.goto(`${WEB}/cases/1/timeline`)
  await T('status-tz-unknown').waitFor()
  const before = await T('unplaceable-item').count()
  const card = T('time-settings-3')
  await card.locator('select[aria-label="Device timezone"]').selectOption('Asia/Kolkata')
  await card.locator('input[aria-label="Timezone notes"]').fill('Rehearsal: invented note, DVR menu shows UTC+05:30')
  await card.getByRole('button', { name: 'Save time assumption' }).click()
  await card.getByTestId('tz-assumed-banner').waitFor()
  await page.goto(`${WEB}/cases/1/timeline`)
  await T('unplaceable-item').first().waitFor()
  const tzBanner = await T('status-tz-unknown').count()
  return `unplaceable ${before} -> ${await T('unplaceable-item').count()}; unknown-timezone banner count ${tzBanner}`
})
await step('S13 CSV export of the timeline', async () => {
  const r = await page.request.get(`${WEB}/api/cases/1/timeline/export?format=csv`)
  if (r.status() !== 200) throw new Error(`export ${r.status()}`)
  return `${(await r.text()).split('\n').length} lines`
})
await step('S14 generate the PDF report from the case page and download it', async () => {
  await page.goto(`${WEB}/cases/1`)
  const before = await T('report-table').locator('tbody tr').count().catch(() => 0)
  await page.getByRole('button', { name: 'Generate report' }).click()
  await page.waitForFunction(
    (n) => document.querySelectorAll('[data-testid="report-table"] tbody tr').length > n, before)
  const link = page.getByRole('link', { name: /Download PDF/ }).first()
  const href = await link.getAttribute('href')
  const r = await page.request.get(href.startsWith('http') ? href : WEB + href)
  if (r.status() !== 200) throw new Error(`download ${r.status()}`)
  return `${(await r.body()).length} bytes`
})
await browser.close()
console.log('| Step | Seconds | Result |\n|---|---|---|')
for (const r of rows) console.log(`| ${r.name} | ${r.s} | ${r.note} |`)
process.exit(failed ? 1 : 0)
