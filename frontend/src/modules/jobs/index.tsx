import { useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { type JobWithDeps, apiJobs } from '../../api_jobs'
import { useDetailDrawer } from '../../shell/DetailDrawer'
import { Button, Can, Chip, DataTable, EmptyState, ErrorState, KV, PageHeader, Skeleton, StatusChip, Tabs, fmtTime, useAsync, useToast } from '../../ui'

const num = (v: unknown): number[] => (Array.isArray(v) ? v.map(Number) : v == null || v === '' ? [] : [Number(v)])

function JobDetail({ job, all }: { job: JobWithDeps; all: JobWithDeps[] }) {
  const t = (job.timings ?? {}) as { isolated?: boolean; limits_applied?: Record<string, string>; total_s?: number }
  const chain = (id: number | null | undefined, seen = new Set<number>()): string[] => {
    const j = all.find((x) => x.id === id)
    if (!j || seen.has(j.id)) return []
    seen.add(j.id)
    return [...chain(j.depends_on ?? j.retry_of, seen), `#${j.id} ${j.kind} (${j.status})`]
  }
  const upstream = chain(job.depends_on ?? job.retry_of)
  return (
    <div className="space-y-4">
      <KV
        items={[
          ['Status', <StatusChip key="s" status={job.status} />],
          ['Stage', job.stage || '—'],
          ['Evidence', `#${job.evidence_id}`],
          ['Run', job.run_id ? `#${job.run_id}` : '—'],
          ['Examiner', job.examiner],
          ['Created', fmtTime(job.created_at)],
          ['Started', fmtTime(job.started_at)],
          ['Finished', fmtTime(job.finished_at)],
          ['Attempt', String(job.attempt ?? 1)],
          ['Worker', t.isolated ? 'subprocess worker with best-effort limits' : 'in-process'],
          ['Total seconds', t.total_s != null ? t.total_s.toFixed(2) : '—'],
        ]}
      />
      {job.error && <p role="alert" className="rounded border border-red-400 bg-red-950 p-2 text-red-100">{job.error}</p>}
      <div>
        <h3 className="mb-1 font-medium">Dependency chain</h3>
        {upstream.length === 0 && num(job.dependents).length === 0 ? (
          <p className="text-slate-400">This job has no dependencies, retries or dependents.</p>
        ) : (
          <ol className="list-decimal space-y-1 pl-5">
            {upstream.map((u) => <li key={u}>{u} <span className="text-slate-400">(upstream)</span></li>)}
            <li className="font-semibold">#{job.id} {job.kind} (this job)</li>
            {num(job.dependents).map((d) => <li key={d}>#{d} <span className="text-slate-400">(waits for this job)</span></li>)}
          </ol>
        )}
      </div>
      {t.limits_applied && (
        <div>
          <h3 className="mb-1 font-medium">Limits applied (best effort)</h3>
          <KV items={Object.entries(t.limits_applied)} />
        </div>
      )}
    </div>
  )
}

function Table({ jobs, reload, active }: { jobs: JobWithDeps[]; reload: () => void; active: boolean }) {
  const toast = useToast()
  const drawer = useDetailDrawer()
  const run = (fn: () => Promise<unknown>, ok: string) => fn().then(() => (toast.ok(ok), reload())).catch(toast.error)
  const rows = jobs.filter((j) => j.active === active)
  return (
    <DataTable
      testId={active ? 'jobs-running' : 'jobs-history'}
      caption={active ? 'Running jobs' : 'Job history'}
      rows={rows}
      rowKey={(j) => j.id}
      empty={active ? { title: 'Nothing is running', hint: 'Start an analysis from Recovery Lab; it runs here in a subprocess worker.' } : { title: 'No finished jobs yet' }}
      columns={[
        { key: 'id', header: 'Job', render: (j) => <button className="underline" onClick={() => drawer.show(`Job #${j.id}`, <JobDetail job={j} all={jobs} />)}>#{j.id} {j.kind}</button>, sort: (j) => j.id, text: (j) => j.kind },
        { key: 'ev', header: 'Evidence', render: (j) => `#${j.evidence_id}`, sort: (j) => j.evidence_id },
        { key: 'st', header: 'Status', render: (j) => <StatusChip status={j.status} />, sort: (j) => j.status },
        { key: 'stage', header: 'Stage', render: (j) => j.waiting ? <Chip tone="warn">waiting for #{String(j.depends_on)}</Chip> : j.stage || '—', text: (j) => j.stage },
        { key: 'pr', header: 'Progress', render: (j) => `${Math.round(j.progress * 100)}%`, sort: (j) => j.progress },
        { key: 'dep', header: 'Chain', render: (j) => [j.depends_on ? `after #${j.depends_on}` : '', j.retry_of ? `retry of #${j.retry_of}` : ''].filter(Boolean).join(', ') || '—' },
        { key: 'when', header: 'Created', render: (j) => fmtTime(j.created_at), sort: (j) => j.created_at },
        {
          key: 'act',
          header: 'Actions',
          render: (j) => (
            <Can perm="case.write">
              {j.active && <Button onClick={() => run(() => apiJobs.cancel(j.id), `Cancel requested for job #${j.id}`)}>Cancel</Button>}
              {(j.status === 'failed' || j.status === 'cancelled') && <Button onClick={() => run(() => apiJobs.retry(j.id), `Retry queued for job #${j.id}`)}>Retry</Button>}
            </Can>
          ),
        },
      ]}
      pageSize={10}
    />
  )
}

export default function JobsModule() {
  const caseId = Number(useParams().caseId)
  const jobs = useAsync(() => apiJobs.list(caseId), [caseId])
  const anyActive = jobs.data?.some((j) => j.active)
  useEffect(() => {
    if (!anyActive) return
    const t = setInterval(jobs.reload, 2000)
    return () => clearInterval(t)
  }, [anyActive, jobs.reload])
  return (
    <div>
      <PageHeader title="Jobs" subtitle="Analyses run as subprocess workers with best-effort resource limits. Cancel, retry and dependency chains are recorded per job." actions={<Button onClick={jobs.reload}>Refresh</Button>} />
      {jobs.error && !jobs.data ? <ErrorState error={jobs.error} onRetry={jobs.reload} /> : !jobs.data ? <Skeleton rows={4} /> : jobs.data.length === 0 ? (
        <EmptyState title="No jobs in this case yet" hint="Jobs are created when you start an analysis in Recovery Lab." />
      ) : (
        <Tabs
          label="Jobs"
          tabs={[
            { id: 'running', label: `Running (${jobs.data.filter((j) => j.active).length})`, render: () => <Table jobs={jobs.data!} reload={jobs.reload} active /> },
            { id: 'history', label: 'History', render: () => <Table jobs={jobs.data!} reload={jobs.reload} active={false} /> },
          ]}
        />
      )}
    </div>
  )
}
