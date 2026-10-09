import { authFetch, API_URL, ApiError, get, post, put } from '../../lib/http'

export interface TopoNode {
  id: string
  label: string
  evidence_id: number | null
  channel: number | null
  x: number | null
  y: number | null
}
export interface TopoEdge {
  a: string
  b: string
  max_transit_s: number | null
}
export interface Topology {
  case_id: number
  defined: boolean
  nodes: TopoNode[]
  edges: TopoEdge[]
  coordinate_units?: string
  notes?: string
  examiner?: string
  updated_at?: string
  floorplan: { sha256: string; content_type: string; size_bytes: number; url: string } | null
}

export interface Snapshot {
  type: 'event_segment' | 'external_log_entry'
  key: string
  camera_node: string
  class_name?: string
  clip_id?: number
  evidence_id?: number
  camera?: number | null
  utc_lo: string | null
  utc_hi: string | null
  links?: { video_at: string }
  raw_time?: string
  event_text?: string
  location?: string
  row_number?: number
  log_id?: number
}
export interface Link {
  id: number
  status: 'suggested' | 'accepted' | 'rejected'
  a: Snapshot
  b: Snapshot
  rules: { rule: string; detail: unknown }[]
  explanation: string
  gap_s_min: number
  gap_s_max: number
  decided_by: string | null
  decided_at: string | null
  decision_note: string | null
  label: string
  triage_label: string
}
export interface LinksResponse {
  links: Link[]
  note: string
  label: string
}
export interface GenerateResult {
  candidates: number
  created: number
  updated: number
  dropped_stale_suggestions: number
  decided_links_kept: number
  note: string
  label: string
}
export interface ExternalLog {
  id: number
  filename: string
  sha256: string
  size_bytes: number
  timezone: string
  time_format: string
  resolution_s: number
  authorization_note: string
  row_count: number
  rows_unplaced: number
  examiner: string
  imported_at: string
}
export interface ExternalLogIn {
  filename: string
  content: string
  authorization_note: string
  timezone: string
  time_format: string
  mapping: { time: string; event?: string; location?: string }
  location_nodes: Record<string, string>
  delimiter: string
}

export const corrApi = {
  topology: (c: number) => get<Topology>(`/api/cases/${c}/correlation/topology`),
  putTopology: (c: number, b: { nodes: TopoNode[]; edges: TopoEdge[]; coordinate_units: string; notes: string }) =>
    put<Topology>(`/api/cases/${c}/correlation/topology`, b),
  uploadFloorplan: async (c: number, file: File) => {
    const res = await authFetch(`${API_URL}/api/cases/${c}/correlation/floorplan`, { method: 'PUT', headers: { 'Content-Type': file.type }, body: file })
    if (!res.ok) {
      const t = await res.text()
      let d: unknown = t
      try {
        d = (JSON.parse(t) as { detail?: unknown }).detail ?? t
      } catch {
        // raw text
      }
      throw new ApiError(res.status, d)
    }
    return res.json() as Promise<{ sha256: string }>
  },
  /** The floor plan needs the bearer token, so it is fetched and shown from a blob URL. */
  floorplanBlob: async (c: number): Promise<string | null> => {
    const res = await authFetch(`${API_URL}/api/cases/${c}/correlation/floorplan`)
    if (res.status === 404) return null
    if (!res.ok) throw new ApiError(res.status, await res.text())
    return URL.createObjectURL(await res.blob())
  },
  logs: (c: number) => get<ExternalLog[]>(`/api/cases/${c}/correlation/external-logs`),
  importLog: (c: number, b: ExternalLogIn) => post<ExternalLog>(`/api/cases/${c}/correlation/external-logs`, b),
  generate: (c: number, b: { window_s: number; require_same_class: boolean; segment_gap_s: number; include_external_logs: boolean }) =>
    post<GenerateResult>(`/api/cases/${c}/correlation/links/generate`, b),
  links: (c: number, status?: string) => get<LinksResponse>(`/api/cases/${c}/correlation/links${status ? `?status=${status}` : ''}`),
  decide: (id: number, decision: 'accept' | 'reject', note: string) => post<Link>(`/api/correlation/links/${id}/decision`, { decision, note }),
}
