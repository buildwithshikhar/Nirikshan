import { NavLink } from 'react-router-dom'

/** Switches between the module's two screens (Builder, Exports). */
export function ReportsNav({ caseId }: { caseId: number }) {
  const cls = ({ isActive }: { isActive: boolean }) =>
    `rounded-md px-3 py-1.5 text-sm ${isActive ? 'bg-accent font-semibold text-navy-900' : 'bg-navy-700 text-slate-100 hover:bg-navy-600'}`
  return (
    <nav aria-label="Report studio screens" className="mb-4 flex gap-2">
      <NavLink end to={`/cases/${caseId}/reports`} className={cls}>Builder</NavLink>
      <NavLink to={`/cases/${caseId}/reports/exports`} className={cls}>Exports</NavLink>
    </nav>
  )
}
