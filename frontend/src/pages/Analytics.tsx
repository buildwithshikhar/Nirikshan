import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { type AnalyticsKind, type AnalyticsRun, analyticsApi } from '../api_analytics'
import ErrorRatePanel from '../components/ErrorRatePanel'

// Expected route: /clips/:clipId/analytics
const TRIAGE = 'triage, not identification'

const KIND_TITLE: Record<AnalyticsKind, string> = {
  motion: 'Motion',
  objects: 'Objects',
  faces: 'Face detection',
}

const DEFAULTS: Record<AnalyticsKind, Record<string, number>> = {
  motion: { stride: 2, threshold: 25, min_area: 24, blur: 1 },
  objects: { stride: 25, conf_threshold: 0.3, max_samples: 200 },
  faces: { stride: 25, conf_threshold: 0.5, max_samples: 200 },
}

function Badge() {
  return (
    <span className="rounded bg-orange-950 px-2 py-0.5 text-xs font-medium text-accent ring-1 ring-accent" data-testid="triage-label">
      {TRIAGE}
    </span>
  )
}

function ParamForm({
  kind,
  values,
  onChange,
}: {
  kind: AnalyticsKind
  values: Record<string, number>
  onChange: (k: string, v: number) => void
}) {
  return (
    <div className="flex flex-wrap gap-3">
      {Object.keys(DEFAULTS[kind]).map((k) => (
        <label key={k} className="text-xs text-slate-400">
          {k}{' '}
          <input
            type="number"
            step={k === 'conf_threshold' ? 0.05 : 1}
            value={values[k]}
            aria-label={`${kind} ${k}`}
            onChange={(e) => onChange(k, Number(e.target.value))}
            className="w-24 rounded bg-navy-900 px-2 py-1 text-sm ring-1 ring-navy-700"
          />
        </label>
      ))}
    </div>
  )
}

function RunCard({ run }: { run: AnalyticsRun }) {
  const m = run.model
  const classes = run.kind === 'objects' ? Array.from(new Set(run.detections?.map((d) => d.class_name) ?? [])) : undefined
  return (
    <section className="space-y-3 rounded-lg bg-navy-800 p-5 text-sm" data-testid={`run-${run.kind}`}>
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="font-medium">
          {KIND_TITLE[run.kind]} run #{run.id}
        </h3>
        <Badge />
        <span className={run.status === 'completed' ? 'text-emerald-400' : 'text-red-400'} data-testid="run-status">
          {run.status}
        </span>
      </div>
      {run.error && <p className="text-red-400">{run.error}</p>}
      <div className="space-y-1 text-xs text-slate-300">
        {m ? (
          <div data-testid="model-info">
            Model: {m.name} {m.version} · licence {m.licence} · sha256{' '}
            <span className="font-mono" title={m.sha256} data-testid="model-hash">{m.sha256.slice(0, 12)}</span>
          </div>
        ) : (
          <div>Method: frame differencing / background subtraction (no model)</div>
        )}
        <div>
          Parameters: <code>{JSON.stringify(run.params)}</code>
        </div>
        <div>
          Tool: Nirikshan {run.tool.nirikshan}, {run.tool.execution_provider}, onnxruntime {run.tool.onnxruntime} ·{' '}
          {run.frames_analysed} frames analysed · {run.ms_per_frame} ms/frame
        </div>
        <div className="break-all font-mono text-[11px] text-slate-400">
          clip bitstream sha256 {run.bitstream_sha256 || 'n/a'}
        </div>
        <div className="text-slate-500">
          Frame indices are positions in the exported MP4. Times are NOMINAL (frame index / stream frame rate),
          not recording times.
        </div>
      </div>

      {run.kind === 'motion' ? (
        <table className="w-full text-left text-xs" data-testid="motion-results">
          <thead className="text-slate-400">
            <tr><th className="py-1">Frames</th><th>Nominal time</th><th>Peak score</th><th>Mean score</th><th>Label</th></tr>
          </thead>
          <tbody>
            {run.intervals?.map((i) => (
              <tr key={i.id} className="border-t border-navy-700" data-testid="motion-row">
                <td className="py-1">{i.start_frame} – {i.end_frame}</td>
                <td>{i.start_time_s.toFixed(2)} s – {i.end_time_s.toFixed(2)} s (nominal)</td>
                <td>{i.score_peak.toFixed(4)}</td>
                <td>{i.score_mean.toFixed(4)}</td>
                <td>{i.label}</td>
              </tr>
            ))}
            {run.intervals?.length === 0 && <tr><td colSpan={5} className="py-2 text-slate-400">No motion intervals at these parameters.</td></tr>}
          </tbody>
        </table>
      ) : (
        <table className="w-full text-left text-xs" data-testid="detection-results">
          <thead className="text-slate-400">
            <tr><th className="py-1">Frame</th><th>Nominal time</th><th>Class</th><th>Confidence</th><th>Box (x1,y1,x2,y2)</th><th>Label</th></tr>
          </thead>
          <tbody>
            {run.detections?.map((d) => (
              <tr key={d.id} className="border-t border-navy-700" data-testid="detection-row">
                <td className="py-1">{d.frame_index}</td>
                <td>{d.nominal_time_s.toFixed(2)} s (nominal)</td>
                <td>{d.class_name}</td>
                <td>{d.confidence.toFixed(2)}</td>
                <td className="font-mono">{d.bbox.map((v) => Math.round(v)).join(', ')}</td>
                <td>{d.label}</td>
              </tr>
            ))}
            {run.detections?.length === 0 && <tr><td colSpan={6} className="py-2 text-slate-400">No detections at this confidence threshold.</td></tr>}
          </tbody>
        </table>
      )}
      <p className="text-xs text-slate-400">
        Leads for review only: a detection is a box with a score, not an identification, and absence of a detection
        is not evidence of absence.
      </p>
      <ErrorRatePanel rates={run.error_rates} classes={classes} />
    </section>
  )
}

