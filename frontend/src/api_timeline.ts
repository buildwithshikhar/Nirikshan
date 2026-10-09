import { API_URL, authFetch } from './lib/http'

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
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return res.status === 204 ? (undefined as T) : res.json()
}

const send = <T>(method: 'POST' | 'PUT', path: string, body?: unknown) =>
  request<T>(path, {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
  })

export interface TimeAssumption {
  evidence_id: number
  set: boolean
  timezone: string | null
  epoch_basis: 'utc' | 'device_local' | null
  evidence_kind: string | null
  notes: string
  tz_status: 'unknown' | 'examiner_assumed'
  examiner: string | null
  updated_at: string | null
  warning: string | null
}

export interface TimeReference {
  id: number
  evidence_id: number
  device_time_raw: string
  true_time_utc: string
  method: string
  notes: string
  photo_path: string
  reading_uncertainty_s: number
  examiner: string
  created_at: string
}

export interface DriftModel {
  id: number | null
  method: 'offset_only' | 'linear'
  n: number
  x0: string
  offset_s: number
  offset_ci_s: [number, number]
  drift_ppm: number
  drift_ci_ppm: [number, number] | null
  drift_assumed_zero: boolean
  sigma_s: number
  df: number
  confidence: number
  residuals_s: number[]
  warnings: string[]
  assumptions: string[]
  usable: boolean
  assumed_max_drift_ppm: number
  timezone_used?: string | null
}

export interface TsRecord {
  raw: number | string
  field: string
  format: string
  offset: number
  wall_clock_as_stored: string
  assumed_timezone: string | null
  tz_evidence: string
  tz_status: string
  epoch_basis: string | null
  utc_lo: string | null
  utc_hi: string | null
  candidates: string[]
  flags: string[]
  notes: string[]
  conflict_note: string
  corrected_utc_lo: string | null
  corrected_utc_hi: string | null
}

export interface OsdSummary {
  status: string
  readable?: number
  samples?: number
  median_delta_s: number | null
  mad_s: number | null
  min_delta_s: number | null
  max_delta_s: number | null
  tolerance_s: number
  reason?: string
  outliers?: { t_s: number; delta_s: number }[]
}

export interface TimelineItem {
  clip_id: number
  evidence_id: number
  channel: number | null
  engine: string
  order?: number
  start?: { lo: string; hi: string }
  end?: { lo: string; hi: string }
  end_note?: string
  reason?: string
  flags: string[]
  tz_status: string
  osd: OsdSummary | null
  drift_model_id: number | null
  start_record: TsRecord | null
  end_record: TsRecord | null
  ambiguous_order_with?: number[]
}

export interface Gap {
  evidence_id: number
  channel: number | null
  after_clip_id: number
  before_clip_id: number
  from: string
  to: string
  gap_s_nominal: number
  gap_s_min: number
  gap_s_max: number
  certain: boolean
}

export interface Overlap {
  type: 'same_channel' | 'cross_channel'
  a_clip_id: number
  b_clip_id: number
  overlap_s_nominal: number
  overlap_s_certain: number
  certain: boolean
}

export interface Timeline {
  case_id: number
  tie_break: string
  disclaimer: string
  placed: TimelineItem[]
  unplaceable: TimelineItem[]
  gaps: Gap[]
  overlaps: Overlap[]
  counts: Record<string, number>
  evidence_without_timezone: number[]
  evidence: (TimeAssumption & { label: string; model: DriftModel | null })[]
}

export interface OsdResult {
  clip_id: number
  summary: OsdSummary
  ocr: { library: string; version: string; licence: string }
  readings: { t_s: number; status: string; text: string; osd_wall: string | null; delta_s: number | null }[]
  caveats: string[]
  comparison_available: boolean
}

export const apiTimeline = {
  getAssumption: (ev: number) => request<TimeAssumption>(`/api/evidence/${ev}/time-assumption`),
  putAssumption: (
    ev: number,
    b: { timezone: string | null; epoch_basis: string | null; evidence_kind: string; notes: string },
  ) => send<TimeAssumption>('PUT', `/api/evidence/${ev}/time-assumption`, b),
  listRefs: (ev: number) => request<TimeReference[]>(`/api/evidence/${ev}/time-references`),
  addRef: (
    ev: number,
    b: {
      device_time_raw: string
      true_time_utc: string
      method: string
      notes: string
      photo_path: string
      reading_uncertainty_s: number
    },
  ) => send<TimeReference>('POST', `/api/evidence/${ev}/time-references`, b),
  fit: (ev: number, b?: { reading_uncertainty_s?: number; assumed_max_drift_ppm?: number }) =>
    send<DriftModel>('POST', `/api/evidence/${ev}/time-model/fit`, b ?? {}),
  getModel: (ev: number) => request<DriftModel | null>(`/api/evidence/${ev}/time-model`),
  timeline: (caseId: number) => request<Timeline>(`/api/cases/${caseId}/timeline`),
  exportUrl: (caseId: number, format: 'csv' | 'json') =>
    `${API_URL}/api/cases/${caseId}/timeline/export?format=${format}`,
  osdCheck: (clipId: number, b?: { n_samples?: number; tolerance_s?: number; roi?: number[] }) =>
    send<OsdResult>('POST', `/api/clips/${clipId}/osd-check`, b ?? {}),
}

export const COMMON_ZONES = [
  'UTC',
  'Asia/Kolkata',
  'Asia/Dubai',
  'Asia/Singapore',
  'Asia/Tokyo',
  'Europe/London',
  'Europe/Berlin',
  'Europe/Paris',
  'America/New_York',
  'America/Chicago',
  'America/Los_Angeles',
  'Australia/Sydney',
]

/** Full IANA list from the browser when available (Intl.supportedValuesOf), else a short list. */
export function ianaZones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (k: string) => string[] }
  try {
    const all = intl.supportedValuesOf?.('timeZone')
    // Browsers differ on aliases (Chromium lists Asia/Calcutta, not Asia/Kolkata): always offer the common names.
    if (all && all.length > 0) return Array.from(new Set([...COMMON_ZONES, ...all]))
  } catch {
    // fall through
  }
  return COMMON_ZONES
}
