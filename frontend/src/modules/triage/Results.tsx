import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Card, Chip, DataTable, EmptyState, HashText, Loadable, PageHeader, Tabs, TriageLabel, useAsync } from '../../ui'
import { type AnalyticsKind, type AnalyticsRun, analyticsApi } from './api'
import { ClipPicker } from './ClipPicker'
import ErrorRatePanel from './ErrorRatePanel'
import { TRIAGE_STATEMENT } from './Run'
import { TriageNav } from './TriageNav'

const TITLE: Record<AnalyticsKind, string> = { motion: 'Motion', objects: 'Objects', faces: 'Face detection' }

function RunView({ run, caseId }: { run: AnalyticsRun; caseId: number }) {
  const m = run.model
  const classes = run.kind === 'objects' ? Array.from(new Set(run.detections?.map((d) => d.class_name) ?? [])) : undefined
  return (
    <section className="space-y-3 text-sm" data-testid={`run-${run.kind}`} aria-label={`${TITLE[run.kind]} run ${run.id}`}>
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="font-medium">{TITLE[run.kind]} run #{run.id}</h2>
        <span data-testid="triage-label"><TriageLabel /></span>
        <Chip tone={run.status === 'completed' ? 'ok' : 'bad'} testId="run-status">{run.status}</Chip>
        <Link className="text-accent underline" to={`/cases/${caseId}/recovery/clips/${run.clip_id}`}>Open clip</Link>
      </div>
      {run.error && <p role="alert" className="text-red-300">{run.error}</p>}
      <div className="space-y-1 text-xs text-slate-300">
        {m ? (
          <div data-testid="model-info">
            Model: {m.name} {m.version} · licence {m.licence} · sha256 <span className="font-mono" title={m.sha256} data-testid="model-hash">{m.sha256.slice(0, 12)}</span>
          </div>
        ) : (
          <div>Method: frame differencing / background subtraction (no model)</div>
        )}
        <div>Parameters: <code>{JSON.stringify(run.params)}</code></div>
        <div>
          Tool: Nirikshan {run.tool.nirikshan}, {run.tool.execution_provider}, onnxruntime {run.tool.onnxruntime} · {run.frames_analysed} frames analysed · {run.ms_per_frame} ms/frame
        </div>
        <div>clip bitstream sha256 <HashText value={run.bitstream_sha256} label="bitstream SHA-256" head={16} /></div>
        <div>Frame indices are positions in the exported MP4. Times are NOMINAL (frame index / stream frame rate), not recording times.</div>
      </div>
      {run.kind === 'motion' ? (
        <DataTable
          testId="motion-results"
          caption="Motion intervals detected in the clip"
          rows={run.intervals ?? []}
          rowKey={(i) => i.id}
          empty={{ title: 'No motion intervals at these parameters', hint: 'Lower the threshold on the Run screen and run again.' }}
          columns={[
            { key: 'f', header: 'Frames', sort: (i) => i.start_frame, render: (i) => `${i.start_frame} – ${i.end_frame}` },
            { key: 't', header: 'Nominal time', sort: (i) => i.start_time_s, render: (i) => `${i.start_time_s.toFixed(2)} s – ${i.end_time_s.toFixed(2)} s (NOMINAL)` },
            { key: 'p', header: 'Peak score', sort: (i) => i.score_peak, render: (i) => i.score_peak.toFixed(4) },
            { key: 'm', header: 'Mean score', sort: (i) => i.score_mean, render: (i) => i.score_mean.toFixed(4) },
            { key: 'l', header: 'Label', render: (i) => i.label },
          ]}
        />
      ) : (
        <DataTable
          testId="detection-results"
          caption={run.kind === 'faces' ? 'Face detections (regions only) in sampled frames' : 'Object detections in sampled frames'}
          rows={run.detections ?? []}
          rowKey={(d) => d.id}
          empty={{ title: 'No detections at this confidence threshold', hint: 'Absence of a detection is not evidence of absence.' }}
          columns={[
            { key: 'f', header: 'Frame', sort: (d) => d.frame_index, render: (d) => d.frame_index },
            { key: 't', header: 'Nominal time', sort: (d) => d.nominal_time_s, render: (d) => `${d.nominal_time_s.toFixed(2)} s (NOMINAL)` },
            { key: 'c', header: run.kind === 'faces' ? 'Detected region' : 'Class', sort: (d) => d.class_name, render: (d) => d.class_name },
            { key: 'cf', header: 'Confidence', sort: (d) => d.confidence, render: (d) => d.confidence.toFixed(2) },
            { key: 'b', header: 'Box (x1,y1,x2,y2)', render: (d) => <span className="font-mono">{d.bbox.map((v) => Math.round(v)).join(', ')}</span> },
            { key: 'l', header: 'Label', render: (d) => d.label },
          ]}
        />
      )}
      <p className="text-xs text-slate-300">
        {run.kind === 'faces'
          ? 'A face detection is a box where the detector found a face-shaped region. It says nothing about who, and nothing is compared with any other image.'
          : 'Leads for review only: a detection is a box with a score, not an identification, and absence of a detection is not evidence of absence.'}
      </p>
      <ErrorRatePanel rates={run.error_rates} classes={classes} />
    </section>
  )
}

