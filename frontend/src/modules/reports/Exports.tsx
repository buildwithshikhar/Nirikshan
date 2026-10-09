import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { download, errorText } from '../../lib/http'
import { Button, Can, Card, Chip, DataTable, Field, HashText, KV, Loadable, PageHeader, Tabs, fmtBytes, fmtTime, inputClass, useAsync, useToast, Unavailable, READONLY_HINT } from '../../ui'
import { useAuth } from '../../auth/AuthContext'
import { api } from '../../api'
import { reportsApi } from './api'
import { StatusLabel } from './Builder'
import { ReportsNav } from './ReportsNav'

function JsonLdCsvTab({ caseId }: { caseId: number }) {
  const toast = useToast()
  const dl = (path: string, name: string) => download(path, name).catch((e) => toast.error(errorText(e)))
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-300">
        Machine-readable exports of the case record. JSON-LD carries the case, evidence, hashes and custody chain; the timeline export lists clip times with their
        timezone status. Neither is a signed document.
      </p>
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" onClick={() => dl(`/api/cases/${caseId}/export.jsonld`, `case${caseId}.jsonld`)}>Export case JSON-LD</Button>
        <Button onClick={() => dl(`/api/cases/${caseId}/timeline/export?format=csv`, `timeline-case-${caseId}.csv`)}>Export timeline CSV</Button>
        <Button onClick={() => dl(`/api/cases/${caseId}/timeline/export?format=json`, `timeline-case-${caseId}.json`)}>Export timeline JSON</Button>
      </div>
    </div>
  )
}

