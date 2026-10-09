import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { ROLE_LABEL } from '../auth/permissions'
import { TIER_LIMIT } from '../dataOrigin'
import { type BackendStatus, useBackendStatus } from '../useBackendStatus'
import { Button, Chip, ErrorBoundary } from '../ui'
import { useCase } from './CaseContext'
import StatusBanners, { StatusChips, useCaseStatus } from './CaseStatus'
import { DetailDrawerProvider } from './DetailDrawer'
import { JobsDrawer } from './JobsDrawer'
import { NAV } from './nav'

const API_STATUS: Record<BackendStatus, { tone: 'neutral' | 'ok' | 'warn' | 'bad'; label: string }> = {
  checking: { tone: 'neutral', label: 'Checking API…' },
  online: { tone: 'ok', label: 'API online' },
  waking: { tone: 'warn', label: 'Waking up API, retrying…' },
  offline: { tone: 'bad', label: 'API offline' },
}

/** After a client-side navigation: set the document title from the page's <h1> and move focus
 * to <main> so keyboard and screen-reader users start at the new content (WCAG 2.4.3, 2.4.2). */
function useRouteFocus(mainRef: React.RefObject<HTMLElement | null>) {
  const { pathname } = useLocation()
  const first = useRef(true)
  useEffect(() => {
    const t = setTimeout(() => {
      const h1 = document.querySelector('main h1')?.textContent?.trim()
      document.title = h1 ? `${h1} | Nirikshan` : 'Nirikshan'
      if (first.current) {
        first.current = false
        return
      }
      const a = document.activeElement
      if (!a || a === document.body || !mainRef.current?.contains(a)) mainRef.current?.focus()
    }, 150)
    return () => clearTimeout(t)
  }, [pathname, mainRef])
}

const readCollapsed = () => {
  try {
    return localStorage.getItem('nirikshan.sidebar') === '1'
  } catch {
    return false
  }
}

function Sidebar({ collapsed, toggle }: { collapsed: boolean; toggle: () => void }) {
  const { caseId, kase } = useCase()
  const { can } = useAuth()
  const link = (active: boolean) =>
    `flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition ${active ? 'bg-accent text-navy-900' : 'text-slate-200 hover:bg-navy-700'}`
  return (
    <aside className={`${collapsed ? 'w-16' : 'w-60'} flex shrink-0 flex-col bg-navy-800 transition-[width]`} data-testid="sidebar">
      <div className="flex items-center justify-between p-4">
        {!collapsed && <span className="text-2xl font-bold text-accent">Nirikshan</span>}
        <button
          onClick={toggle}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-expanded={!collapsed}
          className="rounded px-2 py-1 text-slate-200 hover:bg-navy-700"
        >
          {collapsed ? '»' : '«'}
        </button>
      </div>
      {!collapsed && (
        <div className="mx-3 mb-3 rounded bg-navy-900 p-2 text-xs" data-testid="pinned-case">
          <div className="text-slate-400">Current case</div>
          <div className="truncate font-medium" title={kase ? `${kase.case_number}: ${kase.title}` : ''}>
            {kase ? kase.case_number : 'None selected'}
          </div>
          {kase && <div className="truncate text-slate-400">{kase.title}</div>}
        </div>
      )}
      <nav aria-label="Primary" className="flex-1 space-y-3 overflow-y-auto px-2 pb-4">
        {NAV.map((g) => (
          <div key={g.id}>
            {!collapsed && <div className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">{g.label}</div>}
            <ul className="space-y-0.5">
              {g.items
                .filter((i) => !i.perm || can(i.perm))
                .map((i) => {
                  const to = i.to(caseId)
                  const short = i.label.split(/[ &]+/).map((w) => w[0]).join('').slice(0, 2)
                  return (
                    <li key={i.id}>
                      {to ? (
                        <NavLink to={to} end aria-label={collapsed ? i.label : undefined} title={i.label} className={({ isActive }) => link(isActive)}>
                          {collapsed ? <span aria-hidden="true">{short}</span> : i.label}
                        </NavLink>
                      ) : (
                        <span
                          aria-disabled="true"
                          title="Select or create a case first"
                          className="flex cursor-not-allowed items-center rounded-md px-3 py-1.5 text-sm text-slate-400"
                        >
                          {collapsed ? <span aria-hidden="true">{short}</span> : i.label}
                          {collapsed && <span className="sr-only">{i.label} (select a case first)</span>}
                        </span>
                      )}
                    </li>
                  )
                })}
            </ul>
          </div>
        ))}
      </nav>
    </aside>
  )
}

function CaseSwitcher() {
  const { caseId, cases } = useCase()
  const nav = useNavigate()
  const { pathname } = useLocation()
  if (cases.length === 0) return null
  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="text-slate-300">Case</span>
      <select
        value={caseId ?? ''}
        onChange={(e) => {
          const id = e.target.value
          if (!id) return
          nav(/^\/cases\/\d+\//.test(pathname) ? pathname.replace(/^\/cases\/\d+/, `/cases/${id}`) : `/cases/${id}`)
        }}
        className="max-w-56 rounded-md bg-navy-900 px-2 py-1 ring-1 ring-navy-600"
      >
        {caseId == null && <option value="">Select a case…</option>}
        {cases.map((c) => (
          <option key={c.id} value={c.id}>
            {c.case_number}
          </option>
        ))}
      </select>
    </label>
  )
}

export default function Shell() {
  const { user, logout } = useAuth()
  const api = API_STATUS[useBackendStatus()]
  const { caseId, st } = useCaseStatus()
  const { pathname } = useLocation()
  const mainRef = useRef<HTMLElement>(null)
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const [jobsOpen, setJobsOpen] = useState(false)
  useRouteFocus(mainRef)

  const toggle = () => {
    setCollapsed((c) => {
      try {
        localStorage.setItem('nirikshan.sidebar', c ? '0' : '1')
      } catch {
        // preference only
      }
      return !c
    })
  }

  return (
    <DetailDrawerProvider>
      <div className="flex min-h-screen">
        <a href="#main" className="skip-link">
          Skip to main content
        </a>
        <Sidebar collapsed={collapsed} toggle={toggle} />
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-navy-700 px-6 py-2.5">
            <CaseSwitcher />
            <StatusChips caseId={caseId} st={st} />
            <div className="ml-auto flex flex-wrap items-center gap-3">
              <span role="status" aria-live="polite"><Chip tone={api.tone}>{api.label}</Chip></span>
              <Button onClick={() => setJobsOpen((o) => !o)} aria-expanded={jobsOpen} aria-controls="jobs-drawer">
                Jobs
              </Button>
              {user && (
                <span className="flex items-center gap-2 text-sm" data-testid="whoami">
                  <span>{user.display_name}</span>
                  <Chip tone="accent">{ROLE_LABEL[user.role]}</Chip>
                  <Button onClick={() => void logout()}>Sign out</Button>
                </span>
              )}
            </div>
          </header>
          <StatusBanners caseId={caseId} st={st} />
          <main id="main" ref={mainRef} tabIndex={-1} className="min-w-0 flex-1 p-6">
            <ErrorBoundary key={pathname}>
              <Outlet />
            </ErrorBoundary>
          </main>
          <footer data-testid="tier-limit" className="border-t border-navy-700 px-6 py-2 text-xs text-slate-400">
            {TIER_LIMIT}
          </footer>
        </div>
        <JobsDrawer open={jobsOpen} onClose={() => setJobsOpen(false)} />
      </div>
    </DetailDrawerProvider>
  )
}