function KindTab({ kind, runs, caseId, clipId }: { kind: AnalyticsKind; runs: AnalyticsRun[]; caseId: number; clipId: number }) {
  const mine = runs.filter((r) => r.kind === kind)
  const [pick, setPick] = useState<number | null>(null)
  if (mine.length === 0)
    return (
      <EmptyState
        title={`No ${TITLE[kind].toLowerCase()} run for this clip yet`}
        hint="Start one on the Run screen; it runs in the background."
        action={<Link className="rounded bg-accent px-3 py-1.5 text-sm font-semibold text-navy-900" to={`/cases/${caseId}/triage?clip=${clipId}`}>Go to Run</Link>}
      />
    )
  const cur = mine.find((r) => r.id === pick) ?? mine[0]
  return (
    <div className="space-y-3">
      {mine.length > 1 && (
        <label className="flex items-center gap-2 text-sm">
          <span className="text-slate-300">Run</span>
          <select value={cur.id} onChange={(e) => setPick(Number(e.target.value))} className="rounded-md bg-navy-900 px-3 py-1.5 ring-1 ring-navy-600">
            {mine.map((r) => <option key={r.id} value={r.id}>#{r.id} ({r.started_at}, {r.result_count} results)</option>)}
          </select>
        </label>
      )}
      <RunView run={cur} caseId={caseId} />
    </div>
  )
}

function ClipResults({ caseId, clipId }: { caseId: number; clipId: number }) {
  const runs = useAsync(async () => Promise.all((await analyticsApi.runs(clipId)).map((r) => analyticsApi.run(r.id))), [clipId])
  return (
    <Loadable state={runs} rows={5}>
      {(list) => (
        <Card>
          <Tabs
            label="Triage results"
            tabs={[
              { id: 'motion', label: 'Motion', render: () => <KindTab kind="motion" runs={list} caseId={caseId} clipId={clipId} /> },
              { id: 'objects', label: 'Objects', render: () => <KindTab kind="objects" runs={list} caseId={caseId} clipId={clipId} /> },
              { id: 'faces', label: 'Faces', render: () => <KindTab kind="faces" runs={list} caseId={caseId} clipId={clipId} /> },
              {
                id: 'errors',
                label: 'Error rates',
                render: () => (
                  <div className="space-y-4" data-testid="error-rates-tab">
                    <p className="text-sm text-slate-300">Measured on public or synthetic data for the model configuration each run used. Not validated on real DVR footage.</p>
                    {(['motion', 'objects', 'faces'] as AnalyticsKind[]).map((k) => {
                      const r = list.find((x) => x.kind === k)
                      return (
                        <div key={k}>
                          <h2 className="mb-1 font-medium">{TITLE[k]}</h2>
                          {r ? <ErrorRatePanel rates={r.error_rates} /> : <p className="text-sm text-slate-300">No run yet, so no configuration to show rates for.</p>}
                        </div>
                      )
                    })}
                  </div>
                ),
              },
            ]}
          />
        </Card>
      )}
    </Loadable>
  )
}

export default function Results() {
  const caseId = Number(useParams().caseId)
  return (
    <div>
      <PageHeader title="Triage results" subtitle={<span className="inline-flex flex-wrap items-center gap-2"><TriageLabel /> Leads for an examiner, never identifications.</span>} />
      <TriageNav caseId={caseId} />
      <p className="mb-4 rounded-lg bg-navy-800 p-4 text-sm text-slate-300">{TRIAGE_STATEMENT}</p>
      <ClipPicker caseId={caseId}>{(clip) => <ClipResults key={clip.id} caseId={caseId} clipId={clip.id} />}</ClipPicker>
    </div>
  )
}
