import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { API_URL, type CarveRunInfo, type ClipRow, type Evidence, api } from '../api'

const STATUS_STYLE: Record<string, string> = {
  ok: 'text-emerald-400',
  decode_errors: 'text-amber-400',
  export_failed: 'text-red-400',
  not_exported: 'text-slate-400',
}

function hex(n: number) {
  return `0x${n.toString(16)}`
}

function ClipItem({ clip, onVerify }: { clip: ClipRow; onVerify: (id: number) => void }) {
  const errors: string[] = JSON.parse(clip.decode_errors_json || '[]')
  const notes: string[] = JSON.parse(clip.notes_json || '[]')
  return (
    <tr className="border-t border-navy-700 align-top" data-testid={`clip-${clip.kind}`}>
      <td className="py-2">{clip.seq}</td>
      <td>{clip.codec}{clip.reassembled ? <div className="text-xs text-amber-400">reassembled (heuristic)</div> : null}</td>
      <td className="font-mono text-xs">
        {clip.start_offset.toLocaleString()} – {clip.end_offset.toLocaleString()}
        <div className="text-slate-500">{hex(clip.start_offset)} – {hex(clip.end_offset)}</div>
        <div className="text-slate-500">{clip.size_bytes.toLocaleString()} B</div>
      </td>
      <td className="font-mono text-[11px] break-all">
        <div>bitstream {clip.bitstream_sha256}</div>
        <div>mp4 {clip.mp4_sha256}</div>
      </td>
      <td className="text-xs">
        {clip.width ? `${clip.width}×${clip.height}` : '—'}
        <div title="From the stream frame rate (25 fps assumed without timing info); not a recording time">
          {clip.duration_s != null ? `${clip.duration_s.toFixed(2)} s nominal` : '—'} · {clip.packets ?? '?'} frames
        </div>
        <div className="text-slate-500">{clip.irap_count} IRAP · {clip.nal_count} NAL</div>
      </td>
      <td className="text-xs">
        <div className={STATUS_STYLE[clip.decode_status] ?? ''} data-testid="decode-status">{clip.decode_status}</div>
        {errors.map((e, i) => <div key={i} className="max-w-xs break-all text-amber-300">{e}</div>)}
        {clip.error && <div className="max-w-xs break-all text-red-400">{clip.error}</div>}
        {notes.map((n, i) => <div key={i} className="text-slate-400">{n}</div>)}
        <div className="text-slate-500">{clip.reason}</div>
      </td>
      <td>
        {clip.has_video && (
          <div className="space-y-1">
            <video controls preload="metadata" width={220} data-testid="clip-video"
              src={`${API_URL}/api/clips/${clip.id}/video`} />
            <button className="rounded bg-navy-700 px-2 py-0.5 text-xs hover:bg-navy-900" onClick={() => onVerify(clip.id)}>
              Verify MP4 hash
            </button>
          </div>
        )}
      </td>
    </tr>
  )
}

