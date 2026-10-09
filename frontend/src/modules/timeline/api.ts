import { get, post, put } from '../../lib/http'
import type { DriftModel, OsdResult, TimeAssumption, TimeReference, Timeline } from '../../api_timeline'

// Types (and the IANA zone helper) stay in the shared api_timeline.ts: the shell status chips use it too.
export { COMMON_ZONES, ianaZones } from '../../api_timeline'
export type * from '../../api_timeline'

export const tl = {
  getAssumption: (ev: number) => get<TimeAssumption>(`/api/evidence/${ev}/time-assumption`),
  putAssumption: (ev: number, b: { timezone: string | null; epoch_basis: string | null; evidence_kind: string; notes: string }) =>
    put<TimeAssumption>(`/api/evidence/${ev}/time-assumption`, b),
  listRefs: (ev: number) => get<TimeReference[]>(`/api/evidence/${ev}/time-references`),
  addRef: (
    ev: number,
    b: { device_time_raw: string; true_time_utc: string; method: string; notes: string; photo_path: string; reading_uncertainty_s: number },
  ) => post<TimeReference>(`/api/evidence/${ev}/time-references`, b),
  fit: (ev: number) => post<DriftModel>(`/api/evidence/${ev}/time-model/fit`, {}),
  getModel: (ev: number) => get<DriftModel | null>(`/api/evidence/${ev}/time-model`),
  timeline: (caseId: number) => get<Timeline>(`/api/cases/${caseId}/timeline`),
  exportPath: (caseId: number, format: 'csv' | 'json') => `/api/cases/${caseId}/timeline/export?format=${format}`,
  osdCheck: (clipId: number) => post<OsdResult>(`/api/clips/${clipId}/osd-check`, {}),
}
