import { NavLink, useSearchParams } from 'react-router-dom'

/** Switches between Run, Results and Search; carries the chosen clip along. */
export function TriageNav({ caseId }: { caseId: number }) {
  const [sp] = useSearchParams()
  const clip = sp.get('clip')
  const q = clip ? `?clip=${clip}` : ''
  const cls = ({ isActive }: { isActive: boolean }) =>
    `rounded-md px-3 py-1.5 text-sm ${isActive ? 'bg-accent font-semibold text-navy-900' : 'bg-navy-700 text-slate-100 hover:bg-navy-600'}`
  return (
    <nav aria-label="AI triage screens" className="mb-4 flex flex-wrap gap-2">
      <NavLink end to={`/cases/${caseId}/triage${q}`} className={cls}>Run</NavLink>
      <NavLink to={`/cases/${caseId}/triage/results${q}`} className={cls}>Results</NavLink>
      <NavLink to={`/cases/${caseId}/triage/search`} className={cls}>Event search and summaries</NavLink>
    </nav>
  )
}