function TransfersSection({ caseId }: { caseId: number }) {
  const { can } = useAuth()
  const toast = useToast()
  const list = useAsync(() => reportsApi.transfers(caseId), [caseId])
  const evidence = useAsync(() => api.listEvidence(caseId), [caseId])
  const [f, setF] = useState({ evidence_id: 0, from_party: '', to_party: '', reason: '', location: '', seal: '' })
  const [busy, setBusy] = useState(false)
  const submit = async () => {
    const eid = f.evidence_id || evidence.data?.[0]?.id
    if (!eid) return
    setBusy(true)
    try {
      await reportsApi.addTransfer(eid, { from_party: f.from_party, to_party: f.to_party, reason: f.reason, location: f.location, seal: f.seal })
      toast.ok('Transfer recorded (custody entry written).')
      setF({ ...f, from_party: '', to_party: '', reason: '', location: '', seal: '' })
      list.reload()
    } catch (e) {
      toast.error(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="space-y-3" aria-labelledby="transfers-h">
      <h3 id="transfers-h" className="font-medium">Evidence transfers (chain of possession)</h3>
      <Loadable state={list}>
        {(rows) => (
          <DataTable
            testId="transfers-table"
            caption="Evidence transfers"
            rows={rows}
            rowKey={(t) => t.id}
            empty={{ title: 'No transfers recorded', hint: can('case.write') ? 'Record a handover below.' : 'An examiner records handovers.' }}
            columns={[
              { key: 'ev', header: 'Evidence', sort: (t) => t.evidence_id, render: (t) => `#${t.evidence_id}` },
              { key: 'from', header: 'From', render: (t) => t.from_party, sort: (t) => t.from_party },
              { key: 'to', header: 'To', render: (t) => t.to_party, sort: (t) => t.to_party },
              { key: 'at', header: 'When', render: (t) => fmtTime(t.transferred_at), sort: (t) => t.transferred_at },
              { key: 'why', header: 'Reason', render: (t) => t.reason },
              { key: 'seal', header: 'Seal / place', render: (t) => [t.seal, t.location].filter(Boolean).join(' / ') || '—' },
              { key: 'seq', header: 'Custody #', render: (t) => t.custody_seq ?? '—' },
            ]}
          />
        )}
      </Loadable>
      {can('case.write') ? (
        <div className="grid gap-3 md:grid-cols-3">
          <Field label="Evidence item">
            <select aria-label="Transfer evidence" className={inputClass} value={f.evidence_id || evidence.data?.[0]?.id || 0} onChange={(e) => setF({ ...f, evidence_id: Number(e.target.value) })}>
              {(evidence.data ?? []).map((e) => <option key={e.id} value={e.id}>#{e.id} {e.label}</option>)}
            </select>
          </Field>
          <Field label="From"><input aria-label="Transfer from" className={inputClass} value={f.from_party} onChange={(e) => setF({ ...f, from_party: e.target.value })} /></Field>
          <Field label="To"><input aria-label="Transfer to" className={inputClass} value={f.to_party} onChange={(e) => setF({ ...f, to_party: e.target.value })} /></Field>
          <Field label="Reason"><input aria-label="Transfer reason" className={inputClass} value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} /></Field>
          <Field label="Location"><input aria-label="Transfer location" className={inputClass} value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} /></Field>
          <Field label="Seal number"><input aria-label="Transfer seal" className={inputClass} value={f.seal} onChange={(e) => setF({ ...f, seal: e.target.value })} /></Field>
          <div><Button busy={busy} onClick={submit}>Record transfer</Button></div>
        </div>
      ) : (
        <p className="text-sm text-slate-300">{READONLY_HINT}</p>
      )}
    </section>
  )
}

function PackageTab({ caseId }: { caseId: number }) {
  const toast = useToast()
  const list = useAsync(() => reportsApi.packages(caseId), [caseId])
  const reports = useAsync(() => reportsApi.list(caseId), [caseId])
  const key = useAsync(() => reportsApi.packageKey(), [])
  const [clips, setClips] = useState(true)
  const [pass, setPass] = useState('')
  const [busy, setBusy] = useState(false)
  const build = async () => {
    setBusy(true)
    try {
      const p = await reportsApi.buildPackage(caseId, { include_clips: clips, ...(pass ? { passphrase: pass } : {}) })
      toast.ok(`Package ${p.id} built (${fmtBytes(p.size_bytes)}, custody entry written).`)
      setPass('')
      list.reload()
    } catch (e) {
      toast.error(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-300">
        An evidence package is a signed ZIP: manifest, case record, custody chain, stored report PDFs that still match their hash, and (optionally) clips. It is
        verified offline, not trusted because it was downloaded from here.
      </p>
      <section aria-labelledby="pkg-reports" className="space-y-2">
        <h3 id="pkg-reports" className="font-medium">Approval status of the reports a package would include</h3>
        <Loadable state={reports}>
          {(rows) => (
            <DataTable
              testId="package-reports"
              caption="Reports and their approval status"
              rows={rows}
              rowKey={(r) => r.id}
              empty={{ title: 'No reports yet', hint: 'Generate one in the Builder; a package without reports still carries the case record and custody chain.' }}
              columns={[
                { key: 'id', header: 'Report', render: (r) => `#${r.id}`, sort: (r) => r.id },
                { key: 'sha', header: 'SHA-256', render: (r) => <HashText value={r.sha256} label="report SHA-256" /> },
                { key: 'st', header: 'Approval', render: (r) => <StatusLabel status={r.review_status} />, sort: (r) => r.review_status },
              ]}
            />
          )}
        </Loadable>
        <p className="text-xs text-slate-300">A package records each report's review status in its manifest. Only an approved or final report should be relied on.</p>
      </section>
      <Can perm="case.write">
        <section aria-labelledby="pkg-build" className="space-y-2">
          <h3 id="pkg-build" className="font-medium">Build a package</h3>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={clips} onChange={(e) => setClips(e.target.checked)} /> Include recovered clips
          </label>
          <div className="max-w-sm">
            <Field label="Passphrase (optional, encrypts the package; minimum length enforced by the server)">
              <input aria-label="Package passphrase" type="password" autoComplete="new-password" className={inputClass} value={pass} onChange={(e) => setPass(e.target.value)} />
            </Field>
          </div>
          <Button variant="primary" busy={busy} onClick={build}>Build package</Button>
        </section>
      </Can>
      <Loadable state={list}>
        {(rows) => (
          <DataTable
            testId="package-table"
            caption="Built evidence packages"
            rows={rows}
            rowKey={(p) => p.id}
            empty={{ title: 'No package built yet', hint: 'An examiner builds one with the form above.' }}
            columns={[
              { key: 'id', header: '#', render: (p) => p.id, sort: (p) => p.id },
              { key: 'at', header: 'Created', render: (p) => fmtTime(p.created_at), sort: (p) => p.created_at },
              { key: 'sha', header: 'SHA-256', render: (p) => <HashText value={p.sha256} label="package SHA-256" /> },
              { key: 'size', header: 'Size', render: (p) => `${fmtBytes(p.size_bytes)}, ${p.file_count} files` },
              { key: 'enc', header: 'Encrypted', render: (p) => (p.encrypted ? <Chip tone="info">AES-256-GCM</Chip> : <Chip>no</Chip>) },
              {
                key: 'act',
                header: 'Actions',
                render: (p) => (
                  <Button aria-label={`Download package ${p.id}`} onClick={() => download(`/api/packages/${p.id}/download`, p.file_name).catch((e) => toast.error(errorText(e)))}>
                    Download
                  </Button>
                ),
              },
            ]}
          />
        )}
      </Loadable>
      <section aria-labelledby="pkg-verify" className="space-y-2">
        <h3 id="pkg-verify" className="font-medium">Verify a package (offline)</h3>
        <Loadable state={list}>
          {(rows) => (
            <pre data-testid="verify-instructions" className="overflow-x-auto rounded bg-navy-900 p-3 text-xs">
              {`python -m app.cli verify-package ${rows[0]?.file_name ?? '<package.zip>'} --expect-key-id ${key.data?.key_id ?? '<key id>'}`}
            </pre>
          )}
        </Loadable>
        <p className="text-xs text-slate-300">
          Run it on a different machine from the one that built the package. Pin the expected key id (below) so a swapped signing key is detected. Encrypted
          packages need the passphrase. See docs/package.md.
        </p>
        {key.error ? (
          <Unavailable what="Package signing key" reason={key.error.message} />
        ) : key.data ? (
          <KV items={[['Algorithm', key.data.algorithm], ['Key id', <HashText key="k" value={key.data.key_id} label="key id" head={16} />], ['Public key', <HashText key="p" value={key.data.public_key_hex} label="public key" head={16} />]]} />
        ) : null}
      </section>
      <TransfersSection caseId={caseId} />
    </div>
  )
}

export default function Exports() {
  const caseId = Number(useParams().caseId)
  return (
    <div>
      <PageHeader title="Exports" subtitle="JSON-LD and CSV exports, and the signed evidence package. Reference test data only; nothing here is validated on a real device." />
      <ReportsNav caseId={caseId} />
      <Card>
        <Tabs
          label="Exports"
          tabs={[
            { id: 'jsonld', label: 'JSON-LD and CSV', render: () => <JsonLdCsvTab caseId={caseId} /> },
            { id: 'package', label: 'Evidence package with approval status', render: () => <PackageTab caseId={caseId} /> },
          ]}
        />
      </Card>
    </div>
  )
}
