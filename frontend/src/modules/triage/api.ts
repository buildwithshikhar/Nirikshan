import { ApiError, get, post } from '../../lib/http'

export type AnalyticsKind = 'motion' | 'objects' | 'faces'

export interface ModelInfo {
  key?: string
  name: string
  version: string
  sha256: string
  licence: string
  licence_url: string
  source_url?: string
  input_size?: number[]
}

export interface ErrorRateConfig {
  dataset: string
  dataset_licence?: string
  label: string
  condition: string
  class?: string
  confidence_threshold?: number
  iou_threshold?: number
  match_rule?: string
  n_images: number
  tp: number
  fp: number
  fn: number
  precision: number | null
  recall: number | null
  precision_ci_wilson: (number | null)[]
  recall_ci_wilson: (number | null)[]
  precision_ci_bootstrap: number[]
  recall_ci_bootstrap: number[]
}

export interface ErrorRates {
  configs: ErrorRateConfig[]
  measured_classes?: string[]
  unmeasured_note?: string
  run_threshold_measured?: boolean | null
  run_params_match_measured?: boolean
  label?: string
  note?: string
}

export interface MotionIntervalRow {
  id: number
  start_frame: number
  end_frame: number
  start_time_s: number
  end_time_s: number
  n_samples: number
  score_peak: number
  score_mean: number
  label: string
}

export interface DetectionRow {
  id: number
  frame_index: number
  nominal_time_s: number
  class_name: string
  confidence: number
  bbox: number[]
  label: string
}

export interface AnalyticsRun {
  id: number
  clip_id: number
  kind: AnalyticsKind
  status: string
  label: string
  examiner: string
  bitstream_sha256: string
  mp4_sha256: string
  params: Record<string, unknown>
  model: ModelInfo | null
  error_rates: ErrorRates
  tool: Record<string, string>
  frames_analysed: number
  result_count: number
  ms_per_frame: number
  started_at: string
  finished_at: string
  error: string
  intervals?: MotionIntervalRow[]
  detections?: DetectionRow[]
}

export interface ModelStatus extends ModelInfo {
  installed: boolean
  error: string
}
export interface ModelsResponse {
  label: string
  models: ModelStatus[]
  error_rates: Record<string, unknown>
}
export interface Job {
  id: number
  status: 'queued' | 'running' | 'cancelling' | 'cancelled' | 'failed' | 'completed'
  active: boolean
  progress: number
  stage: string
  run_id: number | null
  error: string
  isolated: boolean
  clip_id: number | null
}
export interface ClipOption {
  id: number
  evidence_id: number
  channel: number | null
  codec: string
  duration_s: number | null
  size_bytes: number
}
export interface GrammarClause {
  form: string
  example: string
  meaning: string
}
export interface Grammar {
  summary: string
  clauses: GrammarClause[]
  label: string
  [k: string]: unknown
}
export interface EventHit {
  event_id: number
  clip_id: number
  evidence_id: number
  run_id: number
  kind: string
  class_name: string
  camera: number | null
  frame_index: number
  nominal_time_s: number
  nominal_end_s?: number
  confidence: number | null
  motion_score_peak: number | null
  placement: string
  unplaceable_reason: string | null
  tz_status: string
  assumed_timezone: string | null
  utc: { lo: string; hi: string; end_lo?: string; end_hi?: string } | null
  model: { name: string | null; sha256: string | null }
  source: {
    clip_start_offset: number | null
    clip_end_offset: number | null
    note: string
    frame_byte_offset: { available: boolean; reason: string }
  }
  links: { video: string; analytics_run: string }
  label: string
}
export interface SearchResult {
  total: number
  offset: number
  limit: number
  interpreted: unknown
  hits: EventHit[]
  excluded_unplaceable_clips: number
  excluded_unplaceable_clip_ids: number[]
  excluded_no_device_timezone_clip_ids: number[]
  fulltext_backend: string
  notes: string[]
  label: string
}
export interface EventStatus {
  events: number
  indexed_at: string | null
  fulltext_backend: string
}
export interface SummaryGroup {
  group: { clip_id?: number; evidence_id?: number; camera?: number | null }
  text: string
  classes: { class_name: string; count: number }[]
}
export interface Summaries {
  by: string
  label: string
  triage_label: string
  template: string
  events_indexed: number
  summaries: SummaryGroup[]
}

export const analyticsApi = {
  runs: (clipId: number) => get<AnalyticsRun[]>(`/api/clips/${clipId}/analytics`),
  run: (runId: number) => get<AnalyticsRun>(`/api/analytics/${runId}`),
  models: () => get<ModelsResponse>('/api/analytics/models'),
  /** Background, isolated-worker route (the synchronous route is not isolated). */
  startJob: (clipId: number, kind: AnalyticsKind, params: Record<string, unknown>) =>
    post<Job>(`/api/clips/${clipId}/jobs/analytics`, { kind, params }),
  job: (id: number) => get<Job>(`/api/jobs/${id}`),
  grammar: () => get<Grammar>('/api/events/grammar'),
  status: (caseId: number) => get<EventStatus>(`/api/cases/${caseId}/events/status`),
  reindex: (caseId: number) => post<unknown>(`/api/cases/${caseId}/events/reindex`),
  search: (caseId: number, q: string) => get<SearchResult>(`/api/cases/${caseId}/events/search?q=${encodeURIComponent(q)}&limit=100`),
  summaries: (caseId: number, by: 'clip' | 'camera') => get<Summaries>(`/api/cases/${caseId}/summaries?by=${by}`),
}

/** The server's reason for a failed call, with a parse-error body (422) flattened to text. */
export const reasonOf = (e: unknown): string => {
  if (e instanceof ApiError && typeof e.detail === 'object' && e.detail && 'error' in e.detail) {
    const d = e.detail as { error: string; position?: number; token?: string }
    return `${d.error}${d.token ? ` (at "${d.token}")` : ''}`
  }
  return e instanceof Error ? e.message : String(e)
}
