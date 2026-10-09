import { get } from '../../lib/http'

export interface IdField {
  value: string | null
  status: string
  source: string
  offset: number | null
  note: string
}
export interface SignatureResult {
  name: string
  kind: string
  matched: boolean
  count: number
  offsets: number[]
  details: string[]
  reason?: string
  pattern?: string
  expected_offset?: number
  bytes_seen_hex?: string
}
export interface ParserIdentification {
  vendor: string
  tier: string
  parser_version: string
  confidence: string
  matched: boolean
  signatures_matched: number
  signatures_total: number
  signatures: SignatureResult[]
  basis: string[]
  notes: string[]
  confidence_rule?: string
}
export interface Identification {
  available: boolean
  reason?: string
  image_size: number
  manufacturer: IdField
  device: Record<string, IdField>
  ambiguous: boolean
  matches: { vendor: string; tier: string; confidence: string }[]
  routing: { engine: string; reason: string }
  parsers: ParserIdentification[]
  not_identifiable?: { vendors: string[]; reason: string }
  limits: string[]
  evidence_id: number
  evidence_sha256: string
  tool_version: string
  cached?: boolean
}

export interface OemSupport {
  level: string
  detail: string
}
export interface OemEntry {
  name: string
  parser_vendor: string
  tier: string
  parser_version: string
  standard_export_support: OemSupport
  proprietary_storage_parsing: OemSupport
  deleted_video_recovery: OemSupport
  limitations: string[]
  sources: string[]
}
export interface OemRegistry {
  policy: string[]
  oems: OemEntry[]
  sources: Record<string, { title: string; url: string; confidence: string; says: string; does_not_say: string }>
}

export const deviceApi = {
  identification: (id: number, refresh: boolean, signal?: AbortSignal) =>
    get<Identification>(`/api/evidence/${id}/identification${refresh ? '?refresh=true' : ''}`, signal),
  registry: (signal?: AbortSignal) => get<OemRegistry>('/api/oem-registry', signal),
}
