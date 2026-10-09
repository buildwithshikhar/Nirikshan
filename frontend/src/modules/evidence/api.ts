import { get, post } from '../../lib/http'

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
  synthetic?: boolean
}

export interface BadRange {
  start: number
  end: number
  bytes: number
  error: string
}
export interface AcquisitionSession {
  id: number
  case_id: number
  evidence_id: number | null
  mode: string
  status: string
  source_path: string
  source_size: number
  bytes_done: number
  progress: number
  chunk_size: number
  chunks_checkpointed: number
  retries: number
  resumes: number
  error: string
  bad_sector_map: { ranges: BadRange[]; range_count: number; bytes: number; sector_size: number; zero_filled: boolean; hash_scope: string }
  evidence?: { id: number; status: string; size_bytes: number; md5: string; sha256: string } | null
}

export interface BadSectors {
  available: boolean
  method?: string
  session_id?: number
  ranges: BadRange[]
  range_count: number
  bytes: number
  sector_size?: number
  zero_filled: boolean
  hash_scope?: string
  note?: string
}

export interface Capability {
  available: boolean
  reason?: string
  note?: string
  opt_in?: string
}
export type Capabilities = Record<'resumable' | 'bad_sector_map' | 'native_export_ingest' | 'ewf' | 'block_device', Capability>

export interface NativeExport {
  available: boolean
  reason?: string
  probe_status?: string
  container?: { format_name: string; format_long_name: string; duration_s: number | null; bit_rate: number | null; nb_streams: number; probe_score: number }
  streams?: Record<string, unknown>[]
  tags?: Record<string, string>
  tags_note?: string
  probe_error?: string
  ffprobe_version?: string
  note?: string
}

export const evidenceApi = {
  list: (caseId: number, signal?: AbortSignal) => get<Evidence[]>(`/api/cases/${caseId}/evidence`, signal),
  capabilities: (signal?: AbortSignal) => get<Capabilities>('/api/acquisition/capabilities', signal),
  ewf: (signal?: AbortSignal) => get<Capability>('/api/acquisition/ewf', signal),
  acquire: (caseId: number, b: { source_path: string; label: string; write_blocker: string }) =>
    post<AcquisitionSession>(`/api/cases/${caseId}/acquisitions`, b),
  nativeExport: (caseId: number, b: { source_path: string; label: string; write_blocker: string }) =>
    post<{ acquisition: AcquisitionSession }>(`/api/cases/${caseId}/native-exports`, b),
  sessions: (caseId: number, signal?: AbortSignal) => get<AcquisitionSession[]>(`/api/cases/${caseId}/acquisitions`, signal),
  resume: (sessionId: number) => post<AcquisitionSession>(`/api/acquisitions/${sessionId}/resume`),
  verify: (id: number) => post<{ ok: boolean; error: string }>(`/api/evidence/${id}/verify`),
  badSectors: (id: number, signal?: AbortSignal) => get<BadSectors>(`/api/evidence/${id}/bad-sectors`, signal),
  nativeInfo: (id: number, signal?: AbortSignal) => get<NativeExport>(`/api/evidence/${id}/native-export`, signal),
}
