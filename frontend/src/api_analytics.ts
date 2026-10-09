// P6 analytics API client (triage only). Same request()/post pattern and X-Examiner header as api.ts.
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
    throw new Error(String(detail))
  }
  return res.json()
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
  })

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

export const analyticsApi = {
  runs: (clipId: number) => request<AnalyticsRun[]>(`/api/clips/${clipId}/analytics`),
  run: (runId: number) => request<AnalyticsRun>(`/api/analytics/${runId}`),
  start: (clipId: number, kind: AnalyticsKind, params: Record<string, unknown>) =>
    post<AnalyticsRun>(`/api/clips/${clipId}/analytics`, { kind, params }),
  models: () =>
    request<{ label: string; models: (ModelInfo & { installed: boolean; error: string })[] }>(
      '/api/analytics/models',
    ),
}
