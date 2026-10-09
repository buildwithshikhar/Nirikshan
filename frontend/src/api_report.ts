// Report API (P7). Same request()/post pattern and X-Examiner header as src/api.ts.
import { API_URL, authFetch } from './lib/http'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await authFetch(`${API_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!res.ok) {
    let detail = await res.text()
    try {
      detail = JSON.parse(detail).detail ?? detail
    } catch {
      // keep raw text
    }
    throw new Error(String(detail))
  }
  return res.status === 204 ? (undefined as T) : res.json()
}

export interface ReportRow {
  id: number
  case_id: number
  file_name: string
  sha256: string
  size_bytes: number
  pages: number
  content_hash: string
  head_hash_before: string
  chain_ok: boolean
  generated_at: string
  examiner: string
  custody_seq: number | null
}

export const reportApi = {
  list: (caseId: number) => request<ReportRow[]>(`/api/cases/${caseId}/reports`),
  generate: (caseId: number) =>
    request<ReportRow>(`/api/cases/${caseId}/report`, {
      method: 'POST',
    }),
  downloadUrl: (reportId: number) => `${API_URL}/api/reports/${reportId}/download`,
  certificateUrl: (caseId: number, evidenceId: number) =>
    `${API_URL}/api/cases/${caseId}/certificate-draft?evidence_id=${evidenceId}`,
  jsonldUrl: (caseId: number) => `${API_URL}/api/cases/${caseId}/export.jsonld`,
}
