import { get, post } from '../../lib/http'

export type ReviewStatus = 'draft' | 'pending_approval' | 'approved' | 'rejected' | 'final'

export interface ReportRow {
  id: number
  case_id: number
  kind: string
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
  review_status: ReviewStatus
}

export interface ReviewEvent {
  action: string
  actor: string
  actor_role: string
  note: string
  at: string
  custody_seq: number | null
}
export interface Review {
  report_id: number
  case_id: number
  status: ReviewStatus
  final: boolean
  author: string
  requested_by: string | null
  requested_at: string | null
  approved_by: string | null
  approved_at: string | null
  rejected_by: string | null
  rejected_at: string | null
  finalized_by: string | null
  finalized_at: string | null
  report_sha256: string
  events: ReviewEvent[]
}

export interface PackageRow {
  id: number
  case_id: number
  file_name: string
  sha256: string
  size_bytes: number
  encrypted: boolean
  manifest_sha256: string
  key_id: string
  file_count: number
  include_clips: boolean
  head_hash_built_from: string
  created_at: string
  created_by: string
  custody_seq: number | null
  excluded: unknown[]
  verify_command: string
}

export interface PackageKey {
  algorithm: string
  key_id: string
  public_key_hex: string
}

export interface Transfer {
  id: number
  case_id: number
  evidence_id: number
  from_party: string
  to_party: string
  reason: string
  transferred_at: string
  location: string
  seal: string
  recorded_by: string
  recorded_at: string
  custody_seq: number | null
}

export const reportsApi = {
  list: (caseId: number) => get<ReportRow[]>(`/api/cases/${caseId}/reports`),
  generate: (caseId: number) => post<ReportRow>(`/api/cases/${caseId}/report`),
  review: (id: number) => get<Review>(`/api/reports/${id}/review`),
  step: (id: number, action: 'request-approval' | 'approve' | 'reject' | 'finalize', body?: { note?: string; reason?: string }) =>
    post<Review>(`/api/reports/${id}/${action}`, body ?? {}),
  packages: (caseId: number) => get<PackageRow[]>(`/api/cases/${caseId}/packages`),
  buildPackage: (caseId: number, b: { include_clips: boolean; passphrase?: string }) => post<PackageRow>(`/api/cases/${caseId}/package`, b),
  packageKey: () => get<PackageKey>('/api/package-key'),
  transfers: (caseId: number) => get<Transfer[]>(`/api/cases/${caseId}/transfers`),
  addTransfer: (evidenceId: number, b: { from_party: string; to_party: string; reason: string; location: string; seal: string; transferred_at?: string }) =>
    post<Transfer>(`/api/evidence/${evidenceId}/transfers`, b),
}
