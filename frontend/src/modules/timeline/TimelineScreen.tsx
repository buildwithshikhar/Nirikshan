import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { download, errorText } from '../../lib/http'
import { useDetailDrawer } from '../../shell/DetailDrawer'
import { Button, Can, Card, Chip, DataTable, Loadable, PageHeader, Tabs, useAsync, useToast } from '../../ui'
import { type OsdResult, type TimelineItem, tl } from './api'
import TimelineChart from './TimelineChart'
import { TimelineNav } from './TimelineNav'

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
  if (flags.length === 0) return <span className="text-xs text-slate-300">no flags</span>
  return (
    <span className="inline-flex flex-wrap gap-1" data-testid="flags">
      {flags.map((f) => (
        <Chip key={f} tone={f === 'tz_unknown' || f === 'dst_gap' || f === 'invalid_date' ? 'bad' : 'warn'} title={FLAG_HELP[f] ?? f}>
          {f}
        </Chip>
      ))}
    </span>
  )
}

function ItemDetail({ item, caseId }: { item: TimelineItem; caseId: number }) {
  const toast = useToast()
  const [osd, setOsd] = useState<OsdResult>()
  const [busy, setBusy] = useState(false)
  const summary = osd?.summary ?? item.osd
  const recs = [item.start_record, item.end_record].filter((r) => r != null)
  const run = async () => {
    setBusy(true)
    try {
      setOsd(await tl.osdCheck(item.clip_id))
    } catch (e) {
      toast.error(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="space-y-3" data-testid="item-detail">
      <div>
        Clip {item.clip_id} · evidence {item.evidence_id} · channel {item.channel ?? 'n/a'} · {item.engine} · tz status <b>{item.tz_status}</b>
        {item.drift_model_id != null && ` · drift model #${item.drift_model_id}`}
      </div>
      <div className="flex gap-3 text-sm">
        <Link className="text-accent underline" to={`/cases/${caseId}/recovery/clips/${item.clip_id}`}>Open clip</Link>
        <Link className="text-accent underline" to={`/cases/${caseId}/triage?clip=${item.clip_id}`}>AI triage for this clip</Link>
      </div>
      {item.end_note && <div className="text-amber-300">{item.end_note}</div>}
      {recs.map((r, i) => (
        <div key={i} className="space-y-1 border-t border-navy-700 pt-2">
          <div><b>{r.field}</b> · raw <span className="font-mono">{String(r.raw)}</span> @ byte {r.offset} · {r.format}</div>
          <div>As stored (no timezone claim): {r.wall_clock_as_stored}</div>
          <div>Timezone: <b>{r.assumed_timezone ?? 'UNKNOWN'}</b> ({r.tz_status}); epoch basis {r.epoch_basis ?? 'not stated'}; evidence: {r.tz_evidence}</div>
          <div>UTC (uncorrected): {r.utc_lo ?? 'not computed'} .. {r.utc_hi ?? ''}</div>
          <div>UTC (drift-corrected): {r.corrected_utc_lo ?? 'no model'} .. {r.corrected_utc_hi ?? ''}</div>
          {r.candidates.length > 1 && <div className="text-amber-300">Candidate instants: {r.candidates.join(' | ')}</div>}
          <Flags flags={r.flags} />
          {r.conflict_note && <div className="text-amber-300" data-testid="conflict-note">Source conflict: {r.conflict_note}</div>}
          {r.notes.map((n, k) => <div key={k} className="text-slate-300">{n}</div>)}
        </div>
      ))}
      <div className="border-t border-navy-700 pt-2">
        <Can perm="case.write">
          <Button busy={busy} onClick={run}>OSD check</Button>
        </Can>
        {summary && (
          <div className="mt-2" data-testid="osd-result">
            OSD vs metadata: <b data-testid="osd-status">{summary.status}</b>
            {summary.median_delta_s != null &&
              ` · median delta ${summary.median_delta_s.toFixed(2)} s, MAD ${summary.mad_s?.toFixed(2)} s, range [${summary.min_delta_s}, ${summary.max_delta_s}], tolerance ${summary.tolerance_s} s`}
            {summary.reason && ` · ${summary.reason}`}
            {osd && <div className="text-slate-300">OCR: {osd.ocr.library} {osd.ocr.version} ({osd.ocr.licence}). {osd.caveats.join('; ')}.</div>}
          </div>
        )}
      </div>
    </div>
  )
}

export default function TimelineScreen() {
  const caseId = Number(useParams().caseId)
  const toast = useToast()
  const drawer = useDetailDrawer()
  const data = useAsync(() => tl.timeline(caseId), [caseId])
  const open = (it: TimelineItem) => drawer.show(`Clip ${it.clip_id}`, <ItemDetail item={it} caseId={caseId} />)
  const exp = (format: 'csv' | 'json') => download(tl.exportPath(caseId, format), `timeline-case-${caseId}.${format}`).catch((e) => toast.error(errorText(e)))

  return (
    <div>
      <PageHeader
        title="Timeline"
        subtitle="Timestamps are normalised to UTC only where the examiner entered a timezone assumption with its evidence. Nothing is defaulted. Validated on reference test data only; not validated on any real device."
        actions={
          <>
            <Button data-testid="export-csv" onClick={() => exp('csv')}>Export CSV</Button>
            <Button data-testid="export-json" onClick={() => exp('json')}>Export JSON</Button>
          </>
        }
      />
      <TimelineNav caseId={caseId} />
      <Loadable state={data} rows={5}>
        {(t) => {
          const all = [...t.placed, ...t.unplaceable]
          const byId = (id: number) => all.find((i) => i.clip_id === id)!
          return (
            <div className="space-y-4">
              {t.evidence_without_timezone.length > 0 && (
                <div role="alert" data-testid="tz-unknown-summary" className="rounded border border-red-400 bg-red-950 p-3 text-sm font-medium text-red-100">
                  Timezone unknown for evidence {t.evidence_without_timezone.map((e) => `#${e}`).join(', ')}: their clips are NOT placed on the timeline.{' '}
                  <Link className="underline" to={`/cases/${caseId}/timeline/time-settings`}>Set the device timezone</Link>                </div>
              )}
              <Card>
                <Tabs
                  label="Timeline views"
                  tabs={[
                    {
                      id: 'chart',
                      label: 'Chart',
                      render: () => (
                        <div className="space-y-2">
                          <p className="text-sm text-slate-300">{t.counts.placed} placed, {t.counts.unplaceable} unplaceable. Order tie-break: {t.tie_break}. Order is presentation only when bars overlap.</p>
                          <TimelineChart items={t.placed} gaps={t.gaps} onSelect={(id) => open(byId(id))} />
                        </div>
                      ),
                    },
                    {
                      id: 'gaps',
                      label: 'Gaps and overlaps',
                      render: () => (
                        <div className="space-y-6">
                          <div data-testid="gaps">
                            <h2 className="mb-2 font-medium">Gaps ({t.gaps.length})</h2>
                            <DataTable
                              caption="Gaps between consecutive clips on a channel"
                              rows={t.gaps}
                              rowKey={(g) => `${g.after_clip_id}-${g.before_clip_id}`}
                              empty={{ title: 'No gaps above the minimum gap' }}
                              columns={[
                                { key: 'ev', header: 'Evidence / channel', render: (g) => `ev ${g.evidence_id} ch ${g.channel ?? 'n/a'}`, sort: (g) => g.evidence_id },
                                { key: 'clips', header: 'Between', render: (g) => `clip ${g.after_clip_id} and ${g.before_clip_id}` },
                                { key: 'nom', header: 'Nominal (s)', render: (g) => g.gap_s_nominal.toFixed(1), sort: (g) => g.gap_s_nominal },
                                { key: 'range', header: 'Min .. max (s)', render: (g) => `${g.gap_s_min.toFixed(1)} .. ${g.gap_s_max.toFixed(1)}` },
                                { key: 'c', header: 'Certainty', render: (g) => (g.certain ? 'certain' : 'possible (bars overlap)') },
                              ]}
                            />
                          </div>
                          <div data-testid="overlaps">
                            <h2 className="mb-2 font-medium">Overlaps ({t.overlaps.length})</h2>
                            <DataTable
                              caption="Overlapping clips"
                              rows={t.overlaps}
                              rowKey={(o) => `${o.a_clip_id}-${o.b_clip_id}`}
                              empty={{ title: 'No overlaps' }}
                              columns={[
                                { key: 'type', header: 'Type', render: (o) => (o.type === 'same_channel' ? 'SAME CHANNEL (anomaly)' : 'cross channel'), sort: (o) => o.type },
                                { key: 'clips', header: 'Clips', render: (o) => `${o.a_clip_id} and ${o.b_clip_id}` },
                                { key: 'nom', header: 'Nominal (s)', render: (o) => o.overlap_s_nominal.toFixed(1), sort: (o) => o.overlap_s_nominal },
                                { key: 'cert', header: 'Certain (s)', render: (o) => o.overlap_s_certain.toFixed(1) },
                                { key: 'c', header: 'Certainty', render: (o) => (o.certain ? 'certain' : 'possible') },
                              ]}
                            />
                          </div>
                        </div>
                      ),
                    },
                    {
                      id: 'unplaceable',
                      label: 'Unplaceable clips',
                      render: () => (
                        <div data-testid="unplaceable" className="space-y-2">
                          <p className="text-sm text-slate-300">Never drawn on the axis. The reason is shown for each; nothing is defaulted to a timezone.</p>
                          <DataTable
                            caption="Clips that cannot be placed on the timeline"
                            rows={t.unplaceable}
                            rowKey={(u) => u.clip_id}
                            empty={{ title: 'Every clip is placed' }}
                            columns={[
                              { key: 'clip', header: 'Clip', sort: (u) => u.clip_id, render: (u) => <button data-testid="unplaceable-item" className="text-accent underline" onClick={() => open(u)}>Clip {u.clip_id}</button> },
                              { key: 'ev', header: 'Evidence', render: (u) => `${u.evidence_id} (${u.engine})`, sort: (u) => u.evidence_id },
                              { key: 'reason', header: 'Reason', render: (u) => <span data-testid="unplaceable-reason">{u.reason}</span>, text: (u) => u.reason ?? '' },
                              { key: 'flags', header: 'Flags', render: (u) => <Flags flags={u.flags} />, text: (u) => u.flags.join(' ') },
                            ]}
                          />
                        </div>
                      ),
                    },
                  ]}
                />
              </Card>
            </div>
          )
        }}
      </Loadable>
    </div>
  )
}
