import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { EvidencePicker } from '../../shell/EvidencePicker'
import { Button, Card, Chip, DataTable, EmptyState, Field, KV, Loadable, PageHeader, Tabs, fmtBytes, inputClass, useAsync, useToast } from '../../ui'
import { type HexRead, type Region, explorerApi } from './api'

const hex = (n: number) => `0x${n.toString(16)}`
const KIND_FILL: Record<string, string> = {
  parser_clip: '#34d399', carved_clip: '#38bdf8', orphan: '#fbbf24', structure: '#f97316', zero: '#334155', unknown: '#a78bfa', not_scanned: '#0f172a',
}

function LayoutTab({ evId }: { evId: number }) {
  const state = useAsync((s) => explorerApi.regions(evId, s), [evId])
  return (
    <Loadable state={state} rows={4}>
      {(r) => {
        const total = Math.max(r.image_size, 1)
        const kinds = Object.entries(r.summary)
        const label = `Layout map of ${fmtBytes(r.image_size)}: ${kinds.map(([k, v]) => `${k.replace('_', ' ')} ${(v.fraction * 100).toFixed(1)} percent`).join(', ')}`
        return (
          <div className="space-y-4">
            <Card title="Layout map">
              <svg role="img" aria-label={label} viewBox="0 0 1000 40" preserveAspectRatio="none" className="h-10 w-full rounded ring-1 ring-navy-600" data-testid="layout-svg">
                {r.regions.map((g, i) => (
                  <rect key={i} x={(g.start / total) * 1000} width={Math.max(0.5, (g.bytes / total) * 1000)} height={40} fill={KIND_FILL[g.kind] ?? '#64748b'} />
                ))}
              </svg>
              <ul className="mt-2 flex flex-wrap gap-3 text-xs" aria-label="Legend">
                {kinds.map(([k, v]) => (
                  <li key={k} className="flex items-center gap-1">
                    <span aria-hidden="true" className="inline-block h-3 w-3 rounded-sm ring-1 ring-slate-400" style={{ background: KIND_FILL[k] ?? '#64748b' }} />
                    {k.replace('_', ' ')}: {fmtBytes(v.bytes)} in {v.regions} region(s), {(v.fraction * 100).toFixed(1)}%
                  </li>
                ))}
              </ul>
              {r.truncated && <p className="mt-2 text-xs text-amber-300">The region list is truncated; the summary above covers all regions.</p>}
              {r.notes.map((n) => <p key={n} className="mt-1 text-xs text-slate-400">{n}</p>)}
            </Card>
            <Card title="Regions (table alternative to the map)">
              <DataTable<Region>
                rows={r.regions}
                caption="Regions of the image"
                rowKey={(g) => g.start}
                pageSize={10}
                columns={[
                  { key: 'k', header: 'Kind', sort: (g) => g.kind, render: (g) => g.kind.replace('_', ' ') },
                  { key: 's', header: 'Start', sort: (g) => g.start, render: (g) => <span className="font-mono text-xs">{hex(g.start)}</span> },
                  { key: 'e', header: 'End', sort: (g) => g.end, render: (g) => <span className="font-mono text-xs">{hex(g.end)}</span> },
                  { key: 'b', header: 'Bytes', sort: (g) => g.bytes, render: (g) => g.bytes.toLocaleString() },
                  { key: 'r', header: 'Reference', render: (g) => (g.ref ? `${g.ref.vendor ?? ''} ${g.ref.signature ?? ''}` : '—'), text: (g) => `${g.ref?.vendor ?? ''} ${g.ref?.signature ?? ''}` },
                ]}
                empty={{ title: 'No regions', hint: 'Run an analysis in the Recovery lab first.' }}
              />
            </Card>
          </div>
        )
      }}
    </Loadable>
  )
}

function VendorTab({ evId }: { evId: number }) {
  const regions = useAsync((s) => explorerApi.regions(evId, s), [evId])
  const parts = useAsync((s) => explorerApi.partitions(evId, s), [evId])
  return (
    <div className="space-y-4">
      <Card title="Vendor structures found">
        <Loadable state={regions} rows={3}>
          {(r) => (
            <DataTable<Region>
              rows={r.regions.filter((g) => g.kind === 'structure')}
              caption="Vendor and partition structures located by signature"
              rowKey={(g) => g.start}
              columns={[
                { key: 'v', header: 'Vendor', sort: (g) => String(g.ref?.vendor ?? ''), render: (g) => String(g.ref?.vendor ?? 'partition table') },
                { key: 'sig', header: 'Signature', sort: (g) => String(g.ref?.signature ?? ''), render: (g) => <code className="text-xs">{String(g.ref?.signature ?? '—')}</code> },
                { key: 'o', header: 'Offset', sort: (g) => g.start, render: (g) => <span className="font-mono text-xs">{hex(g.start)}</span> },
                { key: 'b', header: 'Bytes', sort: (g) => g.bytes, render: (g) => g.bytes },
                { key: 'd', header: 'Detail', render: (g) => String(g.ref?.detail ?? '') },
              ]}
              empty={{ title: 'No vendor structures located', hint: 'Signatures come from public research only; an unknown device shows none.' }}
            />
          )}
        </Loadable>
      </Card>
      <Card title="Partition tables">
        <Loadable state={parts} rows={2}>
          {(p) => (
            <div className="space-y-1 text-sm">
              <KV items={[['Scheme', p.scheme], ['Filesystem signatures', String(p.filesystems.length)]]} />
              <p className="text-xs text-slate-400">{p.note}</p>
            </div>
          )}
        </Loadable>
      </Card>
    </div>
  )
}

