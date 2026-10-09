import { useState } from 'react'
import { useAuth } from '../../auth/AuthContext'
import { errorText } from '../../lib/http'
import { ianaZones } from '../timeline/api'
import { Button, DataTable, Field, HashText, Loadable, READONLY_HINT, fmtBytes, inputClass, useAsync, useToast } from '../../ui'
import { corrApi } from './api'

function ImportForm({ caseId, onDone }: { caseId: number; onDone: () => void }) {
  const toast = useToast()
  const topo = useAsync(() => corrApi.topology(caseId), [caseId])
  const [filename, setFilename] = useState('')
  const [content, setContent] = useState('')
  const [delimiter, setDelimiter] = useState(',')
  const [auth, setAuth] = useState('')
  const [tz, setTz] = useState('')
  const [fmt, setFmt] = useState('%Y-%m-%d %H:%M:%S')
  const [cols, setCols] = useState({ time: '', event: '', location: '' })
  const [locMap, setLocMap] = useState('')
  const [busy, setBusy] = useState(false)
  const headers = content ? (content.split(/\r?\n/)[0] ?? '').split(delimiter).map((h) => h.trim().replace(/^"|"$/g, '')).filter(Boolean) : []
  const zones = ianaZones()

  const pick = async (f: File | undefined) => {
    if (!f) return
    setFilename(f.name)
    setContent(await f.text())
  }
  const submit = async () => {
    const location_nodes: Record<string, string> = {}
    for (const line of locMap.split('\n')) {
      const [k, v] = line.split('=').map((x) => x.trim())
      if (k && v) location_nodes[k] = v
    }
    setBusy(true)
    try {
      const r = await corrApi.importLog(caseId, {
        filename,
        content,
        authorization_note: auth,
        timezone: tz,
        time_format: fmt,
        mapping: { time: cols.time, ...(cols.event ? { event: cols.event } : {}), ...(cols.location ? { location: cols.location } : {}) },
        location_nodes,
        delimiter,
      })
      toast.ok(`Imported ${r.row_count} rows (${r.rows_unplaced} without a usable time). Custody entry written.`)
      setContent('')
      setFilename('')
      onDone()
    } catch (e) {
      toast.error(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  const ready = filename && content && auth.trim() && tz && fmt && cols.time
  const nodes = topo.data?.nodes.map((n) => n.id).join(', ')
  return (
    <section aria-labelledby="imp-h" className="space-y-3">
      <h2 id="imp-h" className="font-medium">Import an authorised log (CSV)</h2>
      <p className="text-sm text-slate-300">For example door-access records obtained under legal authority. The device timezone has no default: state it, as on the Timeline. Times are converted with the same rules, and rows whose time cannot be read are kept, unplaced, with the reason.</p>
      <div className="grid gap-3 md:grid-cols-3">
        <Field label="CSV file"><input aria-label="Log file" type="file" accept=".csv,text/csv,text/plain" onChange={(e) => pick(e.target.files?.[0])} className="text-sm" /></Field>
        <Field label="Delimiter"><input aria-label="Delimiter" maxLength={1} className={inputClass} value={delimiter} onChange={(e) => setDelimiter(e.target.value || ',')} /></Field>
        <Field label="Authorisation note (legal authority or consent)"><input aria-label="Authorisation note" className={inputClass} value={auth} onChange={(e) => setAuth(e.target.value)} /></Field>
        <Field label="Timezone of the log (required)">
          <select aria-label="Log timezone" className={inputClass} value={tz} onChange={(e) => setTz(e.target.value)}>
            <option value="">choose a timezone</option>
            {zones.map((z) => <option key={z}>{z}</option>)}
          </select>
        </Field>
        <Field label="Time format (strptime, wall clock)"><input aria-label="Time format" className={inputClass} value={fmt} onChange={(e) => setFmt(e.target.value)} /></Field>
        <Field label="Time column">
          <select aria-label="Time column" className={inputClass} value={cols.time} onChange={(e) => setCols({ ...cols, time: e.target.value })}><option value="">choose</option>{headers.map((h) => <option key={h}>{h}</option>)}</select>
        </Field>
        <Field label="Event column (optional)">
          <select aria-label="Event column" className={inputClass} value={cols.event} onChange={(e) => setCols({ ...cols, event: e.target.value })}><option value="">none</option>{headers.map((h) => <option key={h}>{h}</option>)}</select>
        </Field>
        <Field label="Location column (optional)">
          <select aria-label="Location column" className={inputClass} value={cols.location} onChange={(e) => setCols({ ...cols, location: e.target.value })}><option value="">none</option>{headers.map((h) => <option key={h}>{h}</option>)}</select>
        </Field>
        <Field label="Location to camera (one per line: Location=camera id)" hint={nodes ? `Defined cameras: ${nodes}` : 'Define cameras on the Camera map tab first.'}>
          <textarea aria-label="Location mapping" rows={3} className={inputClass} value={locMap} onChange={(e) => setLocMap(e.target.value)} />
        </Field>
      </div>
      <Button variant="primary" busy={busy} disabled={!ready} onClick={submit}>Import log</Button>
    </section>
  )
}

export function ExternalLogs({ caseId }: { caseId: number }) {
  const { can } = useAuth()
  const logs = useAsync(() => corrApi.logs(caseId), [caseId])
  return (
    <div className="space-y-5">
      <Loadable state={logs}>
        {(rows) => (
          <DataTable
            testId="logs-table"
            caption="Imported external logs"
            rows={rows}
            rowKey={(l) => l.id}
            empty={{ title: 'No external logs imported', hint: can('case.write') ? 'Import an authorised CSV below.' : 'An examiner imports logs.' }}
            columns={[
              { key: 'f', header: 'File', sort: (l) => l.filename, render: (l) => l.filename },
              { key: 'sha', header: 'SHA-256', render: (l) => <HashText value={l.sha256} label="log SHA-256" /> },
              { key: 'sz', header: 'Size', render: (l) => fmtBytes(l.size_bytes) },
              { key: 'tz', header: 'Timezone', render: (l) => l.timezone },
              { key: 'rows', header: 'Rows (unplaced)', render: (l) => `${l.row_count} (${l.rows_unplaced})` },
              { key: 'auth', header: 'Authority', render: (l) => l.authorization_note },
              { key: 'by', header: 'Imported by', render: (l) => l.examiner },
            ]}
          />
        )}
      </Loadable>
      {can('case.write') ? <ImportForm caseId={caseId} onDone={logs.reload} /> : <p className="text-sm text-slate-300">{READONLY_HINT}</p>}
    </div>
  )
}
