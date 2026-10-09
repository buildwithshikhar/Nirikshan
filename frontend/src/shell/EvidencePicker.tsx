import { useSearchParams } from 'react-router-dom'
import { type Evidence, api } from '../api'
import { EmptyState, Loadable, useAsync } from '../ui'
import { Link } from 'react-router-dom'

/** Evidence selector shared by evidence-scoped screens: keeps the choice in `?evidence=`. */
export function useEvidenceParam(evidence: Evidence[] | null): [Evidence | null, (id: number) => void] {
  const [sp, setSp] = useSearchParams()
  const id = Number(sp.get('evidence')) || null
  const cur = evidence?.find((e) => e.id === id) ?? evidence?.[0] ?? null
  return [
    cur,
    (n) => {
      const next = new URLSearchParams(sp)
      next.set('evidence', String(n))
      setSp(next, { replace: true })
    },
  ]
}

export function EvidencePicker({
  caseId,
  children,
}: {
  caseId: number
  children: (ev: Evidence, all: Evidence[]) => React.ReactNode
}) {
  const list = useAsync(() => api.listEvidence(caseId), [caseId])
  return (
    <Loadable state={list}>
      {(items) => <Inner caseId={caseId} items={items}>{children}</Inner>}
    </Loadable>
  )
}

function Inner({ caseId, items, children }: { caseId: number; items: Evidence[]; children: (ev: Evidence, all: Evidence[]) => React.ReactNode }) {
  const [cur, pick] = useEvidenceParam(items)
  if (!cur)
    return (
      <EmptyState
        title="This case has no evidence yet"
        hint="Acquire an evidence image first."
        action={<Link className="rounded bg-accent px-3 py-1.5 text-sm font-semibold text-navy-900" to={`/cases/${caseId}/evidence/new`}>New acquisition</Link>}
      />
    )
  return (
    <div className="space-y-4">
      <label className="flex items-center gap-2 text-sm">
        <span className="text-slate-300">Evidence item</span>
        <select value={cur.id} onChange={(e) => pick(Number(e.target.value))} className="rounded-md bg-navy-900 px-3 py-1.5 ring-1 ring-navy-600">
          {items.map((e) => (
            <option key={e.id} value={e.id}>
              #{e.id} {e.label}
            </option>
          ))}
        </select>
      </label>
      {children(cur, items)}
    </div>
  )
}
