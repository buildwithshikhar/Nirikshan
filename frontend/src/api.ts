import { API_URL, authFetch } from './lib/http'
export { API_URL }

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
  synthetic?: boolean // true when the image starts with the SYNTHETIC banner
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

export interface VendorHit {
  signature: string
  offset: number
  detail: string
}

export interface VendorMatch {
  vendor: string
  tier: string
  confidence: string
  evidence: VendorHit[]
  signature_counts: Record<string, number>
  basis: string[]
  notes: string[]
}

export interface ClipRow {
  id: number
  run_id: number
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

export interface ParsedFieldInfo {
  name: string
  value: unknown
  status: 'parsed' | 'inferred' | 'unknown'
  source: string
  note: string
}

export interface RawTimestampInfo {
  field: string
  offset: number
  raw: unknown
  format: string
  wall_clock_as_stored: string
  tz_basis: string
  note: string
}

export interface ParserResultInfo {
  parser: string
  vendor: string
  tier: string
  status: 'parsed' | 'partial' | 'fallback'
  options: Record<string, unknown>
  fields: ParsedFieldInfo[]
  timestamps: RawTimestampInfo[]
  warnings: string[]
  inconsistencies: string[]
  stats: Record<string, number>
  crosscheck: { parser_clips: number; generic_clips: number; disagreements: Record<string, unknown>[] }
  clips: { channel: number | null; codec: string; frames: number }[]
}

export interface CarveRunInfo {
  parsers: ParserResultInfo[]
  id: number
  evidence_id: number
  status: string
  params: { max_pad: number; join_gap: number; h264_continuity: boolean }
  vendor_matches: VendorMatch[]
  stats: Record<string, number>
  tool_version: string
  ffmpeg_version: string
  started_at: string
  finished_at: string
  identify_seconds: number
  carve_seconds: number
  error: string
  clips: ClipRow[]
}

export interface SystemInfo {
  tool_version: string
  ffmpeg: { available: boolean; version: string | null }
  mode: string
  ntp_status: string
  signing_key_id: string
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, {
    method: 'POST',
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
  getEvidence: async (caseId: number, id: number) =>
    (await request<Evidence[]>(`/api/cases/${caseId}/evidence`)).find((e) => e.id === id),
  analyze: (id: number, b: { join_gap: number; parser_options: Record<string, unknown> }) =>
    post<CarveRunInfo>(`/api/evidence/${id}/analyze`, {
      join_gap: b.join_gap,
      parser_options: b.parser_options,
    }),
  runs: (id: number) => request<CarveRunInfo[]>(`/api/evidence/${id}/runs`),
  verifyClip: (id: number) => post<{ ok: boolean }>(`/api/clips/${id}/verify`),
  custody: (id: number) => request<CustodyEntry[]>(`/api/cases/${id}/custody`),
  verifyChain: (id: number) => request<ChainResult>(`/api/cases/${id}/custody/verify`),
}