function AnomaliesTab({ evId }: { evId: number }) {
  const state = useAsync((s) => explorerApi.anomalies(evId, s), [evId])
  return (
    <Card title="Anomalies">
      <Loadable state={state} rows={3}>
        {(a) => (
          <>
            <p className="mb-2 text-sm">{a.count} item(s), {a.warnings} warning(s).{a.note ? ` ${a.note}` : ''}</p>
            <DataTable
              rows={a.anomalies}
              caption="Structural anomalies"
              rowKey={(x) => `${x.kind}-${x.offset}-${x.source}-${String(x.detail)}`}
              columns={[
                { key: 's', header: 'Severity', sort: (x) => x.severity, render: (x) => <Chip tone={x.severity === 'warning' ? 'warn' : 'info'}>{x.severity}</Chip> },
                { key: 'k', header: 'Kind', sort: (x) => x.kind, render: (x) => x.kind },
                { key: 'o', header: 'Offset', sort: (x) => x.offset ?? -1, render: (x) => (x.offset != null ? <span className="font-mono text-xs">{hex(x.offset)}</span> : '—') },
                { key: 'd', header: 'Detail', render: (x) => <span className="break-all text-xs">{x.detail == null ? '' : typeof x.detail === 'string' ? x.detail : JSON.stringify(x.detail)} {x.source ?? ''}</span> },
              ]}
              empty={{ title: 'No anomalies found', hint: 'Nothing structurally inconsistent was detected in this analysis run.' }}
            />
          </>
        )}
      </Loadable>
    </Card>
  )
}

const parseOffset = (s: string) => (/^0x/i.test(s.trim()) ? parseInt(s.trim(), 16) : Number(s.trim()))

function HexView({ evId, size }: { evId: number; size: number }) {
  const toast = useToast()
  const [off, setOff] = useState('0')
  const [len, setLen] = useState(256)
  const [data, setData] = useState<HexRead | null>(null)
  const [busy, setBusy] = useState(false)
  const read = async () => {
    const o = parseOffset(off)
    if (!Number.isInteger(o) || o < 0 || o >= size) {
      toast.error(new Error(`Offset must be between 0 and ${size - 1} (decimal or 0x hex)`))
      return
    }
    const l = Math.min(4096, Math.max(1, Math.floor(len) || 1))
    setLen(l)
    setBusy(true)
    try {
      setData(await explorerApi.hex(evId, o, l))
    } catch (e) {
      toast.error(e)
    } finally {
      setBusy(false)
    }
  }
  const rows: { off: number; bytes: string[]; ascii: string }[] = []
  if (data) {
    const b = data.hex.match(/../g) ?? []
    for (let i = 0; i < b.length; i += 16) rows.push({ off: data.offset + i, bytes: b.slice(i, i + 16), ascii: data.ascii.slice(i, i + 16) })
  }
  return (
    <Card title="Hex view (read-only, at most 4096 bytes per read)">
      <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); void read() }}>
        <Field label="Offset (decimal or 0x hex)"><input className={`${inputClass} w-40 font-mono`} value={off} onChange={(e) => setOff(e.target.value)} /></Field>
        <Field label="Length (1 to 4096)"><input type="number" className={`${inputClass} w-28`} value={len} onChange={(e) => setLen(Number(e.target.value))} /></Field>
        <Button type="submit" variant="primary" busy={busy}>Read bytes</Button>
      </form>
      {data ? (
        <div className="mt-3">
          <pre tabIndex={0} aria-label="Hex dump" data-testid="hex-dump" className="overflow-x-auto rounded bg-navy-900 p-3 font-mono text-xs leading-5">
            {rows.map((r) => `${r.off.toString(16).padStart(8, '0')}  ${r.bytes.join(' ').padEnd(47, ' ')}  |${r.ascii.replace(/[^\x20-\x7e]/g, '.')}|`).join('\n')}
          </pre>
          <p className="mt-1 text-xs text-slate-400">{data.length} bytes from {hex(data.offset)}; SHA-256 of these bytes {data.bytes_sha256.slice(0, 16)}…. Reads are audited; nothing here can modify the evidence.</p>
        </div>
      ) : (
        <div className="mt-3"><EmptyState title="No bytes read yet" hint="Enter an offset and choose Read bytes." /></div>
      )}
    </Card>
  )
}

function Explorer({ evId, size }: { evId: number; size: number }) {
  return (
    <div className="space-y-4">
      <Tabs
        label="Explorer sections"
        tabs={[
          { id: 'layout', label: 'Layout map', render: () => <LayoutTab evId={evId} /> },
          { id: 'vendor', label: 'Vendor structures', render: () => <VendorTab evId={evId} /> },
          { id: 'anomalies', label: 'Anomalies', render: () => <AnomaliesTab evId={evId} /> },
        ]}
      />
      <HexView evId={evId} size={size} />
    </div>
  )
}

export default function ExplorerModule() {
  const caseId = Number(useParams().caseId)
  return (
    <div>
      <PageHeader title="Offset map" subtitle="Storage explorer: where things are in the image. Read-only." />
      <EvidencePicker caseId={caseId}>{(ev) => <Explorer key={ev.id} evId={ev.id} size={ev.size_bytes} />}</EvidencePicker>
    </div>
  )
}
