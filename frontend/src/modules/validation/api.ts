import { get, post } from '../../lib/http'

export interface Unavail {
  available: false
  reason: string
  path?: string
  basis?: string
}
export interface Metric {
  k?: number
  n?: number
  rate?: number
  ci95?: [number, number]
  count?: number
  basis: string
}
export interface Summary {
  available: true
  headline: string
  disclosure: string
  tier_limit: string
  basis: string
  disclaimer: string[]
  synthetic: boolean
  seed: number
  trials: number
  results_digest: string
  digest_verified: boolean
  file_sha256: string
  path: string
}
export interface ScenarioResult {
  id: string
  scenario: string
  title: string
  kind: string
  layout: string
  trials: number
  recall?: Metric
  precision?: Metric
  frame_recall?: Metric
  [k: string]: unknown
}
export interface EngineCard {
  engine: string
  scenarios: ScenarioResult[]
  pooled_recall?: Metric
  pooled_precision?: Metric
}
export interface Vendor {
  vendor: string
  tier: string
  scenario_results: number
  engines: EngineCard[]
  basis: string
}
export interface Scorecards {
  available: true
  results_digest: string
  digest_verified: boolean
  vendors: Vendor[]
  basis: string
}
export interface RegressionRule {
  scenario: string
  metric: string
  rule: Record<string, number>
  observed: Metric | null
  pass: boolean
  violations: string[]
}
export interface Regression {
  available: true
  status: string
  violations: string[]
  stored_matches_recomputed: boolean
  thresholds_file: string
  rules: RegressionRule[]
  basis: string
}
export interface FalseRates {
  available: true
  negative_scenarios: { id: string; engine: string; title: string; images: number; clips_emitted: Metric; false_accept_decodable_clips: Metric; emitted_but_flagged_failed: Metric }[]
  reassembler: { id: string; engine: string; reassembler_false_accept: Metric; reassembler_true_accept: Metric }[]
  positive_scenario_false_positives: { id: string; engine: string; false_positive_clips: Metric; mixed_clips: Metric }[]
  notes: string[]
  basis: string
}
export interface Crosscheck {
  available: true
  scenarios: { id: string; engine: string; images: number; disagreement_kinds: Record<string, number>; benign_kinds: string[]; non_benign_disagreement_images: Metric }[]
  totals_by_vendor: Record<string, Record<string, Metric>>
  benign_definition: string[]
  explanation: string
  basis: string
}

export interface OemSource {
  title: string
  url: string
  retrieved: string
  says: string
  does_not_say: string
  confidence: 'high' | 'medium' | 'low'
}
export interface Support {
  level: string
  detail: string
}
export interface Oem {
  name: string
  tier: string
  parser_version?: string
  standard_export_support: Support
  proprietary_storage_parsing: Support
  deleted_video_recovery: Support
  evidence: { tests: string[]; docs: string[] }
  limitations: string[]
  sources: string[]
}
export interface OemRegistry {
  registry_version: number
  updated: string
  policy: string[]
  generic: { standard_export_ingest: string; generic_carving: string }
  sources: Record<string, OemSource>
  oems: Oem[]
  consistent_with_code: boolean
  consistency_problems: string[]
  targets: number
}

export interface Rerun {
  id: number
  status: string
  params: { seed: number; trials: number; export: boolean; scenarios: string[] | null }
  command: string[]
  baseline_unchanged: boolean | null
  baseline_digest: string | null
  rerun_digest: string | null
  comparison: {
    comparable?: boolean
    digest_match?: boolean
    parameter_or_version_differences?: unknown[]
    metric_differences?: unknown[]
    rerun_threshold_violations?: unknown[]
  }
  exit_code: number | null
  log_tail: string
  error: string | null
  examiner: string
  created_at: string
  started_at: string | null
  finished_at: string | null
  timeout_s: number
  basis: string
}

export const ACTIVE_RERUN = ['queued', 'running']
export const isUnavailable = (x: unknown): x is Unavail => !!x && typeof x === 'object' && (x as { available?: unknown }).available === false

export const validationApi = {
  summary: () => get<Summary | Unavail>('/api/validation/summary'),
  scorecards: () => get<Scorecards | Unavail>('/api/validation/scorecards'),
  regression: () => get<Regression | Unavail>('/api/validation/regression'),
  falseRates: () => get<FalseRates | Unavail>('/api/validation/false-rates'),
  crosscheck: () => get<Crosscheck | Unavail>('/api/validation/crosscheck'),
  registry: () => get<OemRegistry>('/api/oem-registry'),
  reruns: () => get<Rerun[]>('/api/validation/reruns'),
  rerun: (id: number) => get<Rerun>(`/api/validation/reruns/${id}`),
  startRerun: (b: { trials?: number; seed?: number; export: boolean }) => post<Rerun>('/api/validation/reruns', b),
}