export default function Analytics() {
  const clipId = Number(useParams().clipId)
  const [runs, setRuns] = useState<AnalyticsRun[]>([])
  const [params, setParams] = useState<Record<AnalyticsKind, Record<string, number>>>(DEFAULTS)
  const [busy, setBusy] = useState<AnalyticsKind | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    analyticsApi
      .runs(clipId)
      .then((list) => Promise.all(list.map((r) => analyticsApi.run(r.id))))
      .then(setRuns)
      .catch((e) => setError(e.message))
  }, [clipId])

  const start = async (kind: AnalyticsKind) => {
    setError('')
    setBusy(kind)
    try {
      const run = await analyticsApi.start(clipId, kind, params[kind])
      setRuns((r) => [run, ...r])
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-2xl font-semibold">Analytics for clip #{clipId}</h1>
        <Badge />
      </div>
      <p className="rounded-lg bg-navy-800 p-4 text-xs text-slate-300" data-testid="triage-statement">
        Triage only. Results are leads for an examiner to review; they are not identifications, and no face
        recognition or matching is performed. Models are small CPU detectors; error rates shown with each run were
        measured on public or synthetic data and were not validated on real DVR footage.
      </p>
      {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
      <div className="grid gap-4 md:grid-cols-3">
        {(['motion', 'objects', 'faces'] as AnalyticsKind[]).map((k) => (
          <section key={k} className="space-y-3 rounded-lg bg-navy-800 p-5">
            <h2 className="font-medium">{KIND_TITLE[k]}</h2>
            <ParamForm kind={k} values={params[k]} onChange={(p, v) => setParams((s) => ({ ...s, [k]: { ...s[k], [p]: v } }))} />
            <button
              disabled={busy !== null}
              onClick={() => start(k)}
              className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50"
            >
              {busy === k ? 'Running…' : `Run ${k}`}
            </button>
          </section>
        ))}
      </div>
      <div className="space-y-4">
        {runs.map((r) => <RunCard key={r.id} run={r} />)}
        {runs.length === 0 && <p className="text-sm text-slate-400">No analytics runs for this clip yet.</p>}
      </div>
    </div>
  )
}
