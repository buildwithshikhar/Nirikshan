import { get } from '../../lib/http'

export interface Region {
  start: number
  end: number
  bytes: number
  kind: string
  ref?: { vendor?: string; signature?: string; detail?: string; [k: string]: unknown }
}
export interface Regions {
  evidence_id: number
  run_id: number | null
  image_size: number
  scanned_bytes: number
  block_size: number
  summary: Record<string, { bytes: number; regions: number; fraction: number }>
  region_count: number
  truncated: boolean
  regions: Region[]
  notes: string[]
}
export interface Partitions {
  scheme: string
  mbr: unknown
  gpt: unknown
  filesystems: { [k: string]: unknown }[]
  anomalies: { kind: string; offset?: number; detail?: unknown }[]
  note: string
}
export interface Anomaly {
  severity: 'warning' | 'info'
  kind: string
  offset?: number | null
  source?: string
  detail?: unknown
}
export interface Anomalies {
  count: number
  warnings: number
  anomalies: Anomaly[]
  note: string | null
}
export interface HexRead {
  offset: number
  length: number
  requested_length: number
  max_length: number
  image_size: number
  hex: string
  ascii: string
  bytes_sha256: string
}

export const explorerApi = {
  regions: (id: number, signal?: AbortSignal) => get<Regions>(`/api/evidence/${id}/regions`, signal),
  partitions: (id: number, signal?: AbortSignal) => get<Partitions>(`/api/evidence/${id}/partitions`, signal),
  anomalies: (id: number, signal?: AbortSignal) => get<Anomalies>(`/api/evidence/${id}/anomalies`, signal),
  hex: (id: number, offset: number, length: number) => get<HexRead>(`/api/evidence/${id}/hex?offset=${offset}&length=${length}`),
}
