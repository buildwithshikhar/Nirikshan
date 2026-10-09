import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { Loadable, Unavailable } from '../../ui'
import { type Metric, type Unavail, isUnavailable } from './api'

export function ValidationNav() {
  const cls = ({ isActive }: { isActive: boolean }) =>
    `rounded-md px-3 py-1.5 text-sm ${isActive ? 'bg-accent font-semibold text-navy-900' : 'bg-navy-700 text-slate-100 hover:bg-navy-600'}`
  return (
    <nav aria-label="Validation screens" className="mb-4 flex gap-2">
      <NavLink end to="/validation" className={cls}>Validation Center</NavLink>
      <NavLink to="/validation/compatibility" className={cls}>Compatibility Registry</NavLink>
    </nav>
  )
}

/** The API's own circularity statement, shown beside the numbers it governs (never abbreviated). */
export function Basis({ text }: { text: string }) {
  return (
    <p role="note" data-testid="basis" className="mt-2 rounded border border-navy-600 bg-navy-900 p-2 text-xs text-slate-300">
      <b>Read these numbers with this in mind.</b> {text}
    </p>
  )
}

const pct = (r: number) => `${(r * 100).toFixed(1)}%`
/** A rate (with k/n and 95% interval) or a count; the full basis statement is on the element itself. */
export function MetricView({ m }: { m: Metric | null | undefined }) {
  if (!m) return <span className="text-slate-400">n/a</span>
  const body =
    m.rate != null ? (
      <>
        {pct(m.rate)} <span className="text-xs text-slate-300">({m.k}/{m.n}{m.ci95 ? `, 95% CI ${pct(m.ci95[0])} to ${pct(m.ci95[1])}` : ''})</span>
      </>
    ) : m.count != null ? (
      <>{m.count}</>
    ) : (
      <>
        {m.k}/{m.n}
      </>
    )
  return (
    <span title={m.basis} className="whitespace-nowrap">
      {body}
      <sup aria-label="self-consistency on reference test data" className="ml-0.5 text-amber-300">†</sup>
    </span>
  )
}

/** Runs a loader result through Loadable and the {available:false} state. */
export function Avail<T>({ state, children, what }: { state: { data: (T | Unavail) | null; error: Error | null; loading: boolean; reload: () => void }; children: (d: T) => ReactNode; what: string }) {
  return (
    <Loadable state={state} rows={4}>
      {(d) => (isUnavailable(d) ? <Unavailable what={what} reason={d.reason} /> : <>{children(d as T)}</>)}
    </Loadable>
  )
}
