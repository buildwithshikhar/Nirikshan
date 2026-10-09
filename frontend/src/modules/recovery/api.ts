import { get, post } from '../../lib/http'

export type JobStatus = 'queued' | 'running' | 'cancelling' | 'cancelled' | 'failed' | 'completed'
export interface Job {
  id: number
  kind: string
  case_id: number
  evidence_id: number
  status: JobStatus
  active: boolean
  cancel_requested: boolean
  progress: number
  stage: string
  run_id: number | null
  clips_recorded: number
  error: string
  existing?: boolean
}

export interface ClipRow {
  id: number
  run_id: number
  evidence_id: number
  kind: 'clip' | 'orphan'
  seq: number
  codec: string
  start_offset: number
  end_offset: number
  size_bytes: number
  extents_json: string
  nal_count: number
  irap_count: number
  vcl_count: number
  reassembled: number
  reason: string
  notes_json: string
  bitstream_sha256: string
  mp4_sha256: string
  decode_status: string
  decode_errors_json: string
  error: string
  width: number | null
  height: number | null
  fps: string
  packets: number | null
  duration_s: number | null
  has_video: boolean
  engine: string
  channel: number | null
  parsed_json: string
}

export interface ParsedField {
  name: string
  value: unknown
  status: 'parsed' | 'inferred' | 'unknown'
  source: string
  note: string
}
export interface RawTimestamp {
  field: string
  offset: number
  raw: unknown
  format: string
  wall_clock_as_stored: string
  tz_basis: string
  note: string
}
export interface ParserResult {
  parser: string
  vendor: string
  tier: string
  status: 'parsed' | 'partial' | 'fallback'
  options: Record<string, unknown>
  fields: ParsedField[]
  timestamps: RawTimestamp[]
  warnings: string[]
  inconsistencies: string[]
  crosscheck: { parser_clips: number; generic_clips: number; disagreements: Record<string, unknown>[] }
}
export interface VendorMatch {
  vendor: string
  tier: string
  confidence: string
  notes: string[]
  basis: string[]
}
export interface Run {
  id: number
  evidence_id: number
  status: string
  params: Record<string, unknown>
  vendor_matches: VendorMatch[]
  parsers: ParserResult[]
  stats: Record<string, number>
  tool_version: string
  ffmpeg_version: string
  identify_seconds: number
  carve_seconds: number
  error: string
  clips: ClipRow[]
}

export interface Recoverability {
  clip_id: number
  available: boolean
  reason?: string
  kind?: string
  engine?: string
  estimate?: number
  band?: string
  rule_version?: string
  components?: { name: string; factor: number; why: string }[]
  explanation?: string
  limitations?: string[]
  disclaimer?: string
  measured_agreement?: Agreement
}
export interface Agreement {
  available: boolean
  reason?: string
  overall?: { pearson_r: number; spearman_rho: number; band_agreement: number; mean_absolute_error: number; clips: number }
  disclaimer?: string
  source?: string
}
export interface FragmentReassembly {
  available: boolean
  reason?: string
  default?: string
  enable_with?: string
  pooled_false_accept?: { k: number; n: number; rate: number }
  scenarios?: { scenario: string; layout: string; false_accept: { rate: number | null; k: number; n: number }; true_accept: { rate: number | null; k: number; n: number } }[]
  disclaimer?: string[]
  note?: string
}

export const recoveryApi = {
  runs: (evidenceId: number, signal?: AbortSignal) => get<Run[]>(`/api/evidence/${evidenceId}/runs`, signal),
  submit: (evidenceId: number, b: { join_gap: number; parser_options: Record<string, unknown> }) =>
    post<Job>(`/api/evidence/${evidenceId}/jobs/analyze`, b),
  job: (id: number, signal?: AbortSignal) => get<Job>(`/api/jobs/${id}`, signal),
  activeJobs: (caseId: number, evidenceId: number) => get<Job[]>(`/api/cases/${caseId}/jobs?evidence_id=${evidenceId}&active=true`),
  cancel: (id: number) => post<Job>(`/api/jobs/${id}/cancel`),
  verifyClip: (id: number) => post<{ ok: boolean }>(`/api/clips/${id}/verify`),
  recoverability: (id: number, signal?: AbortSignal) => get<Recoverability>(`/api/clips/${id}/recoverability`, signal),
  agreement: (signal?: AbortSignal) => get<Agreement>('/api/recovery/agreement', signal),
  fragments: (signal?: AbortSignal) => get<FragmentReassembly>('/api/recovery/fragment-reassembly', signal),
}

export const parseJson = <T,>(s: string, fallback: T): T => {
  try {
    return JSON.parse(s || 'null') ?? fallback
  } catch {
    return fallback
  }
}
export const hex = (n: number) => `0x${n.toString(16)}`
