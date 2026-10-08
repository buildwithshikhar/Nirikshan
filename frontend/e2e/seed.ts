import { execFileSync } from 'node:child_process'
import { mkdtempSync, realpathSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { APIRequestContext } from '@playwright/test'

export interface Seeded {
  caseId: number
  evidence: { id: number; label: string }[]
  hikEvidenceId: number
  dahuaEvidenceId: number
  rawEvidenceId: number
  clipId: number
}

/** Builds the SYNTHETIC demo case (scripts/demo.py --data-only) in the running e2e backend, once. */
export async function ensureDemo(request: APIRequestContext): Promise<Seeded> {
  const find = async () => {
    const cases = (await (await request.get('/api/cases')).json()) as { id: number; case_number: string }[]
    return cases.find((c) => c.case_number === 'DEMO-SYNTHETIC-001')
  }
  let kase = await find()
  if (!kase) {
    const dir = join(mkdtempSync(join(realpathSync(tmpdir()), 'nirikshan-e2e-demo-')), 'evidence')
    const api = `http://localhost:${process.env.API_PORT ?? 8010}`
    execFileSync(
      '../backend/.venv/bin/python',
      ['../scripts/demo.py', '--data-only', '--api-url', api, '--evidence-dir', dir],
      { env: { ...process.env, PATH: `/opt/homebrew/bin:/usr/local/bin:${process.env.PATH ?? ''}` }, stdio: 'pipe' },
    )
    kase = await find()
  }
  const id = kase!.id
  const evidence = (await (await request.get(`/api/cases/${id}/evidence`)).json()) as {
    id: number
    label: string
  }[]
  const byLabel = (s: string) => evidence.find((e) => e.label.includes(s))!.id
  const hik = byLabel('Hikvision')
  const runs = (await (await request.get(`/api/evidence/${hik}/runs`)).json()) as {
    clips: { id: number; kind: string; has_video: boolean }[]
  }[]
  const clip = runs[0].clips.find((c) => c.kind === 'clip' && c.has_video)!
  return {
    caseId: id,
    evidence,
    hikEvidenceId: hik,
    dahuaEvidenceId: byLabel('Dahua'),
    rawEvidenceId: byLabel('raw'),
    clipId: clip.id,
  }
}
