import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { type Evidence, api } from '../api'
import { type OsdResult, type Timeline as Tl, type TimelineItem, apiTimeline } from '../api_timeline'
import TimeSettings from '../components/TimeSettings'
import TimelineChart from '../components/TimelineChart'

const FLAG_HELP: Record<string, string> = {
  tz_unknown: 'No timezone/epoch-basis assumption: no UTC value computed',
  dst_ambiguous: 'Local time occurs twice (DST fall-back): both candidate instants kept',
  dst_gap: 'Local time does not exist (DST spring-forward)',
  epoch32_signed_overflow: 'Value >= 2^31 (2038 signed-int32 overflow)',
  epoch32_u32_wrap: 'Does not fit u32 or is 0xFFFFFFFF (2106 wrap)',
  invalid_date: 'Not a valid calendar date/time',
  source_conflict: 'Public sources conflict or are silent on the time basis',
  unsupported_format: 'Timestamp format not decoded',
  implausible_date: 'Year outside 1995-2100',
}

function Flags({ flags }: { flags: string[] }) {
  if (flags.length === 0) return <span className="text-xs text-slate-400">no flags</span>
  return (
    <span className="flex flex-wrap gap-1" data-testid="flags">
      {flags.map((f) => (
        <span key={f} title={FLAG_HELP[f] ?? f} data-testid={`flag-${f}`}
          className={`rounded px-2 py-0.5 text-xs ${
            f === 'tz_unknown' || f === 'dst_gap' || f === 'invalid_date'
              ? 'bg-red-900 text-red-200'
              : 'bg-amber-900 text-amber-200'
          }`}>
          {f}
        </span>
      ))}
    </span>
  )
}

function ItemDetail({ item, onOsd, osd, busy }: {
  item: TimelineItem
  onOsd: (id: number) => void
  osd: OsdResult | undefined
  busy: boolean
}) {
  const recs = [item.start_record, item.end_record].filter((r) => r != null)
  const summary = osd?.summary ?? item.osd
  return (
    <div className="space-y-2 rounded bg-navy-900 p-3 text-xs" data-testid="item-detail">
      <div className="font-medium">
        Clip {item.clip_id} · evidence {item.evidence_id} · channel {item.channel ?? 'n/a'} · {item.engine} · tz status{' '}
        <b>{item.tz_status}</b>
        {item.drift_model_id != null && ` · drift model #${item.drift_model_id}`}
      </div>
      {item.end_note && <div className="text-amber-300">{item.end_note}</div>}
      {recs.map((r, i) => (
        <div key={i} className="space-y-0.5 border-t border-navy-700 pt-1">
          <div>
            <b>{r.field}</b> · raw <span className="font-mono">{String(r.raw)}</span> @ byte {r.offset} · {r.format}
          </div>
          <div>As stored (no timezone claim): {r.wall_clock_as_stored}</div>
          <div>
            Timezone: <b>{r.assumed_timezone ?? 'UNKNOWN'}</b> ({r.tz_status}); epoch basis {r.epoch_basis ?? 'not stated'};
            evidence: {r.tz_evidence}
          </div>
          <div>UTC (uncorrected): {r.utc_lo ?? 'not computed'} .. {r.utc_hi ?? ''}</div>
          <div>UTC (drift-corrected): {r.corrected_utc_lo ?? 'no model'} .. {r.corrected_utc_hi ?? ''}</div>
          {r.candidates.length > 1 && <div className="text-amber-300">Candidate instants: {r.candidates.join(' | ')}</div>}
          <Flags flags={r.flags} />
          {r.conflict_note && <div className="text-amber-300" data-testid="conflict-note">Source conflict: {r.conflict_note}</div>}
          {r.notes.map((n, k) => <div key={k} className="text-slate-400">{n}</div>)}
        </div>
      ))}
      <div className="border-t border-navy-700 pt-2">
        <button disabled={busy} onClick={() => onOsd(item.clip_id)}
          className="rounded bg-navy-700 px-3 py-1 hover:bg-navy-600 disabled:opacity-50">
          {busy ? 'Reading overlay…' : 'OSD check'}
        </button>
        {summary && (
          <div className="mt-2" data-testid="osd-result">
            OSD vs metadata: <b data-testid="osd-status">{summary.status}</b>
            {summary.median_delta_s != null &&
              ` · median delta ${summary.median_delta_s.toFixed(2)} s, MAD ${summary.mad_s?.toFixed(2)} s, range [${summary.min_delta_s}, ${summary.max_delta_s}], tolerance ${summary.tolerance_s} s`}
            {summary.reason && ` · ${summary.reason}`}
            {osd && <div className="text-slate-400">OCR: {osd.ocr.library} {osd.ocr.version} ({osd.ocr.licence}). {osd.caveats.join('; ')}.</div>}
          </div>
        )}
      </div>
    </div>
  )
}

