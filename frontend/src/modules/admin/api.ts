import { del, get, patch, post } from '../../lib/http'
import type { User } from '../../auth/api'
import type { Role } from '../../auth/permissions'

export interface Member { user_id: number; username: string; display_name: string; role: Role; active: boolean; added_by: string; added_at: string }
export interface PublicKey { algorithm: string; key_id: string; public_key_hex: string }
export interface SystemFull {
  tool_version: string
  schema_version: number
  mode: string
  ntp_status: string
  evidence_roots: string[]
  block_devices_allowed: boolean
  signing_key_id: string
  ffmpeg: { available: boolean; version: string | null }
}
export interface AuditRow { id: number; timestamp_utc: string; examiner: string; method: string; path: string; status_code: number; case_id: number | null }

export const adminApi = {
  users: () => get<User[]>('/api/users'),
  createUser: (b: { username: string; display_name: string; role: Role; password: string }) => post<User>('/api/users', b),
  patchUser: (id: number, b: { display_name?: string; role?: Role; active?: boolean }) => patch<User>(`/api/users/${id}`, b),
  resetPassword: (id: number, new_password: string) => post<{ ok: boolean }>(`/api/users/${id}/password`, { new_password }),
  unlock: (id: number) => post<unknown>(`/api/users/${id}/unlock`),
  members: (caseId: number) => get<Member[]>(`/api/cases/${caseId}/members`),
  addMember: (caseId: number, user_id: number) => post<unknown>(`/api/cases/${caseId}/members`, { user_id }),
  removeMember: (caseId: number, uid: number) => del<unknown>(`/api/cases/${caseId}/members/${uid}`),
  signingKey: () => get<PublicKey>('/api/signing-key'),
  packageKey: () => get<PublicKey>('/api/package-key'),
  system: () => get<SystemFull>('/api/system'),
  audit: (limit = 200) => get<AuditRow[]>(`/api/audit?limit=${limit}`),
}
