/** Role -> what the UI offers. Mirrors backend/app/auth/policy.py for presentation only: the server
 * checks every request again, so hiding a control is a convenience, never the protection. */
export type Role = 'admin' | 'examiner' | 'reviewer' | 'readonly'

export type Permission =
  | 'case.create' // create a case
  | 'case.write' // acquire, analyse, jobs, analytics, time settings, generate report, package, transfer
  | 'report.approve' // approve or reject a report
  | 'report.finalize'
  | 'users.manage'
  | 'validation.rerun'

const GRANTS: Record<Permission, Role[]> = {
  'case.create': ['admin', 'examiner'],
  'case.write': ['admin', 'examiner'],
  'report.approve': ['admin', 'reviewer'],
  'report.finalize': ['admin', 'examiner', 'reviewer'],
  'users.manage': ['admin'],
  'validation.rerun': ['admin', 'examiner'],
}

export const roleCan = (role: Role | undefined, perm: Permission) => !!role && GRANTS[perm].includes(role)

export const ROLE_LABEL: Record<Role, string> = {
  admin: 'Admin',
  examiner: 'Examiner',
  reviewer: 'Reviewer',
  readonly: 'Read-only',
}
