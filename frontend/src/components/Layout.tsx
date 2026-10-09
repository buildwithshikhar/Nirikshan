import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { getExaminer, setExaminer } from '../api'
import { type BackendStatus, useBackendStatus } from '../useBackendStatus'
import { TIER_LIMIT } from '../dataOrigin'
import StatusBanners from './StatusBanners'

const NAV = [
  { to: '/', label: 'Dashboard' },
  { to: '/cases', label: 'Cases' },
]

const STATUS: Record<BackendStatus, { dot: string; label: string }> = {
  checking: { dot: 'bg-slate-400', label: 'Checking API…' },
  online: { dot: 'bg-emerald-400', label: 'API online' },
  waking: { dot: 'bg-amber-400 animate-pulse', label: 'Waking up API, retrying…' },
  offline: { dot: 'bg-red-500', label: 'API offline' },
}

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-2 text-sm font-medium transition ${
    isActive ? 'bg-accent text-navy-900' : 'text-slate-300 hover:bg-navy-700'
  }`

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
      // never steal focus from a field the user already moved into
      if (!a || a === document.body || !mainRef.current?.contains(a)) mainRef.current?.focus()
    }, 150)
    return () => clearTimeout(t)
  }, [pathname, mainRef])
}

export default function Layout() {
  const status = STATUS[useBackendStatus()]
  const [examiner, setName] = useState(getExaminer())
  const mainRef = useRef<HTMLElement>(null)
  useRouteFocus(mainRef)

  return (
    <div className="flex min-h-screen">
      <a href="#main" className="skip-link">
        Skip to main content
      </a>
      <aside className="hidden w-56 shrink-0 flex-col gap-1 bg-navy-800 p-4 md:flex">
        <div className="mb-6 text-2xl font-bold text-accent">Nirikshan</div>
        <nav aria-label="Primary" className="flex flex-col gap-1">
          {NAV.map(({ to, label }) => (
            <NavLink key={to} to={to} end={to === '/'} className={linkClass}>
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-navy-700 px-6 py-3">
          <span className="font-semibold text-accent md:hidden">Nirikshan</span>
          <nav aria-label="Primary (compact)" className="flex gap-3 text-sm md:hidden">
            {NAV.map(({ to, label }) => (
              <NavLink key={to} to={to} end={to === '/'} className="rounded px-1 text-slate-300 underline">
                {label}
              </NavLink>
            ))}
          </nav>
          <input
            aria-label="Examiner name"
            placeholder="Examiner name (required to act)"
            value={examiner}
            onChange={(e) => {
              setName(e.target.value)
              setExaminer(e.target.value)
            }}
            className="ml-auto w-56 rounded-md bg-navy-800 px-3 py-1 text-xs ring-1 ring-navy-700 focus:ring-accent"
          />
          <div
            className="ml-3 flex items-center gap-2 rounded-full bg-navy-800 px-3 py-1 text-xs"
            role="status"
            aria-live="polite"
          >
            <span aria-hidden="true" className={`h-2 w-2 rounded-full ${status.dot}`} />
            {status.label}
          </div>
        </header>
        <StatusBanners />
        <main id="main" ref={mainRef} tabIndex={-1} className="flex-1 p-6">
          <Outlet />
        </main>
        <footer data-testid="tier-limit" className="border-t border-navy-700 px-6 py-2 text-xs text-slate-400">
          {TIER_LIMIT}
        </footer>
      </div>
    </div>
  )
}
