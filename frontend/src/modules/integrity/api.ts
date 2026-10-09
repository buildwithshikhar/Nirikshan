import { get, post } from '../../lib/http'

export type { ChainResult, CustodyEntry } from '../../api'
import type { ChainResult, CustodyEntry } from '../../api'

export interface AuditRow {
  id: number
  timestamp_utc: string
  examiner: string
  method: string
  path: string
  status_code: number
  case_id: number | null
}

export interface EvidenceVerify {
  ok: boolean
  expected: { md5: string; sha256: string; size_bytes: number }
  observed: { md5: string; sha256: string; size_bytes: number } | null
  error: string
}
export interface ClipVerify {
  ok: boolean
  expected: string
  observed: string
}
export interface ClipLite {
  id: number
  kind: string
  seq: number
  has_video?: boolean
  mp4_sha256: string
  size_bytes: number
}
export interface RunLite {
  id: number
  clips: ClipLite[]
}

export const integrityApi = {
  custody: (caseId: number) => get<CustodyEntry[]>(`/api/cases/${caseId}/custody`),
  verifyChain: (caseId: number) => get<ChainResult>(`/api/cases/${caseId}/custody/verify`),
  audit: (caseId: number, limit = 200) => get<AuditRow[]>(`/api/audit?case_id=${caseId}&limit=${limit}`),
  verifyEvidence: (id: number) => post<EvidenceVerify>(`/api/evidence/${id}/verify`),
  verifyClip: (id: number) => post<ClipVerify>(`/api/clips/${id}/verify`),
  runs: (evidenceId: number) => get<RunLite[]>(`/api/evidence/${evidenceId}/runs`),
}
