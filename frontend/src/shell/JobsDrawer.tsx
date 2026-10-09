import { Link } from 'react-router-dom'
import { type Job, apiJobs } from '../api_jobs'
import { Can, Button, Drawer, EmptyState, ErrorState, Skeleton, StatusChip, useToast } from '../ui'
import { useEffect, useState } from 'react'
import { useCase } from './CaseContext'

/** Jobs drawer: the case's jobs, refreshed every 3 s while open; cancel for those who may. */
export function JobsDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { caseId } = useCase()
  const toast = useToast()
  const [jobs, setJobs] = useState<Job[] | null>(null)
  const [err, setErr] = useState<Error | null>(null)

  useEffect(() => {
    if (!open || caseId == null) return
    let alive = true
    const load = () =>
      apiJobs
        .list(caseId)
        .then((j) => alive && (setJobs(j), setErr(null)))
        .catch((e) => alive && setErr(e))
    load()
    const t = setInterval(load, 3000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [open, caseId])

  const cancel = (id: number) =>
    apiJobs.cancel(id).then(() => toast.ok(`Cancel requested for job #${id}`)).catch(toast.error)

  return (
    <Drawer open={open} title="Jobs" onClose={onClose} testId="jobs-drawer">
      {caseId == null ? (
        <EmptyState title="No case selected" hint="Pick a case to see its jobs." />
      ) : err && !jobs ? (
        <ErrorState error={err} />
      ) : !jobs ? (
        <Skeleton />
      ) : jobs.length === 0 ? (
        <EmptyState title="No jobs in this case yet" hint="Analyses started from Recovery Lab appear here." />
      ) : (
        <ul className="space-y-3">
          {jobs.slice(0, 15).map((j) => (
            <li key={j.id} className="rounded bg-navy-900 p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">
                  #{j.id} {j.kind}
                </span>
                <StatusChip status={j.status} />
              </div>
              <div className="mt-1 text-xs text-slate-400">{j.stage || '—'}</div>
              {j.active && (
                <div className="mt-2 h-2 rounded bg-navy-700" role="progressbar" aria-valuenow={Math.round(j.progress * 100)} aria-valuemin={0} aria-valuemax={100} aria-label={`Job ${j.id} progress`}>
                  <div className="h-2 rounded bg-accent" style={{ width: `${Math.round(j.progress * 100)}%` }} />
                </div>
              )}
              {j.active && (
                <Can perm="case.write">
                  <Button className="mt-2" onClick={() => cancel(j.id)}>
                    Cancel
                  </Button>
                </Can>
              )}
            </li>
          ))}
        </ul>
      )}
      {caseId != null && (
        <Link className="mt-4 inline-block underline" to={`/cases/${caseId}/jobs`} onClick={onClose}>
          Open the Jobs screen
        </Link>
      )}
    </Drawer>
  )
}
