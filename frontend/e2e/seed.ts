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

export const DEMO_PASSWORD = 'demo-account-not-for-casework'
export type DemoRole = 'admin' | 'examiner' | 'reviewer' | 'readonly'

/** Demo accounts are created by `python -m app.demo_data seed-users` (global setup); this logs one in over the API. */
export async function apiLogin(request: APIRequestContext, role: DemoRole = 'examiner') {
  const res = await request.post('/api/auth/login', { data: { username: `demo-${role}`, password: DEMO_PASSWORD } })
  const body = (await res.json()) as { token: string }
  return { Authorization: `Bearer ${body.token}` }
}

/** Builds the reference-data demo case (scripts/demo.py --data-only) in the running e2e backend, once. */
export async function ensureDemo(request: APIRequestContext): Promise<Seeded> {
  const headers = await apiLogin(request, 'examiner')
  const find = async () => {
    const cases = (await (await request.get('/api/cases', { headers })).json()) as { id: number; case_number: string }[]
    return cases.find((c) => c.case_number === 'DEMO-REFERENCE-001')
  }
  let kase = await find()
  if (!kase) {
    const dir = join(mkdtempSync(join(realpathSync(tmpdir()), 'nirikshan-e2e-demo-')), 'evidence')
    const api = `http://localhost:${process.env.API_PORT ?? 8010}`
    execFileSync(
      '../backend/.venv/bin/python',
      ['../scripts/demo.py', '--data-only', '--api-url', api, '--evidence-dir', dir],
      { env: { ...process.env, DATABASE_URL: process.env.E2E_DATABASE_URL ?? 'sqlite:///./e2e.db', PATH: `/opt/homebrew/bin:/usr/local/bin:${process.env.PATH ?? ''}` }, stdio: 'pipe' },
    )
    kase = await find()
  }
  const id = kase!.id
  const evidence = (await (await request.get(`/api/cases/${id}/evidence`, { headers })).json()) as {
    id: number
    label: string
  }[]
  const byLabel = (s: string) => evidence.find((e) => e.label.includes(s))!.id
  const hik = byLabel('Hikvision')
  const runs = (await (await request.get(`/api/evidence/${hik}/runs`, { headers })).json()) as {
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
