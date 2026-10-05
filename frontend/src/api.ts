export const API_URL = import.meta.env.VITE_API_URL ?? ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
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


export interface Case {
  id: number
  case_number: string
  title: string
  description: string
  examiner: string
  created_at: string
}

export interface Evidence {
  id: number
  case_id: number
  label: string
  source_path: string
  source_type: string
  write_blocker: 'yes' | 'no' | 'unknown'
  status: string
  size_bytes: number
  md5: string
  sha256: string
  examiner: string
  acquired_at: string
  last_verified_at: string
  last_verify_ok: number
}

export interface CustodyEntry {
  seq: number
  timestamp_utc: string
  action: string
  evidence_id: number | null
  examiner: string
  tool_version: string
  ntp_status: string
  details_json: string
  prev_hash: string
  entry_hash: string
  signature: string
  key_id: string
}

export interface ChainResult {
  ok: boolean
  entries: number
  head_hash: string
  key_id: string
  failures: { seq: number; reason: string }[]
}

export interface SystemInfo {
  tool_version: string
  ffmpeg: { available: boolean; version: string | null }
  mode: string
  ntp_status: string
  signing_key_id: string
}

// Examiner attestation (no authentication): sent as X-Examiner on every call.
const EXAMINER_KEY = 'nirikshan.examiner'
export const getExaminer = () => localStorage.getItem(EXAMINER_KEY) ?? ''
export const setExaminer = (name: string) => localStorage.setItem(EXAMINER_KEY, name)

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, {
    method: 'POST',
    headers: { 'X-Examiner': getExaminer() },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

export const api = {
  health: () => request<{ status: string }>('/health'),
  system: () => request<SystemInfo>('/api/system'),
  listCases: () => request<Case[]>('/api/cases'),
  getCase: (id: number) => request<Case>(`/api/cases/${id}`),
  createCase: (b: { case_number: string; title: string; description: string }) =>
    post<Case>('/api/cases', b),
  listEvidence: (id: number) => request<Evidence[]>(`/api/cases/${id}/evidence`),
  acquire: (id: number, b: { source_path: string; label: string; write_blocker: string }) =>
    post<Evidence>(`/api/cases/${id}/evidence`, b),
  verifyEvidence: (id: number) =>
    post<{ ok: boolean; error: string }>(`/api/evidence/${id}/verify`),
  custody: (id: number) => request<CustodyEntry[]>(`/api/cases/${id}/custody`),
  verifyChain: (id: number) => request<ChainResult>(`/api/cases/${id}/custody/verify`),
}
