import type { Permission } from '../auth/permissions'

export interface NavItem {
  id: string
  label: string
  /** case-scoped items need a selected case; `to` receives its id */
  to: (caseId: number | null) => string | null
  perm?: Permission
}
export interface NavGroup {
  id: string
  label: string
  items: NavItem[]
}

const c = (seg: string) => (id: number | null) => (id == null ? null : `/cases/${id}/${seg}`)

/** The 6 groups / 15 modules of docs/ROUND_D_UI_MAP.md. */
export const NAV: NavGroup[] = [
  { id: 'overview', label: 'Overview', items: [{ id: 'dashboard', label: 'Dashboard', to: () => '/' }] },
  {
    id: 'acquire',
    label: 'Acquire',
    items: [
      { id: 'cases', label: 'Cases', to: () => '/cases' },
      { id: 'evidence', label: 'Evidence & Acquisition', to: c('evidence') },
      { id: 'device', label: 'Device Intelligence', to: c('identification') },
    ],
  },
  {
    id: 'recover',
    label: 'Recover',
    items: [
      { id: 'explorer', label: 'Storage Explorer', to: c('explorer') },
      { id: 'recovery', label: 'Recovery Lab', to: c('recovery') },
    ],
  },
  {
    id: 'analyse',
    label: 'Analyse',
    items: [
      { id: 'timeline', label: 'Timeline', to: c('timeline') },
      { id: 'triage', label: 'AI Triage', to: c('triage') },
      { id: 'correlation', label: 'Correlation', to: c('correlation') },
    ],
  },
  {
    id: 'assure',
    label: 'Assure',
    items: [
      { id: 'integrity', label: 'Integrity Center', to: c('integrity') },
      { id: 'reports', label: 'Report Studio', to: c('reports') },
      { id: 'validation', label: 'Validation & Compatibility', to: () => '/validation' },
    ],
  },
  {
    id: 'system',
    label: 'System',
    items: [
      { id: 'jobs', label: 'Jobs', to: c('jobs') },
      { id: 'admin', label: 'Admin', to: () => '/admin', perm: 'users.manage' },
      { id: 'help', label: 'Help', to: () => '/help' },
    ],
  },
]
