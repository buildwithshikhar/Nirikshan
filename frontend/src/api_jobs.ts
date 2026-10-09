import { API_URL, authFetch } from './lib/http'

export type JobStatus = 'queued' | 'running' | 'cancelling' | 'cancelled' | 'failed' | 'completed'

export interface Job {
  id: number
  kind: string
  case_id: number
  evidence_id: number
  params: Record<string, unknown>
  status: JobStatus
  active: boolean
  cancel_requested: boolean
  progress: number
  stage: string
  run_id: number | null
  clips_recorded: number
  error: string
  examiner: string
  created_at: string
  started_at: string
  finished_at: string
  existing?: boolean
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await authFetch(`${API_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!res.ok) {
    let detail = await res.text()
    try {
      const d = JSON.parse(detail).detail ?? detail
      detail = typeof d === 'string' ? d : JSON.stringify(d)
    } catch {
      // keep raw text
    }
    throw new Error(detail)
  }
  return res.json()
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
  })

export interface JobWithDeps extends Job {
  depends_on?: number | null
  batch_id?: string | null
  retry_of?: number | null
  [k: string]: unknown
}

export const apiJobs = {
  list: (caseId: number, q = '') => request<JobWithDeps[]>(`/api/cases/${caseId}/jobs${q}`),
  retry: (id: number) => post<Job>(`/api/jobs/${id}/retry`),
  submitAnalyze: (evidenceId: number, b: { join_gap: number; parser_options: Record<string, unknown> }) =>
    post<Job>(`/api/evidence/${evidenceId}/jobs/analyze`, b),
  get: (id: number) => request<Job>(`/api/jobs/${id}`),
  active: (caseId: number, evidenceId: number) =>
    request<Job[]>(`/api/cases/${caseId}/jobs?evidence_id=${evidenceId}&active=true`),
  cancel: (id: number) => post<Job>(`/api/jobs/${id}/cancel`),
}
