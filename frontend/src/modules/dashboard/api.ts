import { get } from '../../lib/http'

export interface Rate { available: boolean; rate?: number; numerator?: number; denominator?: number; definition?: string; reason?: string }
export interface PerfRun {
  run_id: number
  evidence_id: number
  status: string
  isolated_worker: boolean
  total_seconds: number | null
  bytes_scanned: number
  throughput_mib_per_s: number | null
  bottleneck: { available: boolean; stage?: string; seconds?: number; share?: number; dominant?: boolean; reason?: string }
}
export interface Performance {
  case_id: number
  runs: PerfRun[]
  success_rates: { available: boolean; reason?: string; runs_counted?: number; note?: string; segment_recovery?: Rate; extraction_clean?: Rate; extraction_any?: Rate; analytics_completed?: Rate }
  time_saved: Record<string, { available: boolean; reason?: string; [k: string]: unknown }>
  baseline_comparisons: unknown[]
  method: string
}
export interface AuditRow { id: number; timestamp_utc: string; examiner: string; method: string; path: string; status_code: number; case_id: number | null }

export const dashApi = {
  performance: (caseId: number) => get<Performance>(`/api/cases/${caseId}/performance`),
  audit: (caseId: number, limit = 15) => get<AuditRow[]>(`/api/audit?case_id=${caseId}&limit=${limit}`),
}
