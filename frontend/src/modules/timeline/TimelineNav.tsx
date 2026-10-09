import { NavLink } from 'react-router-dom'

/** Switches between the module's two screens (Timeline, Time settings). */
export function TimelineNav({ caseId }: { caseId: number }) {
  const cls = ({ isActive }: { isActive: boolean }) =>
    `rounded-md px-3 py-1.5 text-sm ${isActive ? 'bg-accent font-semibold text-navy-900' : 'bg-navy-700 text-slate-100 hover:bg-navy-600'}`
  return (
    <nav aria-label="Timeline screens" className="mb-4 flex gap-2">
      <NavLink end to={`/cases/${caseId}/timeline`} className={cls}>Timeline</NavLink>
      <NavLink to={`/cases/${caseId}/timeline/time-settings`} className={cls}>Time settings</NavLink>
    </nav>
  )
}
