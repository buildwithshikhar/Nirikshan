import { useEffect, useState } from 'react'
import { Link, Route, Routes, useParams, useSearchParams } from 'react-router-dom'
import { API_URL } from '../../lib/http'
import { useDetailDrawer } from '../../shell/DetailDrawer'
import { EvidencePicker } from '../../shell/EvidencePicker'
import {
  Button, Card, Chip, type Column, DataTable, EmptyState, Field, FieldStatusChip, KV, Loadable, PageHeader, Tabs, TierChip,
  TriageLabel, Unavailable, fmtBytes, inputClass, useAsync, useToast,
} from '../../ui'
import { useAuth } from '../../auth/AuthContext'
import { READONLY_HINT } from '../../ui'
import { evidenceApi } from '../evidence/api'
import JobProgress from './JobProgress'
import { type ClipRow, type Job, type ParsedField, type ParserResult, type RawTimestamp, type Run, hex, parseJson, recoveryApi } from './api'

const fmtVal = (v: unknown) => (typeof v === 'string' ? v : JSON.stringify(v))
const DECODE_TONE = { ok: 'ok', decode_errors: 'warn', export_failed: 'bad', not_exported: 'neutral' } as const
const DecodeChip = ({ s }: { s: string }) => <Chip tone={DECODE_TONE[s as keyof typeof DECODE_TONE] ?? 'neutral'} testId="decode-status">{s}</Chip>

function clipColumns(caseId: number): Column<ClipRow>[] {
  return [
    { key: 'seq', header: '#', sort: (c) => c.seq, render: (c) => c.seq },
    {
      key: 'clip', header: 'Clip', sort: (c) => c.id,
      render: (c) =>
        c.kind === 'clip' ? (
          <Link className="text-accent hover:underline" to={`/cases/${caseId}/recovery/clips/${c.id}`}>Clip {c.id}</Link>
        ) : (
          <span>Orphan {c.id}</span>
        ),
    },
    { key: 'engine', header: 'Engine / codec', sort: (c) => c.engine, render: (c) => <span data-testid="clip-engine">{c.engine}</span>, text: (c) => `${c.engine} ${c.codec}` },
    { key: 'ch', header: 'Channel', sort: (c) => c.channel ?? -1, render: (c) => (c.channel != null ? `ch ${c.channel}` : '—') },
    { key: 'off', header: 'Offsets', sort: (c) => c.start_offset, render: (c) => <span className="font-mono text-xs">{hex(c.start_offset)} – {hex(c.end_offset)}</span> },
    { key: 'size', header: 'Size', sort: (c) => c.size_bytes, render: (c) => fmtBytes(c.size_bytes) },
    { key: 'dec', header: 'Decode test', sort: (c) => c.decode_status, render: (c) => <DecodeChip s={c.decode_status} /> },
  ]
}

function RunConsole() {
  const caseId = Number(useParams().caseId)
  return (
    <div className="space-y-4">
      <PageHeader
        title="Recovery lab"
        subtitle="Run console: identify and carve in a background job (subprocess workers with best-effort limits)."
        actions={<Link className="rounded-md bg-navy-700 px-3 py-1.5 text-sm" to={`/cases/${caseId}/recovery/orphans`}>Orphans and failed decodes</Link>}
      />
      <EvidencePicker caseId={caseId}>{(ev) => <Console key={ev.id} caseId={caseId} evId={ev.id} />}</EvidencePicker>
    </div>
  )
}