export default function Analysis() {
  const { caseId, id } = useParams()
  const evId = Number(id)
  const cId = Number(caseId)
  const [ev, setEv] = useState<Evidence | undefined>()
  const [run, setRun] = useState<CarveRunInfo | null>(null)
  const [joinGap, setJoinGap] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [note, setNote] = useState('')

  const load = useCallback(() => {
    api.getEvidence(cId, evId).then(setEv).catch((e) => setError(e.message))
    api.runs(evId).then((r) => setRun(r[0] ?? null)).catch((e) => setError(e.message))
  }, [cId, evId])
  useEffect(load, [load])

  const analyze = async () => {
    setError('')
    setBusy(true)
    try {
      setRun(await api.analyze(evId, { join_gap: joinGap }))
    } catch (e) {
      setError((e as Error).message)
      load()
    } finally {
      setBusy(false)
    }
  }

  const verifyClip = async (clipId: number) => {
    try {
      const r = await api.verifyClip(clipId)
      setNote(`Clip ${clipId} MP4 hash ${r.ok ? 'matches' : 'DOES NOT MATCH'} the carve-time hash`)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const clips = run?.clips.filter((c) => c.kind === 'clip') ?? []
  const orphans = run?.clips.filter((c) => c.kind === 'orphan') ?? []

  return (
    <div className="space-y-6">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold">Analyze evidence {ev ? `#${ev.id}: ${ev.label}` : ''}</h1>
        <Link className="text-sm text-accent hover:underline" to={`/cases/${cId}`}>← Case</Link>
      </div>
      <section className="space-y-3 rounded-lg bg-navy-800 p-5">
        <div className="flex flex-wrap items-center gap-4">
          <button disabled={busy} onClick={analyze}
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50">
            {busy ? 'Analyzing…' : 'Identify + carve'}
          </button>
          <label className="text-xs text-slate-400">
            Fragment join gap (bytes, 0 = off){' '}
            <input type="number" min={0} value={joinGap} onChange={(e) => setJoinGap(Number(e.target.value))}
              className="w-28 rounded bg-navy-900 px-2 py-1 text-sm ring-1 ring-navy-700" />
          </label>
        </div>
        <p className="text-xs text-slate-500">
          The image hash is re-verified first. Carving is vendor-agnostic H.264/H.265 recovery; results are leads
          to be reviewed, not a statement of what was recorded. No vendor is validated on a real image (no Tier A).
        </p>
      </section>
      {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
      {note && <p className="text-sm text-slate-300">{note}</p>}
      {run && (
        <>
          <section className="rounded-lg bg-navy-800 p-5 text-sm" data-testid="vendor-section">
            <h2 className="mb-2 font-medium">Vendor identification</h2>
            {run.vendor_matches.length === 0 ? (
              <p className="text-slate-300">Unknown vendor: no documented signature found. Clips below were still carved generically.</p>
            ) : (
              run.vendor_matches.map((m) => (
                <div key={m.vendor} className="mb-3 space-y-1">
                  <div>
                    <span className="font-semibold">{m.vendor}</span> · Tier {m.tier} · confidence <b>{m.confidence}</b>
                  </div>
                  <ul className="list-disc pl-5 text-xs text-slate-400">
                    {m.evidence.slice(0, 8).map((h, i) => (
                      <li key={i}><span className="font-mono">{hex(h.offset)}</span> {h.detail}</li>
                    ))}
                    {m.notes.map((n, i) => <li key={`n${i}`} className="text-amber-300">{n}</li>)}
                  </ul>
                </div>
              ))
            )}
          </section>
          <section className="rounded-lg bg-navy-800 p-5 text-xs text-slate-400">
            Run #{run.id} {run.status} · tool {run.tool_version} · {run.ffmpeg_version} · identify {run.identify_seconds.toFixed(2)} s · carve {run.carve_seconds.toFixed(2)} s ·{' '}
            {clips.length} clips, {orphans.length} orphans, {run.stats.decode_errors ?? 0} with decode errors, {run.stats.export_failed ?? 0} export failures
            {run.error && <span className="text-red-400"> · {run.error}</span>}
          </section>
          <section className="overflow-x-auto rounded-lg bg-navy-800 p-5">
            <h2 className="mb-2 font-medium">Clips</h2>
            {clips.length === 0 ? (
              <p className="text-sm text-slate-400">No clips recovered.</p>
            ) : (
              <table className="w-full text-left text-sm">
                <thead className="text-slate-400">
                  <tr><th className="py-1">#</th><th>Codec</th><th>Offsets</th><th>SHA-256</th><th>Stream</th><th>Decode test</th><th>Preview</th></tr>
                </thead>
                <tbody>{clips.map((c) => <ClipItem key={c.id} clip={c} onVerify={verifyClip} />)}</tbody>
              </table>
            )}
          </section>
          {orphans.length > 0 && (
            <section className="rounded-lg bg-navy-800 p-5 text-sm" data-testid="orphans">
              <h2 className="mb-2 font-medium">Orphan fragments (not exported)</h2>
              <ul className="space-y-1 text-xs text-slate-300">
                {orphans.map((o) => (
                  <li key={o.id}>
                    <span className="font-mono">{o.start_offset.toLocaleString()} – {o.end_offset.toLocaleString()}</span>{' '}
                    {o.codec}, {o.nal_count} NAL units: {o.reason}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  )
}
