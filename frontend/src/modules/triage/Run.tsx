import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError } from '../../lib/http'
import { useAuth } from '../../auth/AuthContext'
import { Button, Card, Chip, Field, Loadable, PageHeader, READONLY_HINT, StatusChip, TriageLabel, inputClass, useAsync, useToast } from '../../ui'
import { type AnalyticsKind, type Job, analyticsApi, reasonOf } from './api'
import { ClipPicker } from './ClipPicker'
import { TriageNav } from './TriageNav'

export const TRIAGE_STATEMENT =
  'Triage only. Results are leads for an examiner to review; they are not identifications. Face detection finds face-shaped regions and nothing more: there is no recognition and no matching of any person. Error rates were measured on public or synthetic data and were not validated on real DVR footage.'

const TITLE: Record<AnalyticsKind, string> = { motion: 'Motion', objects: 'Objects', faces: 'Face detection' }
const DEFAULTS: Record<AnalyticsKind, Record<string, number>> = {
  motion: { stride: 2, threshold: 25, min_area: 24, blur: 1 },
  objects: { stride: 25, conf_threshold: 0.3, max_samples: 200 },
  faces: { stride: 25, conf_threshold: 0.5, max_samples: 200 },
}

function ModelsCard() {
  const models = useAsync(() => analyticsApi.models(), [])
  return (
    <Card title="Detector models">
      <Loadable state={models} rows={2}>
        {(m) => (
          <ul className="space-y-2 text-sm" data-testid="models-list">
            <li>Motion: frame differencing / background subtraction, no model.</li>
            {m.models.map((x) => (
              <li key={x.name} className="flex flex-wrap items-center gap-2">
                <span>{x.name} {x.version} · licence {x.licence}</span>
                {x.installed ? <Chip tone="ok">installed</Chip> : <Chip tone="bad">not installed</Chip>}
                {!x.installed && <span role="note" className="basis-full text-amber-300">{x.error}</span>}
              </li>
            ))}
          </ul>
        )}
      </Loadable>
    </Card>
  )
}

function JobRow({ kind, job, caseId, clipId, onUpdate }: { kind: AnalyticsKind; job: Job; caseId: number; clipId: number; onUpdate: (j: Job) => void }) {
  useEffect(() => {
    if (!job.active) return
    const t = setInterval(() => analyticsApi.job(job.id).then(onUpdate).catch(() => undefined), 1000)
    return () => clearInterval(t)
  }, [job.id, job.active, onUpdate])
  return (
    <li className="flex flex-wrap items-center gap-3 rounded bg-navy-900 p-2 text-sm" data-testid={`job-${kind}`}>
      <span>{TITLE[kind]} job #{job.id}</span>
      <StatusChip status={job.status} />
      <span className="text-slate-300">{job.stage}</span>
      {job.active && <progress aria-label={`${TITLE[kind]} progress`} value={job.progress} max={1} className="w-32" />}
      {job.error && <span role="alert" className="basis-full text-red-300">{job.error}</span>}
      {job.status === 'completed' && (
        <Link className="text-accent underline" to={`/cases/${caseId}/triage/results?clip=${clipId}&tab=${kind}`}>View {TITLE[kind].toLowerCase()} results</Link>
      )}
    </li>
  )
}

function RunForClip({ caseId, clipId }: { caseId: number; clipId: number }) {
  const { can } = useAuth()
  const toast = useToast()
  const [params, setParams] = useState(DEFAULTS)
  const [jobs, setJobs] = useState<{ kind: AnalyticsKind; job: Job }[]>([])
  const [missing, setMissing] = useState<string | null>(null)
  const [busy, setBusy] = useState<AnalyticsKind | null>(null)
  const start = async (kind: AnalyticsKind) => {
    setBusy(kind)
    setMissing(null)
    try {
      const job = await analyticsApi.startJob(clipId, kind, params[kind])
      setJobs((l) => [{ kind, job }, ...l.filter((x) => x.job.id !== job.id)])
      toast.info(`${TITLE[kind]} job #${job.id} queued in a subprocess worker.`)
    } catch (e) {
      if (e instanceof ApiError && e.status === 503) setMissing(reasonOf(e))
      toast.error(reasonOf(e))
    } finally {
      setBusy(null)
    }
  }
  const writable = can('case.write')
  return (
    <div className="space-y-4">
      {!writable && <p className="text-sm text-slate-300">{READONLY_HINT} You can still read results.</p>}
      {missing && (
        <div role="alert" data-testid="model-missing" className="rounded border border-amber-400 bg-navy-900 p-3 text-sm">
          <b className="text-amber-300">A model is missing.</b> {missing}
        </div>
      )}
      <div className="grid gap-4 md:grid-cols-3">
        {(['motion', 'objects', 'faces'] as AnalyticsKind[]).map((k) => (
          <Card key={k} title={TITLE[k]}>
            <div className="space-y-2">
              {Object.keys(DEFAULTS[k]).map((p) => (
                <Field key={p} label={p}>
                  <input
                    type="number"
                    step={p === 'conf_threshold' ? 0.05 : 1}
                    aria-label={`${k} ${p}`}
                    disabled={!writable}
                    value={params[k][p]}
                    onChange={(e) => setParams((s) => ({ ...s, [k]: { ...s[k], [p]: Number(e.target.value) } }))}
                    className={inputClass}
                  />
                </Field>
              ))}
              {writable && <Button variant="primary" busy={busy === k} onClick={() => start(k)}>Run {k}</Button>}
            </div>
          </Card>
        ))}
      </div>
      <p className="text-xs text-slate-300">Runs go through the background job system: a subprocess worker with best-effort resource limits, so the page stays usable while it works.</p>
      {jobs.length > 0 && (
        <ul className="space-y-2" aria-label="Analytics jobs started here">
          {jobs.map(({ kind, job }) => (
            <JobRow key={job.id} kind={kind} job={job} caseId={caseId} clipId={clipId} onUpdate={(j) => setJobs((l) => l.map((x) => (x.job.id === j.id ? { ...x, job: j } : x)))} />
          ))}
        </ul>
      )}
      <p>
        <Link className="text-accent underline" to={`/cases/${caseId}/triage/results?clip=${clipId}`}>Open results for this clip</Link>
      </p>
    </div>
  )
}

export default function Run() {
  const caseId = Number(useParams().caseId)
  return (
    <div>
      <PageHeader title="Run AI triage" subtitle={<span className="inline-flex flex-wrap items-center gap-2"><TriageLabel /> Reference test data only; nothing validated on real devices.</span>} />
      <TriageNav caseId={caseId} />
      <p className="mb-4 rounded-lg bg-navy-800 p-4 text-sm text-slate-300" data-testid="triage-statement">{TRIAGE_STATEMENT}</p>
      <div className="space-y-4">
        <ModelsCard />
        <ClipPicker caseId={caseId}>{(clip) => <RunForClip key={clip.id} caseId={caseId} clipId={clip.id} />}</ClipPicker>
      </div>
    </div>
  )
}