function Console({ caseId, evId }: { caseId: number; evId: number }) {
  const { can } = useAuth()
  const toast = useToast()
  const runs = useAsync((s) => recoveryApi.runs(evId, s), [evId])
  const [joinGap, setJoinGap] = useState(0)
  const [opts, setOpts] = useState('{}')
  const [job, setJob] = useState<Job | null>(null)
  const [cancelling, setCancelling] = useState(false)
  const [error, setError] = useState('')
  const [note, setNote] = useState('')
  const { reload } = runs

  useEffect(() => {
    recoveryApi.activeJobs(caseId, evId).then((l) => l[0] && setJob(l[0])).catch(() => undefined)
  }, [caseId, evId])

  const activeId = job?.active ? job.id : null
  useEffect(() => {
    if (activeId == null) return
    let stop = false
    let timer: ReturnType<typeof setTimeout>
    const tick = async () => {
      try {
        const j = await recoveryApi.job(activeId)
        if (stop) return
        setJob(j)
        if (!j.active) {
          setCancelling(false)
          reload()
          if (j.status === 'cancelled') setNote(`Analysis cancelled. Run #${j.run_id ?? '?'} is partial: ${j.clips_recorded} clip(s) were fully recorded before the cancel and are listed below; half-written files were removed.`)
          else if (j.status === 'failed') setError(`Analysis failed: ${j.error}`)
          else {
            setNote(`Analysis completed (run #${j.run_id}).`)
            toast.ok('Analysis completed')
          }
          return
        }
      } catch (e) {
        if (stop) return
        setError(`Lost contact with the job: ${(e as Error).message}`)
        return
      }
      timer = setTimeout(tick, 1000)
    }
    timer = setTimeout(tick, 300)
    return () => {
      stop = true
      clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId])

  const start = async () => {
    setError('')
    setNote('')
    let parser_options: Record<string, unknown> = {}
    try {
      parser_options = JSON.parse(opts || '{}')
    } catch {
      setError('Parser options must be valid JSON, e.g. {"Dahua": {"frame_gap_tolerance": 3}}')
      return
    }
    try {
      const j = await recoveryApi.submit(evId, { join_gap: joinGap, parser_options })
      setJob(j)
      if (j.existing) setNote('An identical analysis is already running; showing its progress.')
    } catch (e) {
      setError((e as Error).message)
      reload()
    }
  }
  const cancel = async () => {
    if (!job) return
    setCancelling(true)
    try {
      setJob(await recoveryApi.cancel(job.id))
    } catch (e) {
      setError((e as Error).message)
      setCancelling(false)
    }
  }
  const busy = job?.active === true
  const writable = can('case.write')
  return (
    <div className="space-y-4">
      <Card title="Start analysis">
        <div className="flex flex-wrap items-end gap-4">
          <Button variant="primary" onClick={start} disabled={busy || !writable} title={writable ? undefined : READONLY_HINT}>
            {busy ? 'Analyzing…' : 'Identify + carve'}
          </Button>
          <Field label="Fragment join gap (bytes, 0 = off)">
            <input type="number" min={0} value={joinGap} disabled={!writable} onChange={(e) => setJoinGap(Number(e.target.value))} className={`${inputClass} w-32`} />
          </Field>
          <Field label="Parser options (JSON by vendor)">
            <input aria-label="Parser options" value={opts} disabled={!writable} onChange={(e) => setOpts(e.target.value)} className={`${inputClass} w-72 font-mono`} />
          </Field>
        </div>
        <p className="mt-2 text-xs text-slate-400">
          The image hash is re-verified first. Carving is vendor-agnostic H.264/H.265 recovery; results are leads to be reviewed, not a statement of what was recorded.
          Reference test data built from published research; no vendor is validated on a real device (nothing above Tier B).
        </p>
      </Card>
      {job?.active && <JobProgress job={job} onCancel={cancel} cancelling={cancelling} />}
      {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
      <p role="status" aria-live="polite" className={note ? 'text-sm text-slate-300' : 'sr-only'} data-testid="analysis-note">{note}</p>
      <Loadable state={runs} rows={4}>
        {(list) => (list.length === 0 ? (
          <EmptyState title="No analysis has been run on this evidence yet" hint={writable ? 'Choose "Identify + carve" to start a background job.' : 'An examiner must start the analysis.'} />
        ) : (
          <RunResults caseId={caseId} run={list[0]} />
        ))}
      </Loadable>
    </div>
  )
}

function RunResults({ caseId, run }: { caseId: number; run: Run }) {
  const clips = run.clips.filter((c) => c.kind === 'clip')
  const orphans = run.clips.length - clips.length
  return (
    <div className="space-y-4">
      <Card title="Vendor identification" className="text-sm" >
        <div data-testid="vendor-section">
          {run.vendor_matches.length === 0 ? (
            <p>Unknown vendor: no documented signature found. Clips were still carved generically.</p>
          ) : (
            run.vendor_matches.map((m) => (
              <p key={m.vendor} className="flex flex-wrap items-center gap-2">
                <b>{m.vendor}</b> <TierChip tier={m.tier} /> <span>confidence <b>{m.confidence}</b></span>
              </p>
            ))
          )}
          <p className="mt-2 text-xs text-slate-400">
            Run #{run.id} {run.status} · tool {run.tool_version} · {run.ffmpeg_version} · identify {run.identify_seconds.toFixed(2)} s · carve {run.carve_seconds.toFixed(2)} s ·{' '}
            {clips.length} clips, {orphans} orphans, {run.stats.decode_errors ?? 0} with decode errors, {run.stats.export_failed ?? 0} export failures
            {run.error && <span className="text-red-300"> · {run.error}</span>}
          </p>
        </div>
      </Card>
      <Card title="Clips">
        <DataTable rows={clips} columns={clipColumns(caseId)} caption={`Clips recovered by run ${run.id}`} rowKey={(c) => c.id} empty={{ title: 'No clips recovered', hint: 'See orphan fragments for what was found but not exported.' }} />
      </Card>
    </div>
  )
}

/** There is no GET /api/clips/{id}: find the clip through the runs of the case's evidence. */
async function findClip(caseId: number, clipId: number, hint: number | null, signal: AbortSignal) {
  const items = await evidenceApi.list(caseId, signal)
  const order = [...items].sort((a, b) => Number(b.id === hint) - Number(a.id === hint))
  for (const ev of order) {
    for (const run of await recoveryApi.runs(ev.id, signal)) {
      const clip = run.clips.find((c) => c.id === clipId)
      if (clip) return { clip, run, evidenceId: ev.id }
    }
  }
  throw new Error(`Clip ${clipId} was not found in this case`)
}

function ParserTab({ clip, run }: { clip: ClipRow; run: Run }) {
  const drawer = useDetailDrawer()
  const parser: ParserResult | undefined = run.parsers.find((p) => p.vendor === clip.engine || p.parser === clip.engine)
  const parsed = parseJson<{ fields?: ParsedField[]; timestamps?: RawTimestamp[] }>(clip.parsed_json, {})
  const fields = parsed.fields ?? []
  const stamps = parsed.timestamps ?? []
  const match = run.vendor_matches.find((m) => m.vendor === clip.engine)
  if (!parser)
    return <EmptyState title="This clip came from generic carving" hint="No vendor parser produced it, so there are no parsed fields. See the Generic carving tab." />
  const showTier = () =>
    drawer.show(`${parser.parser} parser`, (
      <div className="space-y-3 text-sm">
        <KV items={[['Tier', <TierChip key="t" tier={parser.tier} />], ['Identification confidence', match?.confidence ?? 'not matched'], ['Parser status', parser.status], ['Options', <code key="o" className="text-xs">{JSON.stringify(parser.options)}</code>]]} />
        <p className="text-xs text-slate-300">Reference test data from published research; unvalidated on real devices. Tier is not changed by parsing.</p>
        {(match?.basis ?? []).map((b) => <p key={b} className="text-xs text-slate-400">{b}</p>)}
      </div>
    ))
  const showField = (f: ParsedField) =>
    drawer.show(f.name, <KV items={[['Status', <FieldStatusChip key="s" status={f.status} />], ['Value', <code key="v" className="break-all text-xs">{fmtVal(f.value)}</code>], ['Source', f.source], ['Note', f.note || '—']]} />)
  return (
    <div className="space-y-4" data-testid="parser-panel">
      <Card
        title={`Parser: ${parser.parser}`}
        actions={<Button onClick={showTier}>Tier and confidence</Button>}
      >
        <p className="flex flex-wrap items-center gap-2 text-sm">
          <TierChip tier={parser.tier} /> <span data-testid="parser-name" className="sr-only">{parser.parser}</span> <Chip tone={parser.status === 'parsed' ? 'ok' : parser.status === 'partial' ? 'warn' : 'bad'} testId="parser-status">{parser.status}</Chip>
          <span className="text-xs text-slate-400">Timestamps are raw values; no timezone is assumed.</span>
        </p>
        {[...parser.warnings, ...parser.inconsistencies].map((w, i) => <p key={i} className="mt-1 text-xs text-amber-300">{w}</p>)}
      </Card>
      <Card title="Fields of this clip">
        <DataTable
          rows={fields}
          caption="Fields read by the parser for this clip and their status"
          rowKey={(f) => f.name}
          onRowClick={showField}
          columns={[
            { key: 'n', header: 'Field', sort: (f) => f.name, render: (f) => <button className="font-mono text-left text-accent hover:underline" onClick={() => showField(f)}>{f.name}</button> },
            { key: 's', header: 'Status', sort: (f) => f.status, render: (f) => <span data-testid={`field-${f.status}`}><FieldStatusChip status={f.status} /></span> },
            { key: 'v', header: 'Value', render: (f) => <span className="break-all">{fmtVal(f.value)}</span>, text: (f) => fmtVal(f.value) },
            { key: 'src', header: 'Source', render: (f) => <span className="text-slate-300">{f.source}</span> },
          ]}
          empty={{ title: 'The parser recorded no fields for this clip' }}
        />
      </Card>
      <Card title="Raw timestamps (as stored)">
        {stamps.length === 0 ? <p className="text-sm text-slate-300">No timestamps recorded.</p> : (
          <ul className="space-y-1 text-xs" data-testid="raw-timestamps">
            {stamps.map((t, i) => (
              <li key={i}>{t.field} @ {hex(t.offset)}: raw <code>{String(t.raw)}</code> ({t.format}); as stored {t.wall_clock_as_stored || 'n/a'}; timezone: <b>{t.tz_basis}</b></li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}

function CarvingTab({ clip }: { clip: ClipRow }) {
  const notes = parseJson<string[]>(clip.notes_json, [])
  return (
    <Card title="Generic carving facts">
      <KV items={[
        ['Engine', clip.engine], ['Codec', clip.codec], ['NAL units', String(clip.nal_count)], ['IRAP pictures', String(clip.irap_count)], ['VCL units', String(clip.vcl_count)],
        ['Reassembled', clip.reassembled ? 'yes (heuristic fragment join)' : 'no'], ['End reason', clip.reason || '—'], ['Notes', notes.length ? notes.join('; ') : '—'],
      ]} />
    </Card>
  )
}

function CrossTab({ clip, run }: { clip: ClipRow; run: Run }) {
  const p = run.parsers.find((x) => x.vendor === clip.engine || x.parser === clip.engine) ?? run.parsers[0]
  if (!p) return <EmptyState title="No parser ran for this evidence" hint="Cross-checking compares a vendor parser with the generic carver." />
  const dis = p.crosscheck?.disagreements ?? []
  return (
    <Card title={`Cross-check: ${p.parser} parser vs generic carver`}>
      <p className="text-sm" data-testid="crosscheck">{p.crosscheck?.parser_clips ?? 0} parser clips, {p.crosscheck?.generic_clips ?? 0} generic clips, {dis.length} disagreement(s)</p>
      <ul className="mt-2 space-y-1 text-xs text-amber-300">
        {dis.map((d, i) => <li key={i}>{String(d.kind)}: {JSON.stringify(d)}</li>)}
      </ul>
    </Card>
  )
}

function PlayerTab({ clip, caseId }: { clip: ClipRow; caseId: number }) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const verify = async () => {
    setBusy(true)
    try {
      const r = await recoveryApi.verifyClip(clip.id)
      if (r.ok) toast.ok('Clip MP4 hash matches the carve-time hash')
      else toast.error(new Error('Clip MP4 hash does NOT match the carve-time hash'))
    } catch (e) {
      toast.error(e)
    } finally {
      setBusy(false)
    }
  }
  if (!clip.has_video) return <Unavailable what="Playback" reason="No MP4 was exported for this clip." />
  return (
    <Card title="Player">
      <video controls preload="metadata" data-testid="clip-video" aria-label={`Preview of clip ${clip.id}`} src={`${API_URL}/api/clips/${clip.id}/video`} className="max-w-full rounded" />
      <p className="mt-2 text-xs text-slate-400">Duration is nominal (25 fps assumed without timing info); it is not a recording time. Browser playback depends on H.264 support.</p>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button busy={busy} onClick={verify}>Verify clip hash</Button>
        <Link className="text-accent hover:underline" to={`/cases/${caseId}/triage?clip=${clip.id}`}>AI triage for this clip</Link>
        <TriageLabel />
      </div>
    </Card>
  )
}

function BitstreamTab({ clip }: { clip: ClipRow }) {
  const extents = parseJson<number[][]>(clip.extents_json, [])
  return (
    <Card title="Bitstream and hash info">
      <KV items={[
        ['Bitstream SHA-256', <code key="b" className="break-all text-xs">{clip.bitstream_sha256}</code>],
        ['MP4 SHA-256', <code key="m" className="break-all text-xs">{clip.mp4_sha256 || 'not exported'}</code>],
        ['Offsets', `${clip.start_offset.toLocaleString()} – ${clip.end_offset.toLocaleString()} (${hex(clip.start_offset)} – ${hex(clip.end_offset)})`],
        ['Extents', extents.map(([a, b]) => `${hex(a)}–${hex(b)}`).join(', ') || '—'],
        ['Size', `${fmtBytes(clip.size_bytes)} (${clip.size_bytes.toLocaleString()} bytes)`],
        ['Picture size', clip.width ? `${clip.width}×${clip.height}` : 'unknown'],
        ['Frames / nominal duration', `${clip.packets ?? '?'} frames, ${clip.duration_s != null ? `${clip.duration_s.toFixed(2)} s` : 'unknown'} at ${clip.fps || '?'}`],
        ['Decode test', <DecodeChip key="d" s={clip.decode_status} />],
      ]} />
    </Card>
  )
}

function LimitsTab({ clip }: { clip: ClipRow }) {
  const rec = useAsync((s) => recoveryApi.recoverability(clip.id, s), [clip.id])
  const frag = useAsync((s) => recoveryApi.fragments(s), [])
  return (
    <div className="space-y-4">
      <Loadable state={rec} rows={3}>
        {(r) => !r.available ? <Unavailable what="Recoverability estimate" reason={r.reason} /> : (
          <Card title="Recoverability estimate (rough)">
            <p className="flex flex-wrap items-center gap-2 text-sm" data-testid="recoverability">
              <Chip tone="warn">ROUGH ESTIMATE</Chip> <b>{r.estimate?.toFixed(2)}</b> ({r.band}) · rule version {r.rule_version}
            </p>
            <p role="note" className="mt-2 rounded bg-navy-900 p-2 text-sm" data-testid="agreement-note">
              Measured agreement with the true recoverable fraction is weak: Pearson correlation{' '}
              <b>{(r.measured_agreement?.overall?.pearson_r ?? 0).toFixed(2)}</b> on reference test data. Treat this as a rough guide, not a measurement.
            </p>
            <p className="mt-2 text-xs text-slate-300">{r.explanation}</p>
            <ul className="mt-2 list-disc pl-5 text-xs text-slate-300">{(r.limitations ?? []).map((l) => <li key={l}>{l}</li>)}</ul>
            {r.measured_agreement?.disclaimer && <p className="mt-2 text-xs text-slate-400">{r.measured_agreement.disclaimer}</p>}
          </Card>
        )}
      </Loadable>
      <Loadable state={frag} rows={2}>
        {(f) => !f.available ? <Unavailable what="Fragment reassembly" reason={f.reason} /> : (
          <Card title="Fragment reassembly (heuristic, off by default)">
            <p className="text-sm">Enable with: {f.enable_with}. Pooled false-accept rate on synthetic scenarios: <b>{((f.pooled_false_accept?.rate ?? 0) * 100).toFixed(1)}%</b> ({f.pooled_false_accept?.k}/{f.pooled_false_accept?.n}).</p>
            <p className="mt-1 text-xs text-slate-400">{f.note}</p>
          </Card>
        )}
      </Loadable>
    </div>
  )
}

function ClipDetail() {
  const { caseId, clipId } = useParams()
  const [sp] = useSearchParams()
  const hint = Number(sp.get('evidence')) || null
  const state = useAsync((s) => findClip(Number(caseId), Number(clipId), hint, s), [caseId, clipId])
  const cid = Number(caseId)
  return (
    <Loadable state={state}>
      {({ clip, run, evidenceId }) => (
        <div>
          <PageHeader
            title={`Clip ${clip.id}${clip.channel != null ? ` (channel ${clip.channel})` : ''}`}
            subtitle={<>{clip.engine} · {clip.codec} · evidence <Link className="text-accent underline" to={`/cases/${cid}/evidence/${evidenceId}`}>#{evidenceId}</Link> · <Link className="text-accent underline" to={`/cases/${cid}/recovery?evidence=${evidenceId}`}>back to run console</Link></>}
          />
          <Tabs label="Clip sections" tabs={[
            { id: 'parser', label: 'Parser results', render: () => <ParserTab clip={clip} run={run} /> },
            { id: 'carving', label: 'Generic carving', render: () => <CarvingTab clip={clip} /> },
            { id: 'crosscheck', label: 'Cross-check', render: () => <CrossTab clip={clip} run={run} /> },
            { id: 'player', label: 'Player', render: () => <PlayerTab clip={clip} caseId={cid} /> },
            { id: 'bitstream', label: 'Bitstream and hash info', render: () => <BitstreamTab clip={clip} /> },
            { id: 'limits', label: 'Recovery limits', render: () => <LimitsTab clip={clip} /> },
          ]} />
        </div>
      )}
    </Loadable>
  )
}

function Orphans() {
  const caseId = Number(useParams().caseId)
  return (
    <div className="space-y-4">
      <PageHeader title="Orphans and failed decodes" subtitle="Fragments that were found but not exported, and clips whose decode test reported problems. Nothing is hidden." />
      <EvidencePicker caseId={caseId}>{(ev) => <OrphanTable key={ev.id} evId={ev.id} caseId={caseId} />}</EvidencePicker>
    </div>
  )
}

function OrphanTable({ evId, caseId }: { evId: number; caseId: number }) {
  const runs = useAsync((s) => recoveryApi.runs(evId, s), [evId])
  return (
    <Card>
      <Loadable state={runs}>
        {(list) => {
          const rows = (list[0]?.clips ?? []).filter((c) => c.kind === 'orphan' || c.decode_status !== 'ok')
          return (
            <DataTable
              rows={rows}
              caption="Orphan fragments and clips with decode problems"
              rowKey={(c) => c.id}
              columns={[
                { key: 'k', header: 'Kind', sort: (c) => c.kind, render: (c) => (c.kind === 'clip' ? <Link className="text-accent hover:underline" to={`/cases/${caseId}/recovery/clips/${c.id}`}>clip {c.id}</Link> : `orphan ${c.id}`), text: (c) => c.kind },
                { key: 'o', header: 'Offsets', sort: (c) => c.start_offset, render: (c) => <span className="font-mono text-xs">{hex(c.start_offset)} – {hex(c.end_offset)}</span> },
                { key: 'c', header: 'Codec', sort: (c) => c.codec, render: (c) => `${c.codec}, ${c.nal_count} NAL` },
                { key: 'd', header: 'Decode', sort: (c) => c.decode_status, render: (c) => <DecodeChip s={c.decode_status} /> },
                {
                  key: 'e', header: 'Errors and reason',
                  render: (c) => (
                    <div className="max-w-md break-all text-xs">
                      {parseJson<string[]>(c.decode_errors_json, []).map((e, i) => <div key={i} className="text-amber-300">{e}</div>)}
                      {c.error && <div className="text-red-300">{c.error}</div>}
                      <div className="text-slate-300">{c.reason}</div>
                    </div>
                  ),
                  text: (c) => `${c.decode_errors_json} ${c.error} ${c.reason}`,
                },
              ]}
              empty={{ title: 'No orphans or failed decodes', hint: list.length ? 'Every recovered clip decoded cleanly.' : 'No analysis has been run on this evidence yet. Start one in the run console.' }}
            />
          )
        }}
      </Loadable>
    </Card>
  )
}

export default function RecoveryModule() {
  return (
    <Routes>
      <Route index element={<RunConsole />} />
      <Route path="clips/:clipId" element={<ClipDetail />} />
      <Route path="orphans" element={<Orphans />} />
    </Routes>
  )
}
