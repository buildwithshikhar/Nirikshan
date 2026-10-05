import { NavLink, Outlet } from 'react-router-dom'
import { type BackendStatus, useBackendStatus } from '../useBackendStatus'

const NAV = [{ to: '/', label: 'Dashboard' }]

const STATUS: Record<BackendStatus, { dot: string; label: string }> = {
  checking: { dot: 'bg-slate-400', label: 'Checking API…' },
  online: { dot: 'bg-emerald-400', label: 'API online' },
  waking: { dot: 'bg-amber-400 animate-pulse', label: 'Waking up API, retrying…' },
  offline: { dot: 'bg-red-500', label: 'API offline' },
}

export default function Layout() {
  const status = STATUS[useBackendStatus()]

  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-56 shrink-0 flex-col gap-1 bg-navy-800 p-4 md:flex">
        <div className="mb-6 text-2xl font-bold text-accent">Nirikshan</div>
        {NAV.map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `rounded-md px-3 py-2 text-sm font-medium transition ${
                isActive
                  ? 'bg-accent text-white'
                  : 'text-slate-300 hover:bg-navy-700'
              }`
            }
          >
            {label}
          </NavLink>
        ))}
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-navy-700 px-6 py-3">
          <span className="font-semibold text-accent md:hidden">Nirikshan</span>
          <nav className="flex gap-3 text-sm md:hidden">
            {NAV.map(({ to, label }) => (
              <NavLink key={to} to={to} end={to === '/'} className="text-slate-300">
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2 rounded-full bg-navy-800 px-3 py-1 text-xs">
            <span className={`h-2 w-2 rounded-full ${status.dot}`} />
            {status.label}
          </div>
        </header>
        <main className="flex-1 p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
