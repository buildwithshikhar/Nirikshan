import { get, post } from '../../lib/http'

export interface Case {
  id: number
  case_number: string
  title: string
  description: string
  examiner: string
  created_at: string
}

export interface CaseMember {
  user_id: number
  username: string
  display_name: string
  role: string
  active: boolean
  added_by: string
  added_at: string
}

export interface AuditRow {
  id: number
  timestamp_utc: string
  examiner: string
  method: string
  path: string
  status_code: number
  case_id: number | null
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

export const casesApi = {
  list: (signal?: AbortSignal) => get<Case[]>('/api/cases', signal),
  get: (id: number, signal?: AbortSignal) => get<Case>(`/api/cases/${id}`, signal),
  create: (b: { case_number: string; title: string; description: string }) => post<Case>('/api/cases', b),
  members: (id: number, signal?: AbortSignal) => get<CaseMember[]>(`/api/cases/${id}/members`, signal),
  audit: (id: number, signal?: AbortSignal) => get<AuditRow[]>(`/api/audit?case_id=${id}&limit=200`, signal),
  custody: (id: number, signal?: AbortSignal) => get<CustodyEntry[]>(`/api/cases/${id}/custody`, signal),
}