export default function TimelinePage() {
  const { id } = useParams()
  const caseId = Number(id)
  const [evidence, setEvidence] = useState<Evidence[]>([])
  const [tl, setTl] = useState<Tl | null>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [osd, setOsd] = useState<Record<number, OsdResult>>({})
  const [busyOsd, setBusyOsd] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    api.listEvidence(caseId).then(setEvidence).catch((e) => setError(e.message))
    apiTimeline.timeline(caseId).then(setTl).catch((e) => setError(e.message))
  }, [caseId])
  useEffect(load, [load])

  const runOsd = async (clipId: number) => {
    setError('')
    setBusyOsd(true)
    try {
      const r = await apiTimeline.osdCheck(clipId)
      setOsd((o) => ({ ...o, [clipId]: r }))
      load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusyOsd(false)
    }
  }

  const all = [...(tl?.placed ?? []), ...(tl?.unplaceable ?? [])]
  const sel = all.find((i) => i.clip_id === selected)

  return (
    <div className="space-y-6">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold">Timeline (case #{caseId})</h1>
        <Link className="text-sm text-accent hover:underline" to={`/cases/${caseId}`}>← Case</Link>
      </div>
      <p className="text-xs text-slate-400">
        Timestamps are normalised to UTC only where the examiner entered a timezone assumption with its evidence.
        Nothing is defaulted. Validated on reference test data only; not validated on any real device.
      </p>
      {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
      {tl && tl.evidence_without_timezone.length > 0 && (
        <div role="alert" data-testid="tz-unknown-summary"
          className="rounded border border-red-500 bg-red-950 p-3 text-sm font-medium text-red-200">
          Timezone unknown for evidence {tl.evidence_without_timezone.map((e) => `#${e}`).join(', ')}: their clips are
          NOT placed on the timeline.
        </div>
      )}

      {evidence.map((e) => (
        <TimeSettings key={e.id} evidenceId={e.id} label={e.label} onChanged={load} />
      ))}

      {tl && (
        <>
          <section className="space-y-3 rounded-lg bg-navy-800 p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="font-medium">
                Cross-camera timeline ({tl.counts.placed} placed, {tl.counts.unplaceable} unplaceable)
              </h2>
              <div className="flex gap-2 text-sm">
                <a data-testid="export-csv" href={apiTimeline.exportUrl(caseId, 'csv')}
                  className="rounded bg-navy-700 px-3 py-1 hover:bg-navy-600">Export CSV</a>
                <a data-testid="export-json" href={apiTimeline.exportUrl(caseId, 'json')}
                  className="rounded bg-navy-700 px-3 py-1 hover:bg-navy-600">Export JSON</a>
              </div>
            </div>
            <TimelineChart items={tl.placed} gaps={tl.gaps} onSelect={setSelected} selected={selected} />
            <p className="text-xs text-slate-400">Order tie-break: {tl.tie_break}. Order is presentation only when bars overlap.</p>
            {sel && <ItemDetail item={sel} onOsd={runOsd} osd={osd[sel.clip_id]} busy={busyOsd} />}
          </section>

          <section className="grid gap-4 md:grid-cols-2">
            <div className="rounded-lg bg-navy-800 p-5 text-sm" data-testid="gaps">
              <h2 className="mb-2 font-medium">Gaps ({tl.gaps.length})</h2>
              {tl.gaps.length === 0 && <p className="text-slate-400">None above the minimum gap.</p>}
              {tl.gaps.map((g, i) => (
                <div key={i} className="border-t border-navy-700 py-1 text-xs">
                  ev {g.evidence_id} ch {g.channel ?? 'n/a'}: clip {g.after_clip_id} to {g.before_clip_id},{' '}
                  {g.gap_s_nominal.toFixed(1)} s (min {g.gap_s_min.toFixed(1)}, max {g.gap_s_max.toFixed(1)}) ·{' '}
                  {g.certain ? 'certain' : 'possible (bars overlap)'}
                </div>
              ))}
            </div>
            <div className="rounded-lg bg-navy-800 p-5 text-sm" data-testid="overlaps">
              <h2 className="mb-2 font-medium">Overlaps ({tl.overlaps.length})</h2>
              {tl.overlaps.length === 0 && <p className="text-slate-400">None.</p>}
              {tl.overlaps.map((o, i) => (
                <div key={i} className="border-t border-navy-700 py-1 text-xs">
                  {o.type === 'same_channel' ? 'SAME CHANNEL (anomaly) ' : ''}clips {o.a_clip_id} and {o.b_clip_id}:{' '}
                  {o.overlap_s_nominal.toFixed(1)} s nominal, {o.overlap_s_certain.toFixed(1)} s certain ·{' '}
                  {o.certain ? 'certain' : 'possible'}
                </div>
              ))}
            </div>
          </section>

          <section className="rounded-lg bg-navy-800 p-5 text-sm" data-testid="unplaceable">
            <h2 className="mb-2 font-medium">Unplaceable ({tl.unplaceable.length})</h2>
            <p className="mb-2 text-xs text-slate-400">Never drawn on the axis. Reason shown for each.</p>
            {tl.unplaceable.map((u) => (
              <div key={u.clip_id} className="border-t border-navy-700 py-2 text-xs" data-testid="unplaceable-item">
                <button className="text-accent hover:underline" onClick={() => setSelected(u.clip_id)}>
                  Clip {u.clip_id}
                </button>{' '}
                (evidence {u.evidence_id}, {u.engine}): <span data-testid="unplaceable-reason">{u.reason}</span>{' '}
                <Flags flags={u.flags} />
              </div>
            ))}
          </section>
        </>
      )}
    </div>
  )
}
